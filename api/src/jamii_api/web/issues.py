"""Issues: officers read the evidence, then escalate, record action or resolve.

Nothing reaches a CHP until the officer has seen the exact SMS and pressed send.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from jamii_api import audit, sms
from jamii_api.deps import DB, SessionUser, client_ip
from jamii_api.models import (
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
from jamii_api.services import issues, scope
from jamii_api.web.common import check_csrf, flash, render

router = APIRouter(prefix="/issues", include_in_schema=False)
CSRF = [Depends(check_csrf)]


def _issue_for(db, user: User, issue_id: int) -> Issue:
    issue = db.get(Issue, issue_id)
    if issue is None or not scope.in_scope_issue(user, issue):
        raise HTTPException(404)
    return issue


@router.get("")
def list_issues(
    request: Request, db: DB, user: SessionUser, status: str = "open", theme: str | None = None, ward: str | None = None
):
    q = select(Issue).where(scope.issue_filter(user))
    if status == "open":
        q = q.where(Issue.status != IssueStatus.RESOLVED)
    elif status in {s.value for s in IssueStatus}:
        q = q.where(Issue.status == status)
    if theme:
        q = q.where(Issue.theme_code == theme)
    if ward:
        q = q.where(Issue.ward == ward)
    rows = db.scalars(q.order_by(Issue.last_reported_at.desc()).limit(300)).all()
    themes = db.scalars(select(Theme).order_by(Theme.sort_order)).all()
    wards = sorted(set(db.scalars(select(Issue.ward).where(scope.issue_filter(user)).distinct())))
    return render(
        request,
        "issues/list.html",
        user=user,
        issues=rows,
        status=status,
        theme=theme,
        ward=ward,
        themes=themes,
        wards=wards,
    )


@router.get("/{issue_id}")
def detail(request: Request, db: DB, user: SessionUser, issue_id: int):
    issue = _issue_for(db, user, issue_id)
    audit.record(
        "issue.viewed",
        actor_type="user",
        actor_id=user.id,
        object_type="issue",
        object_id=issue.id,
        ip=client_ip(request),
    )
    reports = (
        db.scalars(
            select(Report)
            .where(Report.issue_id == issue.id, Report.status == ReportStatus.GROUPED)
            .order_by(Report.created_at.desc())
        )
        .unique()
        .all()
    )
    responses = db.scalars(select(Response).where(Response.issue_id == issue.id).order_by(Response.created_at)).all()
    return render(
        request,
        "issues/detail.html",
        user=user,
        issue=issue,
        reports=reports,
        responses=responses,
        next_level=Level(issue.level).next(),
    )


def _draft(db, issue: Issue, user: User, kind: str, action_text: str, resolution: str | None):
    if not scope.can_act_on(user, issue):
        raise HTTPException(403, "Only officers at this issue's level or above can answer it.")
    try:
        kind_enum = ResponseKind(kind)
        res = Resolution(resolution) if resolution else None
    except ValueError:
        raise HTTPException(400, "Unknown action") from None
    return issues.draft_response(db, issue, user, kind_enum, action_text, res)


@router.post("/{issue_id}/preview", dependencies=CSRF)
def preview(
    request: Request,
    db: DB,
    user: SessionUser,
    issue_id: int,
    kind: Annotated[str, Form()],
    action_text: Annotated[str, Form()] = "",
    resolution: Annotated[str | None, Form()] = None,
):
    issue = _issue_for(db, user, issue_id)
    try:
        draft = _draft(db, issue, user, kind, action_text, resolution)
    except issues.IssueError as e:
        flash(request, str(e), "error")
        return RedirectResponse(f"/issues/{issue_id}#respond", 303)
    return render(request, "issues/preview.html", user=user, issue=issue, draft=draft)


@router.post("/{issue_id}/respond", dependencies=CSRF)
def respond(
    request: Request,
    db: DB,
    user: SessionUser,
    issue_id: int,
    kind: Annotated[str, Form()],
    action_text: Annotated[str, Form()] = "",
    resolution: Annotated[str | None, Form()] = None,
):
    issue = _issue_for(db, user, issue_id)
    try:
        draft = _draft(db, issue, user, kind, action_text, resolution)
    except issues.IssueError as e:
        flash(request, str(e), "error")
        return RedirectResponse(f"/issues/{issue_id}", 303)
    resp, sms_ids = issues.release_response(db, issue, user, draft)
    db.commit()
    audit.record(
        "issue.responded",
        actor_type="user",
        actor_id=user.id,
        object_type="issue",
        object_id=issue.id,
        kind=draft.kind.value,
        recipients=len(sms_ids),
        response_id=resp.id,
    )
    sms.dispatch(db, sms_ids)
    flash(request, f"Saved. {len(sms_ids)} CHP(s) will get the SMS.")
    return RedirectResponse(f"/issues/{issue_id}", 303)


@router.post("/{issue_id}/own", dependencies=CSRF)
def take_ownership(request: Request, db: DB, user: SessionUser, issue_id: int):
    issue = _issue_for(db, user, issue_id)
    if not scope.can_act_on(user, issue):
        raise HTTPException(403)
    issue.owner_id = user.id
    db.commit()
    audit.record("issue.owned", actor_type="user", actor_id=user.id, object_type="issue", object_id=issue.id)
    flash(request, "You now own this issue.")
    return RedirectResponse(f"/issues/{issue_id}", 303)
