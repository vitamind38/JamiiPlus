"""Scoped numbers for the in-app dashboards.

Metabase reads the SQL views in dashboards/sql for county and national analysis; these
queries exist because each officer must see only their own area, which Metabase's open
source edition cannot enforce per person.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy import select
from sqlalchemy.orm import Session

from jamii_api.db.base import utcnow
from jamii_api.models import (
    Classification,
    Issue,
    IssueStatus,
    Report,
    ReportStatus,
    Resolution,
    Response,
    ResponseKind,
    User,
)
from jamii_api.services import scope


@dataclass
class Dashboard:
    since: datetime
    reports_total: int = 0
    by_theme: list[tuple[str, int]] = field(default_factory=list)
    by_week: list[tuple[str, int]] = field(default_factory=list)
    by_ward: list[tuple[str, int]] = field(default_factory=list)
    issues_by_status: dict[str, int] = field(default_factory=dict)
    median_days_to_first_response: float | None = None
    responded_reports: int = 0
    share_issues_with_action: float | None = None
    open_issues: int = 0
    review_queue: int = 0
    recheck_total: int = 0
    recheck_agreement: float | None = None
    suggestion_total: int = 0
    suggestion_agreement: float | None = None


def build(db: Session, user: User, days: int = 90) -> Dashboard:
    since = utcnow() - timedelta(days=days)
    d = Dashboard(since=since)

    reports = list(
        db.scalars(
            select(Report).where(
                scope.report_filter(user), Report.created_at >= since, Report.status != ReportStatus.WITHDRAWN
            )
        ).unique()
    )
    d.reports_total = len(reports)
    themes = Counter(
        (r.classification.final_theme if r.classification and r.classification.final_theme else "untagged")
        for r in reports
    )
    d.by_theme = themes.most_common()
    d.by_ward = Counter(r.ward for r in reports).most_common(15)
    weeks = Counter((r.created_at - timedelta(days=r.created_at.weekday())).strftime("%Y-%m-%d") for r in reports)
    d.by_week = sorted(weeks.items())[-12:]
    d.review_queue = sum(
        1
        for r in reports
        if r.status in (ReportStatus.NEEDS_REDACTION, ReportStatus.NEEDS_TRANSCRIPTION, ReportStatus.NEEDS_TAGGING)
    )

    issue_rows = list(db.scalars(select(Issue).where(scope.issue_filter(user), Issue.last_reported_at >= since)))
    d.issues_by_status = {s.value: 0 for s in IssueStatus}
    for i in issue_rows:
        d.issues_by_status[i.status] = d.issues_by_status.get(i.status, 0) + 1
    d.open_issues = sum(1 for i in issue_rows if i.status != IssueStatus.RESOLVED)
    if issue_rows:
        acted = sum(
            1
            for i in issue_rows
            if i.status == IssueStatus.ACTION_TAKEN
            or (i.status == IssueStatus.RESOLVED and i.resolution == Resolution.ACTIONED)
        )
        d.share_issues_with_action = acted / len(issue_rows)

    # Days from each report to the first response on its issue made after the report arrived.
    issue_ids = {r.issue_id for r in reports if r.issue_id}
    responses: dict[int, list[datetime]] = {}
    if issue_ids:
        for issue_id, at in db.execute(
            select(Response.issue_id, Response.created_at)
            .where(Response.issue_id.in_(issue_ids), Response.kind != ResponseKind.ESCALATED)
            .order_by(Response.created_at)
        ):
            responses.setdefault(issue_id, []).append(at)
    waits = []
    for r in reports:
        after = [t for t in responses.get(r.issue_id, []) if t >= r.created_at]
        if after:
            waits.append((after[0] - r.created_at).total_seconds() / 86400)
    d.responded_reports = len(waits)
    d.median_days_to_first_response = round(median(waits), 1) if waits else None

    classes = [r.classification for r in reports if r.classification is not None]
    rechecked = [c for c in classes if c.rechecked_at is not None and c.theme]
    d.recheck_total = len(rechecked)
    if rechecked:
        d.recheck_agreement = sum(c.recheck_theme == c.theme for c in rechecked) / len(rechecked)
    suggested = [c for c in classes if c.theme and c.reviewed_by is not None]
    d.suggestion_total = len(suggested)
    if suggested:
        d.suggestion_agreement = sum(c.final_theme == c.theme for c in suggested) / len(suggested)
    return d


def agreement_rate(db: Session, weeks: int = 4) -> float | None:
    """Published on every dashboard: how often reviewers agree with model-accepted themes."""
    since = utcnow() - timedelta(weeks=weeks)
    rows = list(db.scalars(select(Classification).where(Classification.rechecked_at >= since)))
    rows = [c for c in rows if c.theme]
    return sum(c.recheck_theme == c.theme for c in rows) / len(rows) if rows else None
