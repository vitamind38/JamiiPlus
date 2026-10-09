"""The cron endpoint Vercel calls in place of Celery beat."""

from datetime import timedelta
from pathlib import Path

import pytest
from helpers import post_report
from sqlalchemy import select
from sqlalchemy.orm import Session

from jamii_api import jobs
from jamii_api.audit import AuditLog, get_audit_engine
from jamii_api.config import Settings, get_settings
from jamii_api.db import get_engine, get_sessionmaker
from jamii_api.db.base import utcnow
from jamii_api.models import Report, SmsOutbox
from jamii_api.sms import ConsoleBackend, queue_sms

SECRET = "cron-test-secret"
AUTH = {"Authorization": f"Bearer {SECRET}"}


@pytest.fixture
def cron_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "cron_secret", SECRET)


def last_audit(action: str) -> AuditLog:
    with Session(get_audit_engine()) as s:
        return s.scalars(select(AuditLog).where(AuditLog.action == action).order_by(AuditLog.id.desc())).first()


def test_vercel_cron_secret_is_picked_up(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "from-vercel")
    assert Settings().cron_secret == "from-vercel"


def test_cron_does_not_exist_without_a_secret(client):
    assert client.get("/internal/cron/daily", headers=AUTH).status_code == 404


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": SECRET}, {"Authorization": "Bearer ü".encode()}],
    ids=["none", "wrong", "no-scheme", "non-ascii"],
)
def test_cron_is_hidden_from_wrong_callers(cron_on, client, headers):
    assert client.get("/internal/cron/daily", headers=headers).status_code == 404


def test_unknown_schedule_is_not_found(cron_on, client):
    assert client.get("/internal/cron/hourly", headers=AUTH).status_code == 404


def test_daily_purges_retries_sms_and_sweeps(cron_on, client, db, make):
    chp = make.chp(make.unit())
    voice = post_report(client, chp, text="hakuna dawa", audio=b"voice" * 50).json()["id"]
    stuck = post_report(client, chp, text="x").json()["id"]
    db.expire_all()
    report = db.get(Report, voice)
    audio = Path(get_settings().storage_local_dir) / report.audio_key
    assert audio.exists()
    report.audio_expires_at = utcnow() - timedelta(minutes=1)
    r = db.get(Report, stuck)
    r.status = "processing"
    r.created_at = utcnow() - timedelta(hours=1)
    sms = queue_sms(db, phone=chp.phone, message="retry me", kind="status", chp_id=chp.id)
    db.commit()

    resp = client.get("/internal/cron/daily", headers=AUTH)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["failed"] == []
    assert body["results"]["purge_expired"]["audio"] == 1
    assert body["results"]["flush_outbox"] == 1
    assert body["results"]["sweep_stuck"] == 1
    assert body["results"]["detect_spikes"] == 0  # off unless JAMII_SPIKE_ALERTS_ENABLED

    db.expire_all()
    assert not audio.exists() and db.get(Report, voice).audio_key is None
    assert db.get(Report, stuck).status == "needs_tagging"
    assert db.get(SmsOutbox, sms.id).status == "sent"
    entry = last_audit("cron.ran")
    assert entry.actor_type == "system" and entry.details["schedule"] == "daily"
    assert entry.details["flush_outbox"] == 1 and entry.details["failed"] == []
    assert last_audit("retention.purged").details["audio"] == 1


def test_one_failing_job_does_not_stop_the_others(cron_on, client, db, make, monkeypatch):
    def broken(_db):
        raise RuntimeError("storage down")

    monkeypatch.setitem(jobs.JOBS, "purge_expired", broken)
    chp = make.chp(make.unit())
    sms = queue_sms(db, phone=chp.phone, message="still sent", kind="status", chp_id=chp.id)
    db.commit()

    resp = client.get("/internal/cron/daily", headers=AUTH)
    assert resp.status_code == 500
    assert resp.json()["failed"] == ["purge_expired"]
    assert resp.json()["results"]["flush_outbox"] == 1
    db.expire_all()
    assert db.get(SmsOutbox, sms.id).status == "sent"
    assert last_audit("cron.ran").details["failed"] == ["purge_expired"]


def test_frequent_only_retries_and_sweeps(cron_on, client):
    resp = client.get("/internal/cron/frequent", headers=AUTH)
    assert resp.status_code == 200
    assert set(resp.json()["results"]) == {"flush_outbox", "sweep_stuck"}


@pytest.mark.postgres
def test_two_runs_at_once_send_an_sms_once(db, make):
    """Vercel can deliver a cron event twice; the second run skips rows the first is sending."""
    if get_engine().dialect.name != "postgresql":
        pytest.skip("SQLite has no row locks")
    chp = make.chp(make.unit())
    row = queue_sms(db, phone=chp.phone, message="only once", kind="status", chp_id=chp.id)
    db.commit()
    with get_sessionmaker()() as first:
        first.execute(select(SmsOutbox).where(SmsOutbox.id == row.id).with_for_update())
        with get_sessionmaker()() as second:
            assert jobs.flush_outbox(second) == 0
        first.rollback()
    with get_sessionmaker()() as later:
        assert jobs.flush_outbox(later) == 1
    assert sum(1 for _, m in ConsoleBackend.sent if m == "only once") == 1
