"""The human review queue pages."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from jamii_api import audit
from jamii_api.deps import DB, SessionUser, client_ip
from jamii_api.models import HUMAN_QUEUES, Report, Theme, User
from jamii_api.services import issues, review, scope
from jamii_api.web.common import check_csrf, flash, render

router = APIRouter(prefix="/review", include_in_schema=False)
CSRF = [Depends(check_csrf)]


def _reviewer(user: User) -> User:
    if not scope.can_review(user):
        raise HTTPException(403, "Only reviewers can open the review queue.")
    return user


def _themes(db) -> list[Theme]:
    return list(db.scalars(select(Theme).where(Theme.active.is_(True)).order_by(Theme.sort_order, Theme.id)))


@router.get("")
def queue(request: Request, db: DB, user: SessionUser, status: str | None = None):
    _reviewer(user)
    items = review.recheck_queue(db, user) if status == "recheck" else review.queue(db, user, status)
    return render(
        request,
        "review/queue.html",
        user=user,
        items=items,
        status=status,
        counts=review.queue_counts(db, user),
        themes={t.code: t for t in _themes(db)},
    )


@router.get("/{report_id}")
def item(request: Request, db: DB, user: SessionUser, report_id: int):
    _reviewer(user)
    report = db.get(Report, report_id)
    if report is None or not scope.in_scope_report(user, report):
        raise HTTPException(404)
    audit.record(
        "report.viewed",
        actor_type="user",
        actor_id=user.id,
        object_type="report",
        object_id=report.id,
        ip=client_ip(request),
    )
    cls = report.classification
    suggested = (cls.theme if cls and cls.theme else None) or report.chp_theme_code
    recheck = bool(cls and cls.recheck_requested_at and not cls.rechecked_at)
    open_issue = issues.find_open_issue(db, suggested, report) if suggested else None
    return render(
        request,
        "review/item.html",
        user=user,
        r=report,
        themes=_themes(db),
        suggested=suggested,
        recheck=recheck,
        open_issue=open_issue,
        in_queue=report.status in HUMAN_QUEUES,
    )


def _next_url(db, user: User, after_id: int, status: str | None) -> str:
    for r in review.queue(db, user, status, limit=5):
        if r.id != after_id:
            return f"/review/{r.id}" + (f"?from={status}" if status else "")
    return "/review" + (f"?status={status}" if status else "")


@router.post("/{report_id}", dependencies=CSRF)
def save(
    request: Request,
    db: DB,
    user: SessionUser,
    report_id: int,
    final_theme: Annotated[str, Form()] = "",
    text: Annotated[str | None, Form()] = None,
    transcript: Annotated[str | None, Form()] = None,
    grouping: Annotated[str, Form()] = "auto",
    queue_status: Annotated[str | None, Form()] = None,
):
    _reviewer(user)
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(404)
    try:
        review.save(
            db, report, user, final_theme=final_theme, text=text, transcript=transcript, new_issue=grouping == "new"
        )
    except review.ReviewError as e:
        db.rollback()
        flash(request, str(e), "error")
        return RedirectResponse(f"/review/{report_id}", 303)
    db.commit()
    flash(request, f"Report #{report.id} added to issue #{report.issue_id}.")
    return RedirectResponse(_next_url(db, user, report.id, queue_status or None), 303)


@router.post("/{report_id}/recheck", dependencies=CSRF)
def recheck(request: Request, db: DB, user: SessionUser, report_id: int, final_theme: Annotated[str, Form()] = ""):
    _reviewer(user)
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(404)
    try:
        review.save_recheck(db, report, user, final_theme)
    except review.ReviewError as e:
        db.rollback()
        flash(request, str(e), "error")
        return RedirectResponse(f"/review/{report_id}", 303)
    db.commit()
    flash(request, f"Re-check of report #{report.id} saved.")
    nxt = review.recheck_queue(db, user, limit=1)
    return RedirectResponse(f"/review/{nxt[0].id}" if nxt else "/review?status=recheck", 303)
