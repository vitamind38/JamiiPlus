"""Grouping reports into issues, and the officer responses that close the loop by SMS."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from jamii_api import messages
from jamii_api.config import get_settings
from jamii_api.db.base import utcnow
from jamii_api.models import (
    Chp,
    Issue,
    IssueStatus,
    Level,
    Report,
    ReportStatus,
    Resolution,
    Response,
    ResponseKind,
    Theme,
    User,
)
from jamii_api.sms import queue_sms

MAX_ACTION_CHARS = 300


class IssueError(ValueError):
    pass


def find_open_issue(db: Session, theme_code: str, report: Report) -> Issue | None:
    return db.scalar(
        select(Issue)
        .where(
            Issue.theme_code == theme_code,
            Issue.ward == report.ward,
            Issue.sub_county == report.sub_county,
            Issue.county == report.county,
            Issue.status != IssueStatus.RESOLVED,
        )
        .order_by(Issue.last_reported_at.desc())
        .limit(1)
    )


def new_issue(db: Session, theme_code: str, report: Report) -> Issue:
    issue = Issue(
        theme_code=theme_code,
        ward=report.ward,
        sub_county=report.sub_county,
        county=report.county,
        level=get_settings().issue_default_level,
        status=IssueStatus.RECEIVED,
        report_count=0,
        first_reported_at=report.created_at,
        last_reported_at=report.created_at,
    )
    db.add(issue)
    db.flush()
    return issue


def attach(db: Session, report: Report, issue: Issue) -> None:
    if report.issue_id == issue.id:
        return
    if report.issue_id is not None:
        detach(db, report)
    report.issue_id = issue.id
    report.issue = issue
    report.status = ReportStatus.GROUPED
    issue.report_count += 1
    issue.first_reported_at = min(issue.first_reported_at, report.created_at)
    issue.last_reported_at = max(issue.last_reported_at, report.created_at)


def detach(db: Session, report: Report) -> None:
    issue = report.issue or (db.get(Issue, report.issue_id) if report.issue_id else None)
    report.issue_id = None
    report.issue = None
    if issue is None:
        return
    issue.report_count = max(0, issue.report_count - 1)
    has_responses = db.scalar(select(Response.id).where(Response.issue_id == issue.id).limit(1))
    if issue.report_count == 0 and not has_responses:
        db.flush()
        db.delete(issue)


def group(db: Session, report: Report, theme_code: str, *, force_new: bool = False) -> Issue:
    """Join the open issue for this theme and ward, or start one."""
    issue = None if force_new else find_open_issue(db, theme_code, report)
    if issue is None:
        issue = new_issue(db, theme_code, report)
    attach(db, report, issue)
    return issue


def recipients(db: Session, issue: Issue) -> list[Chp]:
    """Every active CHP with a live report in the issue, once each."""
    return list(
        db.scalars(
            select(Chp)
            .join(Report, Report.chp_id == Chp.id)
            .where(Report.issue_id == issue.id, Report.status == ReportStatus.GROUPED, Chp.active.is_(True))
            .distinct()
        )
    )


@dataclass
class Draft:
    kind: ResponseKind
    action_text: str
    resolution: Resolution | None
    new_level: Level | None
    sms_by_language: dict[str, str]
    recipient_count: int


def _sms_key(kind: ResponseKind, resolution: Resolution | None) -> str:
    if kind == ResponseKind.RESOLVED:
        return "resolved_not_actioned" if resolution == Resolution.NOT_ACTIONED else "resolved_actioned"
    return kind.value


def draft_response(
    db: Session,
    issue: Issue,
    officer: User,
    kind: ResponseKind,
    action_text: str,
    resolution: Resolution | None = None,
) -> Draft:
    """Build exactly what will be sent, so the officer sees it before releasing it."""
    action_text = " ".join((action_text or "").split())
    if kind != ResponseKind.RESOLVED:
        resolution = None  # only a resolution says whether the problem was acted on
    if issue.status == IssueStatus.RESOLVED:
        raise IssueError("This issue is already resolved.")
    if len(action_text) > MAX_ACTION_CHARS:
        raise IssueError(f"Keep the message under {MAX_ACTION_CHARS} characters so it fits in an SMS.")
    new_level = None
    if kind == ResponseKind.ESCALATED:
        new_level = Level(issue.level).next()
        if new_level is None:
            raise IssueError("This issue is already at the national level.")
    elif not action_text:
        raise IssueError("Write what was done, or why nothing was done. CHPs will read it.")
    if kind == ResponseKind.RESOLVED and resolution is None:
        raise IssueError("Choose whether the problem was acted on.")

    theme: Theme = issue.theme
    people = recipients(db, issue)
    by_lang: dict[str, str] = {}
    for language in sorted({messages.lang(c.language) for c in people} or {"sw"}):
        by_lang[language] = messages.sms(
            _sms_key(kind, resolution),
            language,
            theme=theme.label(language),
            ward=issue.ward,
            level=messages.level_name(new_level.value if new_level else issue.level, language),
            issue_id=issue.id,
            text=action_text,
            officer=officer.name,
        )
    return Draft(kind, action_text, resolution, new_level, by_lang, len(people))


def release_response(db: Session, issue: Issue, officer: User, draft: Draft) -> tuple[Response, list[int]]:
    """Record the response, move the issue on, and queue one SMS per CHP. Caller commits, then dispatches."""
    now = utcnow()
    if draft.kind == ResponseKind.ESCALATED:
        issue.level = draft.new_level
        issue.status = IssueStatus.ESCALATED
    elif draft.kind == ResponseKind.ACTION_TAKEN:
        issue.status = IssueStatus.ACTION_TAKEN
    else:
        issue.status = IssueStatus.RESOLVED
        issue.resolution = draft.resolution
        issue.resolved_at = now
    if issue.owner_id is None:
        issue.owner_id = officer.id
    if issue.first_response_at is None:
        issue.first_response_at = now

    people = recipients(db, issue)
    resp = Response(
        issue_id=issue.id,
        officer_id=officer.id,
        kind=draft.kind,
        action_text=draft.action_text or f"Escalated to {draft.new_level}",
        sms_text="\n---\n".join(f"[{k}] {v}" for k, v in draft.sms_by_language.items()),
        recipients=len(people),
        sms_sent=len(people) == 0,
        created_at=now,
    )
    db.add(resp)
    db.flush()
    ids = []
    for chp in people:
        text = draft.sms_by_language.get(messages.lang(chp.language)) or next(iter(draft.sms_by_language.values()))
        ids.append(queue_sms(db, phone=chp.phone, message=text, kind="status", chp_id=chp.id, response_id=resp.id).id)
    return resp, ids
