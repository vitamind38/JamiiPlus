import re
import uuid
from pathlib import Path

from helpers import CONSENT, bearer, post_report

from jamii_api.config import PipelineMode, get_settings
from jamii_api.models import Report


def test_consent_is_required_before_reporting(client, make):
    chp = make.chp(make.unit(), consented=False)
    me = client.get("/api/v1/me", headers=bearer(chp)).json()
    assert me["consent_required"] is True
    assert post_report(client, chp, text="hakuna dawa").status_code == 403
    r = client.post("/api/v1/me/consent", json={"version": CONSENT}, headers=bearer(chp))
    assert r.json()["consent_required"] is False
    assert post_report(client, chp, text="hakuna dawa").status_code == 201


def test_old_consent_version_is_refused(client, make):
    chp = make.chp(make.unit(), consented=False)
    assert client.post("/api/v1/me/consent", json={"version": "old"}, headers=bearer(chp)).status_code == 409


def test_text_report_is_redacted_and_queued_for_a_person(client, make, db):
    chp = make.chp(make.unit(ward="Gatina"))
    r = post_report(client, chp, text="Mama Wanjiku hakupata ORS, namba 0712345678", theme_code="stockout")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "received"
    assert "Wanjiku" not in body["text"] and "0712345678" not in body["text"]
    report = db.get(Report, body["id"])
    assert report.status == "needs_tagging"
    assert report.ward == "Gatina"
    assert report.chp_theme_code == "stockout"


def test_retry_with_same_client_id_does_not_duplicate(client, make, db):
    chp = make.chp(make.unit())
    cid = uuid.uuid4().hex
    first = post_report(client, chp, client_id=cid, text="hakuna dawa")
    second = post_report(client, chp, client_id=cid, text="hakuna dawa")
    assert first.status_code == 201 and second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert db.query(Report).count() == 1


def test_voice_note_is_stored_and_needs_a_transcript(client, make, db):
    chp = make.chp(make.unit())
    r = post_report(client, chp, audio=b"\x00\x01fake-aac" * 50, theme_code="transport")
    assert r.status_code == 201
    report = db.get(Report, r.json()["id"])
    assert report.channel == "voice"
    assert report.status == "needs_transcription"
    assert report.audio_expires_at is not None
    stored = Path(get_settings().storage_local_dir) / report.audio_key
    assert stored.exists()
    # The key is a date and a random id: nothing about the CHP or place.
    assert re.fullmatch(r"\d{4}/\d{2}/[0-9a-f]{32}\.m4a", report.audio_key)


def test_rejects_empty_report_and_bad_audio(client, make):
    chp = make.chp(make.unit())
    assert post_report(client, chp).status_code == 422
    r = client.post(
        "/api/v1/reports",
        data={"client_id": uuid.uuid4().hex},
        files={"audio": ("x.exe", b"MZ", "application/x-msdownload")},
        headers=bearer(chp),
    )
    assert r.status_code == 422


def test_report_rate_limit(client, make, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_reports_per_hour", 2)
    chp = make.chp(make.unit())
    assert post_report(client, chp, text="a").status_code == 201
    assert post_report(client, chp, text="b").status_code == 201
    assert post_report(client, chp, text="c").status_code == 429


def test_withdraw_deletes_content(client, make, db):
    chp = make.chp(make.unit())
    rid = post_report(client, chp, text="hakuna dawa", audio=b"audio" * 100).json()["id"]
    key = db.get(Report, rid).audio_key
    r = client.post(f"/api/v1/reports/{rid}/withdraw", headers=bearer(chp))
    assert r.status_code == 200
    assert r.json()["status"] == "withdrawn"
    db.expire_all()
    report = db.get(Report, rid)
    assert report.raw_text is None and report.audio_key is None
    assert not (Path(get_settings().storage_local_dir) / key).exists()


def test_cannot_touch_another_chps_report(client, make):
    unit = make.unit()
    a, b = make.chp(unit), make.chp(unit)
    rid = post_report(client, a, text="hakuna dawa").json()["id"]
    assert client.post(f"/api/v1/reports/{rid}/withdraw", headers=bearer(b)).status_code == 404
    assert client.get("/api/v1/reports/mine", headers=bearer(b)).json() == []


def test_assisted_mode_falls_back_to_people_when_queue_is_down(client, make, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "pipeline_mode", PipelineMode.ASSISTED)
    chp = make.chp(make.unit())
    rid = post_report(client, chp, text="hakuna dawa").json()["id"]
    db.expire_all()
    assert db.get(Report, rid).status == "needs_tagging"


def test_themes_list(client, make):
    chp = make.chp(make.unit())
    codes = [t["code"] for t in client.get("/api/v1/themes", headers=bearer(chp)).json()]
    assert codes[0] == "stockout" and codes[-1] == "other" and len(codes) == 9
