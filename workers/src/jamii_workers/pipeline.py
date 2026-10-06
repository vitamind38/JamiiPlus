"""The assisted pipeline: redact -> transcribe -> classify -> group, with a person behind each gate.

A wrong model output costs a mislabelled report in a review queue, never a patient decision.
Any failure or low confidence routes the report to the matching human queue; nothing is
lost and nothing reaches a dashboard without either a confident model or a person.
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from jamii_api import audit
from jamii_api.config import get_settings
from jamii_api.models import Classification, Report, ReportStatus, Theme, Transcript
from jamii_api.redaction import redact
from jamii_api.services import issues
from jamii_api.services.reports import route_to_people
from jamii_api.storage import get_audio_store
from jamii_workers.model_client import ModelClient, ModelUnavailable

log = logging.getLogger("jamii.pipeline")


def _hold_for_redaction(report: Report, reason: str) -> str:
    report.status = ReportStatus.NEEDS_REDACTION
    report.hold_reason = reason[:200]
    return "held_for_redaction"


def process_report(db: Session, report_id: int, client: ModelClient | None = None) -> str:
    """Returns what happened, for logs and tests. The caller commits."""
    s = get_settings()
    client = client or ModelClient()
    report = db.get(Report, report_id)
    if report is None or report.status != ReportStatus.PROCESSING:
        return "skipped"
    language = report.language

    # 1. Redact: rules already ran at intake; the named-entity pass runs once its model is approved.
    if report.raw_text and s.ner_redaction_enabled:
        try:
            out = client.redact(report.raw_text, language)
            report.raw_text = redact(out.text).text
            report.redaction = "rules+ner"
        except ModelUnavailable as e:
            return _hold_for_redaction(report, f"Named-entity redaction unavailable ({e})")

    # 2. Transcribe voice notes.
    transcript_ok = True
    if report.audio_key and report.transcript is None:
        try:
            audio = get_audio_store().get(report.audio_key)
            t = client.transcribe(audio, report.audio_mime or "audio/mp4", language)
        except (ModelUnavailable, OSError) as e:
            log.info("report %s: transcription unavailable (%s), routing to people", report.id, e)
            route_to_people(report)
            return "to_transcription_queue"
        text = redact(t.text).text
        held = None
        if s.ner_redaction_enabled:
            try:
                text = redact(client.redact(text, language).text).text
            except ModelUnavailable as e:
                held = f"Transcript redaction unavailable ({e})"
        report.transcript = Transcript(
            report_id=report.id, text=text, model_version=t.model_version, confidence=t.confidence
        )
        db.add(report.transcript)
        if held:  # the reviewer sees and edits the transcript on the redaction screen
            return _hold_for_redaction(report, held)
        transcript_ok = t.confidence >= s.transcribe_min_confidence

    # 3. Classify. Even an unsure guess is stored, to pre-fill the reviewer's choice.
    text = report.readable_text
    if not text:
        route_to_people(report)
        return "to_tagging_queue"
    themes = [{"code": t.code, "keywords": t.keywords} for t in db.scalars(select(Theme).where(Theme.active.is_(True)))]
    try:
        p = client.classify(text, language, themes)
    except ModelUnavailable as e:
        log.info("report %s: classifier unavailable (%s), routing to people", report.id, e)
        route_to_people(report)
        return "to_tagging_queue"
    cls = report.classification or Classification(report_id=report.id)
    cls.theme, cls.confidence, cls.model_version = p.theme, p.confidence, p.model_version
    report.classification = cls
    db.add(cls)

    # 4. The confidence gate. The model never overrides what the CHP themselves chose.
    active = {t["code"] for t in themes}
    confident = p.confidence >= s.classify_min_confidence and p.theme in active
    agrees_with_chp = report.chp_theme_code in (None, p.theme)
    if not (transcript_ok and confident and agrees_with_chp):
        route_to_people(report)
        if not transcript_ok:
            report.status = ReportStatus.NEEDS_TRANSCRIPTION
        return "to_transcription_queue" if not transcript_ok else "to_tagging_queue"

    cls.final_theme = p.theme  # reviewed_by stays empty: accepted from the model
    issues.group(db, report, p.theme)
    audit.record(
        "report.auto_accepted",
        actor_type="system",
        object_type="report",
        object_id=report.id,
        theme=p.theme,
        confidence=round(p.confidence, 3),
        model_version=p.model_version,
    )
    return "grouped"
