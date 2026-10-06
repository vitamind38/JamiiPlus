from datetime import timedelta

import pytest
from helpers import post_report

from jamii_api.config import PipelineMode, get_settings
from jamii_api.db.base import utcnow
from jamii_api.models import Classification, Report, SpikeAlert
from jamii_workers.model_client import ModelUnavailable, Prediction, Redaction, Transcription
from jamii_workers.pipeline import process_report


class FakeModels:
    def __init__(self, theme="stockout", confidence=0.95, transcript=("Hakuna dawa ya ORS", 0.9), down=()):
        self.theme, self.confidence, self.transcript, self.down = theme, confidence, transcript, set(down)
        self.calls = []

    def _check(self, task):
        self.calls.append(task)
        if task in self.down:
            raise ModelUnavailable(task)

    def redact(self, text, language):
        self._check("redact")
        return Redaction(text.replace("Wanjiku", "[NAME]"), 1, "ner-test")

    def transcribe(self, audio, mime, language):
        self._check("transcribe")
        return Transcription(self.transcript[0], self.transcript[1], "whisper-test")

    def classify(self, text, language, themes):
        self._check("classify")
        assert any(t["code"] == "stockout" for t in themes)
        return Prediction(self.theme, self.confidence, "tfidf-test")


@pytest.fixture
def assisted(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "pipeline_mode", PipelineMode.ASSISTED)
    monkeypatch.setattr(s, "classify_min_confidence", 0.8)
    monkeypatch.setattr(s, "transcribe_min_confidence", 0.6)


def _report(client, make, db, **fields):
    chp = make.chp(make.unit())
    rid = post_report(client, chp, **fields).json()["id"]
    db.expire_all()
    report = db.get(Report, rid)
    report.status = "processing"  # as if the queue had accepted it
    db.commit()
    return rid


def test_confident_model_groups_report(assisted, client, make, db):
    rid = _report(client, make, db, text="hakuna ORS")
    assert process_report(db, rid, FakeModels()) == "grouped"
    db.commit()
    report = db.get(Report, rid)
    assert report.status == "grouped" and report.issue_id
    c = report.classification
    assert c.final_theme == "stockout" and c.reviewed_by is None and c.model_version == "tfidf-test"


def test_low_confidence_goes_to_a_person_with_suggestion(assisted, client, make, db):
    rid = _report(client, make, db, text="hakuna ORS")
    assert process_report(db, rid, FakeModels(confidence=0.5)) == "to_tagging_queue"
    db.commit()
    report = db.get(Report, rid)
    assert report.status == "needs_tagging" and report.issue_id is None
    assert report.classification.theme == "stockout" and report.classification.final_theme is None


def test_model_never_overrides_the_chps_own_category(assisted, client, make, db):
    rid = _report(client, make, db, text="hakuna ORS", theme_code="transport")
    assert process_report(db, rid, FakeModels(confidence=0.99)) == "to_tagging_queue"


def test_default_thresholds_never_auto_accept(client, make, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "pipeline_mode", PipelineMode.ASSISTED)
    rid = _report(client, make, db, text="hakuna ORS")
    assert process_report(db, rid, FakeModels(confidence=0.999)) == "to_tagging_queue"


@pytest.mark.parametrize("down", ["classify", "transcribe"])
def test_model_service_down_routes_to_people(assisted, client, make, db, down):
    rid = _report(client, make, db, audio=b"voice" * 100)
    outcome = process_report(db, rid, FakeModels(down={down}))
    db.commit()
    expected = "needs_transcription" if down == "transcribe" else "needs_tagging"
    assert db.get(Report, rid).status == expected
    assert outcome.startswith("to_")


def test_voice_note_transcribed_and_redacted(assisted, client, make, db):
    rid = _report(client, make, db, audio=b"voice" * 100)
    models = FakeModels(transcript=("Mama Wanjiku hana pesa, simu 0712345678", 0.9), theme="cost")
    assert process_report(db, rid, models) == "grouped"
    db.commit()
    t = db.get(Report, rid).transcript
    assert "Wanjiku" not in t.text and "0712345678" not in t.text
    assert t.model_version == "whisper-test" and t.confidence == 0.9


def test_low_confidence_transcript_needs_a_person(assisted, client, make, db):
    rid = _report(client, make, db, audio=b"voice" * 100)
    assert process_report(db, rid, FakeModels(transcript=("maneno", 0.3))) == "to_transcription_queue"
    db.commit()
    report = db.get(Report, rid)
    assert report.status == "needs_transcription"
    assert report.classification.theme == "stockout"  # the suggestion is still there for the reviewer


def test_ner_failure_holds_report_for_redaction(assisted, client, make, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "ner_redaction_enabled", True)
    rid = _report(client, make, db, text="hakuna ORS")
    assert process_report(db, rid, FakeModels(down={"redact"})) == "held_for_redaction"
    db.commit()
    report = db.get(Report, rid)
    assert report.status == "needs_redaction" and "unavailable" in report.hold_reason


def test_ner_pass_runs_when_enabled(assisted, client, make, db, monkeypatch):
    monkeypatch.setattr(get_settings(), "ner_redaction_enabled", True)
    rid = _report(client, make, db, text="wanjiku hakupata ORS")
    models = FakeModels()
    process_report(db, rid, models)
    db.commit()
    assert db.get(Report, rid).redaction == "rules+ner"
    assert models.calls[0] == "redact"


def test_only_processing_reports_are_touched(assisted, client, make, db):
    chp = make.chp(make.unit())
    rid = post_report(client, chp, text="x").json()["id"]  # manual status: needs_tagging
    assert process_report(db, rid, FakeModels()) == "skipped"


def test_spike_detection_proposes_alert(client, make, db, monkeypatch):
    from jamii_workers.jobs import detect_spikes

    monkeypatch.setattr(get_settings(), "spike_alerts_enabled", True)
    unit = make.unit()
    chp = make.chp(unit)
    from jamii_api.services import issues

    for days in [1, 1, 2, 3, 4, 40]:
        rid = post_report(client, chp, text="hakuna dawa").json()["id"]
        db.expire_all()
        r = db.get(Report, rid)
        r.created_at = utcnow() - timedelta(days=days)
        db.add(Classification(report_id=r.id, final_theme="stockout"))
        issues.group(db, r, "stockout")
        db.commit()
    assert detect_spikes(db) == 1
    db.commit()
    alert = db.query(SpikeAlert).one()
    assert alert.count == 5 and alert.status == "proposed"
    assert detect_spikes(db) == 0  # no duplicate for the same window
