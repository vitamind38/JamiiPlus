"""Scheduled jobs: SMS retries, retention, stuck-report sweep, weekly re-check sample, spike flags.

Each takes a session and returns a count, so it can be tested and run by hand
(`python -m jamii_workers.jobs purge_expired`) if the scheduler is down.

They live in the API package so hosting without the workers can run them too: Celery beat
schedules them on the Kenyan server, Vercel Cron through /internal/cron/ (routers/cron.py).
"""

import logging
import math
import random
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from jamii_api import audit, sms
from jamii_api.config import get_settings
from jamii_api.db import session_scope
from jamii_api.db.base import utcnow
from jamii_api.models import (
    Classification,
    OtpChallenge,
    Report,
    ReportStatus,
    SmsOutbox,
    SpikeAlert,
    Transcript,
)
from jamii_api.services.reports import route_to_people
from jamii_api.storage import get_audio_store

log = logging.getLogger("jamii.jobs")


def send_one(db: Session, outbox_id: int) -> bool:
    row = db.scalar(select(SmsOutbox).where(SmsOutbox.id == outbox_id).with_for_update(skip_locked=True))
    if row is None or row.status != "queued":
        return False
    return sms.deliver(db, row)


def flush_outbox(db: Session, limit: int = 200) -> int:
    """Retry anything queued whose time has come, oldest first."""
    ids = db.scalars(
        select(SmsOutbox.id)
        .where(SmsOutbox.status == "queued", SmsOutbox.next_attempt_at <= utcnow())
        .order_by(SmsOutbox.id)
        .limit(limit)
    ).all()
    sent = 0
    for i in ids:
        sent += send_one(db, i)
        db.commit()
    return sent


def sweep_stuck(db: Session, minutes: int = 30) -> int:
    """Reports the workers never finished go to people instead of waiting forever."""
    cutoff = utcnow() - timedelta(minutes=minutes)
    stuck = (
        db.scalars(select(Report).where(Report.status == ReportStatus.PROCESSING, Report.created_at < cutoff))
        .unique()
        .all()
    )
    for r in stuck:
        route_to_people(r)
    return len(stuck)


def purge_expired(db: Session) -> dict[str, int]:
    """Delete raw audio and text past their retention dates, old codes, and old SMS bodies."""
    now = utcnow()
    store = get_audio_store()
    audio = 0
    for r in db.scalars(select(Report).where(Report.audio_key.isnot(None), Report.audio_expires_at <= now)).unique():
        try:
            store.delete(r.audio_key)
        except Exception:  # keep going; the next night retries this one
            log.exception("could not delete audio for report %s", r.id)
            continue
        r.audio_key = None
        audio += 1
    texts = 0
    for r in db.scalars(select(Report).where(Report.raw_text.isnot(None), Report.text_expires_at <= now)).unique():
        r.raw_text = None
        texts += 1
    expired_ids = select(Report.id).where(Report.text_expires_at <= now)
    transcripts = db.execute(
        update(Transcript)
        .where(Transcript.report_id.in_(expired_ids), Transcript.text != "")
        .values(text="", machine_text=None)
    ).rowcount
    codes = db.execute(delete(OtpChallenge).where(OtpChallenge.created_at < now - timedelta(days=1))).rowcount
    old_sms = db.execute(
        update(SmsOutbox)
        .where(SmsOutbox.created_at < now - timedelta(days=180), SmsOutbox.message != "")
        .values(message="")
    ).rowcount
    result = {
        "audio": audio,
        "texts": texts,
        "transcripts": transcripts or 0,
        "codes": codes or 0,
        "sms_bodies": old_sms or 0,
    }
    audit.record("retention.purged", actor_type="system", **result)
    return result


def sample_for_recheck(db: Session, rng: random.Random | None = None) -> int:
    """Each week a person re-checks a random sample of what the model accepted on its own."""
    rng = rng or random.Random()
    since = utcnow() - timedelta(days=7)
    candidates = db.scalars(
        select(Classification).where(
            Classification.reviewed_by.is_(None),
            Classification.final_theme.isnot(None),
            Classification.model_version.isnot(None),
            Classification.recheck_requested_at.is_(None),
            Classification.created_at >= since,
        )
    ).all()
    chosen = rng.sample(candidates, min(len(candidates), get_settings().recheck_sample_size))
    now = utcnow()
    for c in chosen:
        c.recheck_requested_at = now
    return len(chosen)


def detect_spikes(db: Session, min_count: int = 3) -> int:
    """Flag a theme in a ward whose last 7 days are well above its previous 8-week average.

    Only proposes alerts. A person confirms or discards each one.
    """
    if not get_settings().spike_alerts_enabled:
        return 0
    now = utcnow()
    week_ago = now - timedelta(days=7)
    history_start = week_ago - timedelta(weeks=8)
    rows = db.execute(
        select(Classification.final_theme, Report.ward, Report.sub_county, Report.county, Report.created_at)
        .join(Report, Report.id == Classification.report_id)
        .where(Report.status == ReportStatus.GROUPED, Report.created_at >= history_start)
    ).all()
    recent: Counter = Counter()
    before: Counter = Counter()
    place: dict = {}
    for theme, ward, sub, county, at in rows:
        key = (theme, ward, sub, county)
        place[key] = (sub, county)
        (recent if at >= week_ago else before)[key] += 1
    existing = defaultdict(bool)
    for a in db.scalars(select(SpikeAlert).where(SpikeAlert.window_end >= week_ago, SpikeAlert.status != "discarded")):
        existing[(a.theme_code, a.ward, a.sub_county, a.county)] = True
    made = 0
    for key, n in recent.items():
        baseline = before[key] / 8
        if n >= min_count and n > baseline + 3 * math.sqrt(max(baseline, 1)) and not existing[key]:
            theme, ward, sub, county = key
            db.add(
                SpikeAlert(
                    theme_code=theme,
                    ward=ward,
                    sub_county=sub,
                    county=county,
                    window_start=week_ago,
                    window_end=now,
                    count=n,
                    baseline=baseline,
                )
            )
            made += 1
    return made


JOBS = {
    "flush_outbox": flush_outbox,
    "sweep_stuck": sweep_stuck,
    "purge_expired": purge_expired,
    "sample_for_recheck": sample_for_recheck,
    "detect_spikes": detect_spikes,
}

# What /internal/cron/<schedule> runs. Vercel's Hobby plan allows one run a day, so "daily" does
# everything; "frequent" is for a plan or scheduler that can call more often. sample_for_recheck
# is left out: it samples what the model accepted on its own, and without workers nothing is.
CRON = {
    "daily": ("purge_expired", "flush_outbox", "sweep_stuck", "detect_spikes"),
    "frequent": ("flush_outbox", "sweep_stuck"),
}


def run_jobs(names: Iterable[str]) -> tuple[dict[str, object], list[str]]:
    """Run each job in its own transaction, so one failing does not hold back the others."""
    results: dict[str, object] = {}
    failed: list[str] = []
    for name in names:
        try:
            with session_scope() as db:
                results[name] = JOBS[name](db)
        except Exception:
            log.exception("job %s failed", name)
            failed.append(name)
    return results, failed
