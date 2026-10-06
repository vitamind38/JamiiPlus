"""Officer login, the dashboard, spike alerts and audio playback."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select

from jamii_api import audit
from jamii_api.config import get_settings
from jamii_api.db.base import utcnow
from jamii_api.deps import DB, SessionUser, client_ip
from jamii_api.models import Report, SpikeAlert, Theme
from jamii_api.security import InvalidPhone, mask_phone
from jamii_api.services import auth, scope, stats
from jamii_api.storage import get_audio_store
from jamii_api.web.common import check_csrf, flash, render

router = APIRouter(include_in_schema=False)
CSRF = [Depends(check_csrf)]


def _safe_next(url: str | None) -> str:
    return url if url and url.startswith("/") and not url.startswith("//") else "/"


@router.get("/login")
def login_form(request: Request, next: str | None = None):
    return render(request, "login.html", next=_safe_next(next))


@router.post("/login", dependencies=CSRF)
def login_send(request: Request, db: DB, phone: Annotated[str, Form()], next: Annotated[str, Form()] = "/"):
    try:
        sent = auth.request_code(db, phone, "officer", client_ip(request))
    except (InvalidPhone, auth.TooManyAttempts) as e:
        return render(request, "login.html", 400, error=str(e), phone=phone, next=_safe_next(next))
    request.session["pending_phone"] = sent.phone
    request.session["next"] = _safe_next(next)
    if sent.dev_code:
        where = "Demo" if get_settings().demo_mode else "Local development"
        flash(request, f"{where}: your code is {sent.dev_code}. In the real system it arrives by SMS.", "dev")
    return RedirectResponse("/login/verify", 303)


@router.get("/login/verify")
def verify_form(request: Request):
    phone = request.session.get("pending_phone")
    if not phone:
        return RedirectResponse("/login", 303)
    return render(request, "verify.html", masked=mask_phone(phone))


@router.post("/login/verify", dependencies=CSRF)
def verify(request: Request, db: DB, code: Annotated[str, Form()]):
    phone = request.session.get("pending_phone")
    if not phone:
        return RedirectResponse("/login", 303)
    try:
        user = auth.verify_code(db, phone, code, "officer", client_ip(request))
    except auth.AuthError as e:
        return render(request, "verify.html", 400, error=str(e), masked=mask_phone(phone))
    nxt = request.session.get("next", "/")
    request.session.clear()  # new session id contents after login
    request.session["user"] = {"id": user.id, "ver": user.token_version}
    return RedirectResponse(nxt, 303)


@router.post("/logout", dependencies=CSRF)
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


@router.get("/")
def dashboard(request: Request, db: DB, user: SessionUser, days: int = 90):
    days = days if days in (30, 90, 365) else 90
    labels = {t.code: t.label_en for t in db.scalars(select(Theme))}
    labels["untagged"] = "Not yet tagged"
    return render(
        request,
        "dashboard.html",
        user=user,
        d=stats.build(db, user, days),
        days=days,
        theme_label=lambda code: labels.get(code, code),
        mode=get_settings().pipeline_mode,
    )


@router.get("/alerts")
def alerts(request: Request, db: DB, user: SessionUser):
    rows = db.scalars(
        select(SpikeAlert).where(scope.alert_filter(user)).order_by(SpikeAlert.created_at.desc()).limit(100)
    ).all()
    return render(request, "alerts.html", user=user, alerts=rows, enabled=get_settings().spike_alerts_enabled)


@router.post("/alerts/{alert_id}", dependencies=CSRF)
def decide_alert(request: Request, db: DB, user: SessionUser, alert_id: int, decision: Annotated[str, Form()]):
    alert = db.get(SpikeAlert, alert_id)
    if alert is None or alert.status != "proposed" or user.role not in scope.OFFICER_ROLES:
        raise HTTPException(404)
    if not db.scalar(select(SpikeAlert.id).where(SpikeAlert.id == alert_id, scope.alert_filter(user))):
        raise HTTPException(404)
    alert.status = "confirmed" if decision == "confirm" else "discarded"
    alert.reviewed_by = user.id
    alert.reviewed_at = utcnow()
    db.commit()
    audit.record(
        "alert." + alert.status, actor_type="user", actor_id=user.id, object_type="spike_alert", object_id=alert.id
    )
    flash(request, f"Alert {alert.status}.")
    return RedirectResponse("/alerts", 303)


@router.get("/audio/{report_id}")
def audio(request: Request, db: DB, user: SessionUser, report_id: int):
    """Raw voice notes are heard only by reviewers, and every play is logged."""
    report = db.get(Report, report_id)
    if report is None or not report.audio_key or not scope.can_review(user) or not scope.in_scope_report(user, report):
        raise HTTPException(404)
    audit.record(
        "audio.played",
        actor_type="user",
        actor_id=user.id,
        object_type="report",
        object_id=report.id,
        ip=client_ip(request),
    )
    data = get_audio_store().get(report.audio_key)
    return Response(
        data,
        media_type=report.audio_mime or "audio/mp4",
        headers={"Cache-Control": "no-store", "Content-Disposition": "inline"},
    )
