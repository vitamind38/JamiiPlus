"""Africa's Talking callbacks: SMS and USSD for CHPs on basic phones, and delivery reports.

Africa's Talking does not sign callbacks, so each callback URL carries a shared token and
Caddy only forwards /channels/ from Africa's Talking's published addresses.
"""

import hmac
import re
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from jamii_api import messages, sms
from jamii_api.config import get_settings
from jamii_api.db.base import utcnow
from jamii_api.deps import DB
from jamii_api.models import Channel, Chp, Report, ReportStatus, SmsOutbox, Theme
from jamii_api.security import InvalidPhone, normalize_phone
from jamii_api.services import reports
from jamii_api.services.reports import IntakeError, RateLimited

USSD_MAX = 182  # characters a USSD screen can show


def _check_token(token: Annotated[str, Query()] = "") -> None:
    if not hmac.compare_digest(token, get_settings().channel_callback_token):
        raise HTTPException(403, "bad token")


router = APIRouter(prefix="/channels/africastalking", tags=["channels"], dependencies=[Depends(_check_token)])


def _chp_by_phone(db: Session, raw: str) -> Chp | None:
    try:
        phone = normalize_phone(raw)
    except InvalidPhone:
        return None
    return db.scalar(select(Chp).where(Chp.phone == phone, Chp.active.is_(True)))


def _themes(db: Session) -> list[Theme]:
    return list(db.scalars(select(Theme).where(Theme.active.is_(True)).order_by(Theme.sort_order, Theme.id)))


def _recent_status_lines(db: Session, chp: Chp, language: str, n: int = 3) -> list[str]:
    rows = db.scalars(
        select(Report).where(Report.chp_id == chp.id).order_by(Report.created_at.desc()).limit(n)
    ).unique()
    return [f"#{r.id} {messages.status_name(reports.chp_status(r), language)}" for r in rows]


# --- SMS -------------------------------------------------------------------------------

_KEYWORD = re.compile(r"^\s*(jamii|pulse|jp)\b[\s:,-]*", re.I)
_STATUS = re.compile(r"^\s*(hali|status)\s*$", re.I)
_REMOVE = re.compile(r"^\s*(futa|ondoa|remove|delete)\s+#?(\d+)\s*$", re.I)
_THEME_NUM = re.compile(r"^\s*(\d)\b[\s.:)-]*")


def _reply(db: Session, phone: str, text: str, chp: Chp | None = None) -> None:
    row = sms.queue_sms(db, phone=phone, message=text, kind="ack", chp_id=chp.id if chp else None)
    db.commit()
    sms.dispatch(db, [row.id])


@router.post("/sms/inbound")
def sms_inbound(
    db: DB,
    from_: Annotated[str, Form(alias="from")],
    text: Annotated[str, Form()] = "",
):
    chp = _chp_by_phone(db, from_)
    if chp is None:
        _reply_unregistered_once_a_day(db, from_)
        return {"ok": True}
    language = chp.language
    body = _KEYWORD.sub("", text or "", count=1)

    if _STATUS.match(body):
        lines = _recent_status_lines(db, chp, language) or [messages.ussd("no_reports", language)[4:]]
        _reply(db, chp.phone, "Jamii Pulse: " + "; ".join(lines), chp)
        return {"ok": True}

    if m := _REMOVE.match(body):
        report = db.get(Report, int(m.group(2)))
        if report is not None and report.chp_id == chp.id and report.status != ReportStatus.WITHDRAWN:
            reports.withdraw(db, report, actor_type="chp", actor_id=chp.id)
            db.commit()
            _reply(db, chp.phone, messages.sms("withdrawn", language, report_id=report.id), chp)
        return {"ok": True}

    theme_code = None
    if m := _THEME_NUM.match(body):
        themes = _themes(db)
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(themes):
            theme_code = themes[idx].code
            body = body[m.end() :]
    if not body.strip() and theme_code is None:
        _reply(db, chp.phone, messages.sms("empty", language), chp)
        return {"ok": True}
    try:
        report, _ = reports.intake(db, chp, channel=Channel.SMS, text=body, theme_code=theme_code)
    except (RateLimited, IntakeError):
        db.rollback()
        return {"ok": False}
    db.commit()
    reports.after_commit(db, report)
    _reply(db, chp.phone, messages.sms("ack", language, report_id=report.id), chp)
    return {"ok": True}


