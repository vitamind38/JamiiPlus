"""The API the Flutter app talks to. CHPs only."""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import or_, select

from jamii_api import audit
from jamii_api.config import get_settings
from jamii_api.db.base import utcnow
from jamii_api.deps import DB, CurrentChp, client_ip
from jamii_api.models import Channel, Chp, Issue, Report, Response, Theme
from jamii_api.security import InvalidPhone, issue_token, pseudonym
from jamii_api.services import auth, reports
from jamii_api.services.reports import Audio, IntakeError, RateLimited

router = APIRouter(prefix="/api/v1", tags=["mobile"])


class OtpRequestIn(BaseModel):
    phone: str


class OtpRequestOut(BaseModel):
    sent: bool = True
    channel: Literal["sms", "email"] = "sms"  # so the app can say where to look for the code
    dev_code: str | None = None


class OtpVerifyIn(BaseModel):
    phone: str
    code: str


class MeOut(BaseModel):
    pseudonym: str
    unit: str
    ward: str
    sub_county: str
    county: str
    language: str
    consent_version: str | None
    current_consent_version: str
    consent_required: bool


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in_days: int
    me: MeOut


class MePatchIn(BaseModel):
    language: Literal["sw", "en"]


class ConsentIn(BaseModel):
    version: str


class ThemeOut(BaseModel):
    code: str
    label_en: str
    label_sw: str
    description: str


class ResponseOut(BaseModel):
    kind: str
    text: str
    officer: str
    at: datetime


class ReportOut(BaseModel):
    id: int
    client_id: str | None
    channel: str
    theme_code: str | None
    status: str
    text: str | None
    has_audio: bool
    reported_at: datetime
    created_at: datetime
    issue_id: int | None
    responses: list[ResponseOut]


def me_out(chp: Chp) -> MeOut:
    current = get_settings().consent_version
    return MeOut(
        pseudonym=pseudonym(chp.id),
        unit=chp.chu.name,
        ward=chp.chu.ward,
        sub_county=chp.chu.sub_county,
        county=chp.chu.county,
        language=chp.language,
        consent_version=chp.consent_version,
        current_consent_version=current,
        consent_required=chp.consent_version != current,
    )


def report_out(db: DB, r: Report) -> ReportOut:
    responses: list[ResponseOut] = []
    if r.issue_id:
        rows = db.scalars(
            select(Response)
            .where(Response.issue_id == r.issue_id, Response.created_at >= r.created_at)
            .order_by(Response.created_at)
        )
        responses = [
            ResponseOut(kind=x.kind, text=x.action_text, officer=x.officer.name, at=x.created_at) for x in rows
        ]
    theme = r.classification.final_theme if r.classification and r.classification.final_theme else r.chp_theme_code
    return ReportOut(
        id=r.id,
        client_id=r.client_id,
        channel=r.channel,
        theme_code=theme,
        status=reports.chp_status(r),
        text=r.raw_text,
        has_audio=bool(r.audio_key),
        reported_at=r.reported_at,
        created_at=r.created_at,
        issue_id=r.issue_id,
        responses=responses,
    )


@router.post("/auth/otp/request", response_model=OtpRequestOut, status_code=status.HTTP_202_ACCEPTED)
def otp_request(body: OtpRequestIn, request: Request, db: DB):
    try:
        sent = auth.request_code(db, body.phone, "chp", client_ip(request))
    except InvalidPhone as e:
        raise HTTPException(422, str(e)) from None
    except auth.TooManyAttempts as e:
        raise HTTPException(429, str(e)) from None
    return OtpRequestOut(channel=get_settings().message_channel, dev_code=sent.dev_code)


@router.post("/auth/otp/verify", response_model=TokenOut)
def otp_verify(body: OtpVerifyIn, request: Request, db: DB):
    try:
        chp = auth.verify_code(db, body.phone, body.code, "chp", client_ip(request))
    except InvalidPhone as e:
        raise HTTPException(422, str(e)) from None
    except auth.TooManyAttempts as e:
        raise HTTPException(429, str(e)) from None
    except auth.AuthError as e:
        raise HTTPException(401, str(e)) from None
    days = get_settings().mobile_token_days
    return TokenOut(
        access_token=issue_token("chp", chp.id, chp.token_version, days), expires_in_days=days, me=me_out(chp)
    )


