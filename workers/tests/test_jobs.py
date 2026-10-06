import random
from datetime import timedelta
from pathlib import Path

from helpers import post_report

from jamii_api.config import get_settings
from jamii_api.db.base import utcnow
from jamii_api.models import Classification, Report, SmsOutbox
from jamii_api.sms import ConsoleBackend, SendResult, queue_sms
from jamii_workers import jobs


def test_flush_outbox_sends_and_backs_off(db, make, monkeypatch):
    chp = make.chp(make.unit())
    ok = queue_sms(db, phone=chp.phone, message="hello", kind="status", chp_id=chp.id)
    db.commit()
    assert jobs.flush_outbox(db) == 1
    db.refresh(ok)
    assert ok.status == "sent" and ConsoleBackend.sent[-1] == (chp.phone, "hello")

    flaky = queue_sms(db, phone=chp.phone, message="retry me", kind="status", chp_id=chp.id)
    db.commit()
    monkeypatch.setattr(ConsoleBackend, "send", lambda self, p, m: SendResult(ok=False, error="provider 503"))
    assert jobs.flush_outbox(db) == 0
    db.refresh(flaky)
    assert flaky.status == "queued" and flaky.attempts == 1 and flaky.next_attempt_at > utcnow()
    assert jobs.flush_outbox(db) == 0  # not due yet
    db.refresh(flaky)
    assert flaky.attempts == 1


def test_permanent_failure_is_not_retried(db, make, monkeypatch):
    chp = make.chp(make.unit())
    row = queue_sms(db, phone=chp.phone, message="x", kind="status")
    db.commit()
    monkeypatch.setattr(
        ConsoleBackend, "send", lambda self, p, m: SendResult(ok=False, error="AT 403", retryable=False)
    )
    jobs.flush_outbox(db)
    db.refresh(row)
    assert row.status == "failed"


def test_purge_deletes_expired_audio_and_text(client, db, make):
    chp = make.chp(make.unit())
    rid = post_report(client, chp, text="hakuna dawa", audio=b"voice" * 50).json()["id"]
    db.expire_all()
    report = db.get(Report, rid)
    key = report.audio_key
    path = Path(get_settings().storage_local_dir) / key
    assert path.exists()
    report.audio_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    result = jobs.purge_expired(db)
    db.commit()
    assert result["audio"] == 1 and not path.exists()
    db.refresh(report)
    assert report.audio_key is None and report.raw_text  # text is kept longer than audio

    report.text_expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert jobs.purge_expired(db)["texts"] == 1
    db.commit()
    db.refresh(report)
    assert report.raw_text is None


def test_sweep_routes_stuck_reports_to_people(client, db, make):
    chp = make.chp(make.unit())
    rid = post_report(client, chp, text="x").json()["id"]
    db.expire_all()
    r = db.get(Report, rid)
    r.status = "processing"
    r.created_at = utcnow() - timedelta(hours=1)
    db.commit()
    assert jobs.sweep_stuck(db) == 1
    db.commit()
    db.refresh(r)
    assert r.status == "needs_tagging"


def test_weekly_sample_only_takes_model_accepted(client, db, make, monkeypatch):
    monkeypatch.setattr(get_settings(), "recheck_sample_size", 2)
    chp = make.chp(make.unit())
    reviewer = make.user("reviewer")
    for i in range(4):
        rid = post_report(client, chp, text=f"r{i}").json()["id"]
        db.add(
            Classification(
                report_id=rid,
                theme="stockout",
                confidence=0.9,
                model_version="m1",
                final_theme="stockout",
                reviewed_by=reviewer.id if i == 0 else None,
            )
        )
    db.commit()
    assert jobs.sample_for_recheck(db, random.Random(1)) == 2
    db.commit()
    picked = db.query(Classification).filter(Classification.recheck_requested_at.isnot(None)).all()
    assert len(picked) == 2 and all(c.reviewed_by is None for c in picked)


def test_outbox_rows_are_not_resent(db, make):
    chp = make.chp(make.unit())
    row = queue_sms(db, phone=chp.phone, message="once", kind="status")
    db.commit()
    assert jobs.send_one(db, row.id) is True
    db.commit()
    assert jobs.send_one(db, row.id) is False
    assert sum(1 for p, m in ConsoleBackend.sent if m == "once") == 1
    assert db.get(SmsOutbox, row.id).attempts == 1