def _reply_unregistered_once_a_day(db: Session, raw: str) -> None:
    try:
        phone = normalize_phone(raw)
    except InvalidPhone:
        return
    since = utcnow() - timedelta(days=1)
    if db.scalar(select(SmsOutbox.id).where(SmsOutbox.phone == phone, SmsOutbox.created_at >= since).limit(1)):
        return
    _reply(db, phone, messages.sms("not_registered", "sw"))


@router.post("/sms/delivery")
def sms_delivery(
    db: DB,
    id: Annotated[str, Form()],
    status: Annotated[str, Form()],
    failureReason: Annotated[str | None, Form()] = None,  # noqa: N803 - Africa's Talking field name
):
    row = db.scalar(select(SmsOutbox).where(SmsOutbox.provider_id == id))
    if row is not None:
        row.delivery_status = status if not failureReason else f"{status}: {failureReason}"[:40]
        db.commit()
    return {"ok": True}


# --- USSD ------------------------------------------------------------------------------


def _ussd(text: str) -> PlainTextResponse:
    return PlainTextResponse(text[:USSD_MAX])


def _theme_pages(themes: list[Theme], language: str) -> list[str]:
    """Numbered theme lists that each fit one USSD screen. Numbers are global; 0 shows more."""
    header = messages.ussd("pick_theme", language)
    more = "0. Zaidi" if language == "sw" else "0. More"
    pages: list[list[str]] = []
    current: list[str] = []
    for i, theme in enumerate(themes):
        line = f"{i + 1}. {theme.label(language)}"[:40]
        if current and len("\n".join([header, *current, line, more])) > USSD_MAX:
            pages.append(current)
            current = []
        current.append(line)
    pages.append(current)
    return ["\n".join([header, *lines, *([more] if n < len(pages) - 1 else [])]) for n, lines in enumerate(pages)]


@router.post("/ussd", response_class=PlainTextResponse)
def ussd(
    db: DB,
    sessionId: Annotated[str, Form()],  # noqa: N803
    phoneNumber: Annotated[str, Form()],  # noqa: N803
    text: Annotated[str, Form()] = "",
):
    chp = _chp_by_phone(db, phoneNumber)
    if chp is None:
        return _ussd(messages.ussd("not_registered", "sw"))
    language = messages.lang(chp.language)
    parts = text.split("*") if text else []
    if not parts:
        return _ussd(messages.ussd("menu", language))

    if parts[0] == "2":
        lines = _recent_status_lines(db, chp, language)
        if not lines:
            return _ussd(messages.ussd("no_reports", language))
        return _ussd("\n".join([messages.ussd("status_header", language), *lines]))

    if parts[0] == "3":
        chp.language = "en" if language == "sw" else "sw"
        db.commit()
        return _ussd(messages.ussd("lang_changed", language))

    if parts[0] != "1":
        return _ussd(messages.ussd("invalid", language))

    themes = _themes(db)
    pages = _theme_pages(themes, language)
    i, page = 1, 0
    while i < len(parts) and parts[i] == "0" and page < len(pages) - 1:
        page += 1
        i += 1
    if i == len(parts):
        return _ussd(pages[page])
    if not parts[i].isdigit() or not 1 <= int(parts[i]) <= len(themes):
        return _ussd(messages.ussd("invalid", language))
    theme = themes[int(parts[i]) - 1]
    rest = parts[i + 1 :]
    if not rest:
        return _ussd(messages.ussd("describe", language))
    # The description may itself contain '*'; the last part is the confirmation only if it is 1 or 2.
    if len(rest) == 1 or rest[-1] not in ("1", "2"):
        return _ussd(messages.ussd("confirm", language, theme=theme.label(language)))
    if rest[-1] == "2":
        return _ussd(messages.ussd("cancelled", language))
    description = "*".join(rest[:-1]).strip()
    description = None if description in ("", "0") else description
    try:
        report, _ = reports.intake(
            db, chp, channel=Channel.USSD, text=description, theme_code=theme.code, client_id=f"ussd:{sessionId}"[:64]
        )
    except RateLimited:
        db.rollback()
        return _ussd(messages.ussd("rate_limited", language))
    except IntakeError:
        db.rollback()
        return _ussd(messages.ussd("invalid", language))
    db.commit()
    reports.after_commit(db, report)
    return _ussd(messages.ussd("sent", language, report_id=report.id))
