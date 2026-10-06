"""The human review queue: redaction, transcription, tagging and the weekly re-check.

In manual mode every report passes through here. In assisted mode only what the models
were unsure about does, plus a random weekly sample of what they accepted.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from jamii_api import audit
from jamii_api.db.base import utcnow
from jamii_api.models import HUMAN_QUEUES, Classification, Report, ReportStatus, Transcript, User
from jamii_api.redaction import redact
from jamii_api.services import issues, scope
from jamii_api.services.reports import active_theme


class ReviewError(ValueError):
    pass


def queue(db: Session, user: User, status: str | None = None, limit: int = 100) -> list[Report]:
    statuses = [status] if status in HUMAN_QUEUES else list(HUMAN_QUEUES)
    return list(
        db.scalars(
            select(Report)
            .where(Report.status.in_(statuses), scope.report_filter(user))
            .order_by(Report.created_at)
            .limit(limit)
        ).unique()
    )


def recheck_queue(db: Session, user: User, limit: int = 100) -> list[Report]:
    return list(
        db.scalars(
            select(Report)
            .join(Classification, Classification.report_id == Report.id)
            .where(
                Classification.recheck_requested_at.isnot(None),
                Classification.rechecked_at.is_(None),
                Report.status == ReportStatus.GROUPED,
                scope.report_filter(user),
            )
            .order_by(Classification.recheck_requested_at)
            .limit(limit)
        ).unique()
    )


def queue_counts(db: Session, user: User) -> dict[str, int]:
    counts = {s.value: 0 for s in HUMAN_QUEUES}
    for r in queue(db, user, limit=10_000):
        counts[r.status] += 1
    counts["recheck"] = len(recheck_queue(db, user, limit=10_000))
    return counts


def save(
    db: Session,
    report: Report,
    reviewer: User,
    *,
    final_theme: str,
    text: str | None = None,
    transcript: str | None = None,
    new_issue: bool = False,
) -> None:
    """One reviewer decision: fix redaction, set the transcript, set the theme, group it."""
    if not scope.can_review(reviewer) or not scope.in_scope_report(reviewer, report):
        raise ReviewError("You cannot review this report.")
    if report.status not in HUMAN_QUEUES:
        raise ReviewError("This report has already been reviewed.")
    theme = active_theme(db, final_theme)
    if theme is None:
        raise ReviewError("Choose a theme.")
    now = utcnow()

    if report.status == ReportStatus.NEEDS_REDACTION:
        # The reviewer has removed anything the rules missed; run the rules once more anyway.
        report.raw_text = redact(text).text or None
        report.redaction = "manual"
        report.hold_reason = None

    if report.audio_key or report.transcript is not None:
        typed = (transcript or "").strip()
        if not typed and report.transcript is None:
            raise ReviewError("Type what the voice note says before saving.")
        if typed:
            _set_human_transcript(db, report, redact(typed).text, reviewer)

    cls = report.classification
    if cls is None:
        cls = Classification(report_id=report.id)
        db.add(cls)
        report.classification = cls
    cls.final_theme = theme.code
    cls.reviewed_by = reviewer.id
    cls.reviewed_at = now

    issues.group(db, report, theme.code, force_new=new_issue)
    audit.record(
        "report.reviewed",
        actor_type="user",
        actor_id=reviewer.id,
        object_type="report",
        object_id=report.id,
        theme=theme.code,
        model_theme=cls.theme,
    )


def _set_human_transcript(db: Session, report: Report, text: str, reviewer: User) -> None:
    t = report.transcript
    if t is None:
        report.transcript = Transcript(report_id=report.id, text=text, model_version="human", created_by=reviewer.id)
        db.add(report.transcript)
        return
    if t.model_version != "human" and t.machine_text is None:
        t.machine_text = t.text
        t.machine_model_version = t.model_version
    t.text = text
    t.model_version = "human"
    t.created_by = reviewer.id


def save_recheck(db: Session, report: Report, reviewer: User, theme_code: str) -> None:
    """Weekly re-check of a model-accepted report. A disagreement moves the report."""
    if not scope.can_review(reviewer) or not scope.in_scope_report(reviewer, report):
        raise ReviewError("You cannot review this report.")
    cls = report.classification
    if cls is None or cls.recheck_requested_at is None or cls.rechecked_at is not None:
        raise ReviewError("This report is not waiting for a re-check.")
    theme = active_theme(db, theme_code)
    if theme is None:
        raise ReviewError("Choose a theme.")
    cls.recheck_theme = theme.code
    cls.rechecked_by = reviewer.id
    cls.rechecked_at = utcnow()
    if theme.code != cls.final_theme:
        cls.final_theme = theme.code
        issues.group(db, report, theme.code)
    audit.record(
        "report.rechecked",
        actor_type="user",
        actor_id=reviewer.id,
        object_type="report",
        object_id=report.id,
        agreed=theme.code == cls.theme,
    )
