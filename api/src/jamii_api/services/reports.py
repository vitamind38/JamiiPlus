"""Report intake from every channel, routing to the human queues, and withdrawal."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jamii_api import audit, tasks
from jamii_api.config import PipelineMode, get_settings
from jamii_api.db.base import utcnow
from jamii_api.models import Channel, Chp, Report, ReportStatus, Theme
from jamii_api.redaction import redact
from jamii_api.services import issues
from jamii_api.storage import ALLOWED_AUDIO, get_audio_store

log = logging.getLogger("jamii.reports")


class IntakeError(ValueError):
    pass


class RateLimited(IntakeError):
    pass


@dataclass
class Audio:
    data: bytes
    mime: str


def _check_rate(db: Session, chp: Chp) -> None:
    since = utcnow() - timedelta(hours=1)
    recent = db.scalar(select(func.count(Report.id)).where(Report.chp_id == chp.id, Report.created_at >= since))
    if recent >= get_settings().max_reports_per_hour:
        raise RateLimited("Too many reports in the last hour. Try again later.")


def active_theme(db: Session, code: str | None) -> Theme | None:
    if not code:
        return None
    return db.scalar(select(Theme).where(Theme.code == code, Theme.active.is_(True)))


def intake(
    db: Session,
    chp: Chp,
    *,
    channel: Channel,
    text: str | None = None,
    theme_code: str | None = None,
    language: str | None = None,
    audio: Audio | None = None,
    client_id: str | None = None,
    reported_at: datetime | None = None,
) -> tuple[Report, bool]:
    """Store one report. Returns (report, created). Caller commits, then calls after_commit()."""
    s = get_settings()
    if client_id:
        existing = db.scalar(select(Report).where(Report.chp_id == chp.id, Report.client_id == client_id))
        if existing is not None:
            return existing, False
    if not chp.active:
        raise IntakeError("This CHP account is not active.")
    _check_rate(db, chp)

    text = (text or "").strip() or None
    if text and len(text) > s.max_text_chars:
        raise IntakeError(f"Keep the description under {s.max_text_chars} characters.")
    theme = active_theme(db, theme_code)
    if not (text or audio or theme):
        raise IntakeError("A report needs a voice note, a description or a category.")

    now = utcnow()
    audio_key = None
    if audio is not None:
        mime = audio.mime.split(";")[0].strip().lower()
        if mime not in ALLOWED_AUDIO:
            raise IntakeError("Unsupported audio format.")
        if not audio.data or len(audio.data) > s.max_audio_bytes:
            raise IntakeError("Voice note is empty or too long.")
        # The key carries no CHP or place, only a random id.
        audio_key = f"{now:%Y/%m}/{uuid.uuid4().hex}.{ALLOWED_AUDIO[mime]}"
        get_audio_store().put(audio_key, audio.data, mime)
        channel = Channel.VOICE if channel == Channel.APP else channel

    clean = redact(text)
    chu = chp.chu
    report = Report(
        chp_id=chp.id,
        client_id=client_id,
        channel=channel,
        language=language or chp.language,
        chu_id=chu.id,
        ward=chu.ward,
        sub_county=chu.sub_county,
        county=chu.county,
        chp_theme_code=theme.code if theme else None,
        raw_text=clean.text or None,
        redaction="rules" if text else "none",
        audio_key=audio_key,
        audio_mime=audio.mime if audio else None,
        audio_expires_at=now + timedelta(days=s.audio_retention_days) if audio_key else None,
        text_expires_at=now + timedelta(days=s.text_retention_days),
        status=ReportStatus.PROCESSING if s.pipeline_mode == PipelineMode.ASSISTED else _manual_status(audio_key),
        reported_at=min(reported_at, now) if reported_at else now,
        created_at=now,
    )
    db.add(report)
    db.flush()
    audit.record(
        "report.created",
        actor_type="chp",
        actor_id=chp.id,
        object_type="report",
        object_id=report.id,
        channel=str(channel),
        masked=clean.masked,
    )
    return report, True


def _manual_status(audio_key: str | None) -> ReportStatus:
    return ReportStatus.NEEDS_TRANSCRIPTION if audio_key else ReportStatus.NEEDS_TAGGING


def route_to_people(report: Report) -> None:
    """The by-hand path. Used in manual mode, and whenever any automated step is unavailable."""
    if report.status in (ReportStatus.GROUPED, ReportStatus.WITHDRAWN, ReportStatus.NEEDS_REDACTION):
        return
    needs_transcript = report.audio_key and report.transcript is None
    report.status = ReportStatus.NEEDS_TRANSCRIPTION if needs_transcript else ReportStatus.NEEDS_TAGGING


def after_commit(db: Session, report: Report) -> None:
    """Hand a new report to the workers. If they cannot take it, people do the work."""
    if report.status != ReportStatus.PROCESSING:
        return
    if not tasks.enqueue("jamii.process_report", report.id):
        route_to_people(report)
        db.commit()


def chp_status(report: Report) -> str:
    """What the CHP sees: received until an issue moves, then the issue's status."""
    if report.status == ReportStatus.WITHDRAWN:
        return "withdrawn"
    if report.issue is not None:
        return report.issue.status
    return "received"


def withdraw(db: Session, report: Report, *, actor_type: str, actor_id: int) -> None:
    """The CHP asked for removal: delete the content now, keep an empty row so counts stay honest."""
    if report.status == ReportStatus.WITHDRAWN:
        return
    now = utcnow()
    if report.audio_key:
        try:
            get_audio_store().delete(report.audio_key)
            report.audio_key = None
            report.audio_expires_at = None
        except Exception:
            # Storage is down: expire the audio now so the nightly purge deletes it.
            log.exception("audio delete failed for report %s; retention job will retry", report.id)
            report.audio_expires_at = now
    if report.issue_id is not None:
        issues.detach(db, report)
    for child in (report.transcript, report.classification):
        if child is not None:
            db.delete(child)
    report.raw_text = None
    report.chp_theme_code = None
    report.status = ReportStatus.WITHDRAWN
    report.withdrawn_at = now
    audit.record(
        "report.withdrawn", actor_type=actor_type, actor_id=actor_id, object_type="report", object_id=report.id
    )