@router.post("/auth/logout", status_code=204)
def logout(chp: CurrentChp, db: DB):
    chp.token_version += 1  # every token this phone holds stops working
    db.commit()


@router.get("/me", response_model=MeOut)
def me(chp: CurrentChp):
    return me_out(chp)


@router.patch("/me", response_model=MeOut)
def update_me(body: MePatchIn, chp: CurrentChp, db: DB):
    chp.language = body.language
    db.commit()
    return me_out(chp)


@router.post("/me/consent", response_model=MeOut)
def consent(body: ConsentIn, chp: CurrentChp, db: DB, request: Request):
    if body.version != get_settings().consent_version:
        raise HTTPException(409, "The privacy notice has changed. Read the new one first.")
    chp.consent_version = body.version
    chp.consented_at = utcnow()
    db.commit()
    audit.record("chp.consented", actor_type="chp", actor_id=chp.id, ip=client_ip(request), version=body.version)
    return me_out(chp)


@router.get("/themes", response_model=list[ThemeOut])
def themes(db: DB, _: CurrentChp):
    rows = db.scalars(select(Theme).where(Theme.active.is_(True)).order_by(Theme.sort_order, Theme.id))
    return [ThemeOut(code=t.code, label_en=t.label_en, label_sw=t.label_sw, description=t.description) for t in rows]


@router.post("/reports", response_model=ReportOut, status_code=201)
def create_report(
    chp: CurrentChp,
    db: DB,
    client_id: Annotated[str, Form(min_length=8, max_length=64)],
    theme_code: Annotated[str | None, Form()] = None,
    text: Annotated[str | None, Form()] = None,
    language: Annotated[Literal["sw", "en"] | None, Form()] = None,
    reported_at: Annotated[datetime | None, Form()] = None,
    audio: Annotated[UploadFile | None, File()] = None,
):
    if chp.consent_version != get_settings().consent_version:
        raise HTTPException(403, "consent_required")
    clip = None
    if audio is not None and audio.filename:
        data = audio.file.read(get_settings().max_audio_bytes + 1)
        clip = Audio(data=data, mime=audio.content_type or "application/octet-stream")
    try:
        report, created = reports.intake(
            db,
            chp,
            channel=Channel.APP,
            text=text,
            theme_code=theme_code,
            language=language,
            audio=clip,
            client_id=client_id,
            reported_at=reported_at,
        )
    except RateLimited as e:
        raise HTTPException(429, str(e)) from None
    except IntakeError as e:
        raise HTTPException(422, str(e)) from None
    db.commit()
    reports.after_commit(db, report)
    out = report_out(db, report)
    # A retry of a report the server already has is not an error: the phone just marks it synced.
    return out if created else JSONResponse(out.model_dump(mode="json"), status_code=200)


@router.get("/reports/mine", response_model=list[ReportOut])
def my_reports(chp: CurrentChp, db: DB, since: datetime | None = None):
    q = select(Report).outerjoin(Issue, Report.issue_id == Issue.id).where(Report.chp_id == chp.id)
    if since is not None:
        q = q.where(or_(Report.updated_at >= since, Issue.updated_at >= since))
    rows = db.scalars(q.order_by(Report.created_at.desc()).limit(200)).unique()
    return [report_out(db, r) for r in rows]


@router.post("/reports/{report_id}/withdraw", response_model=ReportOut)
def withdraw(report_id: int, chp: CurrentChp, db: DB):
    report = db.get(Report, report_id)
    if report is None or report.chp_id != chp.id:
        raise HTTPException(404, "Report not found")
    reports.withdraw(db, report, actor_type="chp", actor_id=chp.id)
    db.commit()
    return report_out(db, report)
