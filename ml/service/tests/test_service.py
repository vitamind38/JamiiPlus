import csv
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from jamii_ml import app as service
from jamii_ml import registry
from jamii_ml.classifiers import KeywordClassifier
from jamii_ml.evaluation import word_error_rate

ML_DIR = Path(__file__).resolve().parents[2]
SCRIPTS = ML_DIR / "scripts"
THEMES = [
    {"code": "stockout", "keywords": ["dawa", "ors", "imeisha", "kit"]},
    {"code": "transport", "keywords": ["mbali", "boda", "nauli", "usafiri"]},
    {"code": "cost", "keywords": ["pesa", "ksh", "gharama", "lipa"]},
    {"code": "other", "keywords": []},
]


@pytest.fixture
def reg(tmp_path, monkeypatch):
    path = tmp_path / "registry.yaml"
    path.write_text((ML_DIR / "registry.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setenv("JAMII_ML_REGISTRY", str(path))
    for f in (service.classifier, service.transcriber, service.ner):
        f.cache_clear()
    yield path
    for f in (service.classifier, service.transcriber, service.ner):
        f.cache_clear()


def test_keyword_classifier():
    k = KeywordClassifier()
    p = k.predict("Hakuna dawa ya ORS, imeisha", "sw", THEMES)
    assert p.theme == "stockout" and p.confidence > 0.6
    weak = k.predict("boda ni ghali na hakuna dawa", "sw", THEMES)
    assert weak.confidence < p.confidence
    none = k.predict("habari za asubuhi", "sw", THEMES)
    assert none.theme == "other" and none.confidence == 0.0


def test_keywords_match_word_starts_only():
    # "kit" must not fire inside "kitanda"; "ors" must not fire inside "doctors".
    p = KeywordClassifier().predict("kitanda cha doctors", "en", THEMES)
    assert p.confidence == 0.0


def test_api_classify_and_missing_models(reg):
    c = TestClient(service.app)
    assert c.get("/health").json() == {"ok": True}
    assert c.get("/v1/models").json() == {"classifier": "keyword-baseline-v1", "transcriber": None, "ner": None}
    r = c.post("/v1/classify", json={"text": "nauli ya boda ni ghali", "language": "sw", "themes": THEMES})
    assert r.status_code == 200 and r.json()["theme"] == "transport"
    assert r.json()["model_version"] == "keyword-baseline-v1"
    assert c.post("/v1/transcribe", files={"audio": ("a", b"x", "audio/mp4")}).status_code == 503
    assert c.post("/v1/redact", json={"text": "x"}).status_code == 503


def test_registry_rejects_unknown_active(reg):
    data = yaml.safe_load(reg.read_text())
    data["classifier"]["active"] = "missing-version"
    reg.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError):
        registry.active_spec("classifier", reg)


def test_wer():
    assert word_error_rate("hakuna dawa kituoni", "hakuna dawa kituoni") == (0, 3)
    assert word_error_rate("hakuna dawa kituoni", "hakuna kituoni") == (1, 3)


def _synthetic(path: Path, n: int = 400) -> None:
    rng = random.Random(3)
    phrases = {
        "stockout": ["hakuna dawa ya ors", "kit imeisha", "dawa zimeisha kituoni", "hakuna zinc"],
        "transport": ["kituo ni mbali", "nauli ya boda ghali", "hakuna usafiri", "barabara mbaya"],
        "cost": ["walilipa pesa nyingi", "gharama ya kadi", "ksh 500 kwa huduma", "hawana pesa"],
    }
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "report_id",
                "language",
                "channel",
                "text",
                "final_theme",
                "model_theme",
                "model_confidence",
                "model_version",
                "human_reviewed",
                "created_at",
            ]
        )
        for i in range(n):
            theme = rng.choice(list(phrases))
            text = " ".join(rng.sample(phrases[theme], 2)) + f" wiki {rng.randint(1, 9)}"
            conf = rng.random()
            guess = theme if conf > 0.4 else rng.choice(list(phrases))
            w.writerow([i + 1, "sw", "app", text, theme, guess, round(conf, 3), "m0", 1, "2026-10-01"])


def _run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True)


def test_train_promote_serve_and_rollback(reg, tmp_path):
    data = tmp_path / "labelled.csv"
    themes = tmp_path / "themes.json"
    _synthetic(data)
    themes.write_text(json.dumps(THEMES))
    test_ids = tmp_path / "test_ids.txt"
    r = _run(
        "train_classifier.py",
        "--data",
        str(data),
        "--themes",
        str(themes),
        "--test-ids",
        str(test_ids),
        "--models-dir",
        str(tmp_path / "models"),
        "--registry",
        str(reg),
        "--version",
        "tfidf-test",
    )
    assert r.returncode == 0, r.stderr
    assert "Registered, not active" in r.stdout
    frozen = test_ids.read_text()
    entry = registry.load(reg)["classifier"]["versions"]["tfidf-test"]
    assert entry["metrics"]["macro_f1"] > 0.8 and "baseline_macro_f1" in entry["metrics"]
    assert registry.load(reg)["classifier"]["active"] == "keyword-baseline-v1"

    # Retraining reuses the same held-out set.
    _run(
        "train_classifier.py",
        "--data",
        str(data),
        "--themes",
        str(themes),
        "--test-ids",
        str(test_ids),
        "--models-dir",
        str(tmp_path / "models"),
        "--registry",
        str(reg),
        "--version",
        "tfidf-test-2",
    )
    assert test_ids.read_text() == frozen

    r = _run("promote.py", "--version", "tfidf-test", "--registry", str(reg), "--margin", "2")
    assert r.returncode == 1 and "Not promoted" in r.stdout
    r = _run("promote.py", "--version", "tfidf-test", "--registry", str(reg), "--margin", "-1")
    assert r.returncode == 0, r.stdout + r.stderr
    assert registry.load(reg)["classifier"]["active"] == "tfidf-test"

    service.classifier.cache_clear()
    c = TestClient(service.app)
    out = c.post("/v1/classify", json={"text": "hakuna dawa ya ors kituoni", "themes": THEMES}).json()
    assert out["theme"] == "stockout" and out["model_version"] == "tfidf-test"
    # A theme retired since training is never returned with confidence.
    out = c.post("/v1/classify", json={"text": "hakuna dawa ya ors", "themes": THEMES[1:]}).json()
    assert out["theme"] != "stockout"

    r = _run("promote.py", "--rollback", "--registry", str(reg))
    assert r.returncode == 0
    assert registry.load(reg)["classifier"]["active"] == "keyword-baseline-v1"


def test_thresholds_script(tmp_path):
    data = tmp_path / "labelled.csv"
    _synthetic(data)
    r = _run("thresholds.py", "--data", str(data), "--target", "0.97")
    assert r.returncode == 0, r.stderr
    # Guesses above 0.4 are always right in the synthetic data, so the answer sits just below it.
    m = re.search(r"JAMII_CLASSIFY_MIN_CONFIDENCE=([0-9.]+)", r.stdout)
    assert m and 0.3 <= float(m.group(1)) <= 0.41, r.stdout
    r = _run("thresholds.py", "--data", str(data), "--target", "1.01")
    assert "Keep every report in the review queue" in r.stdout


def test_training_refuses_too_little_data(tmp_path, reg):
    data = tmp_path / "labelled.csv"
    _synthetic(data, n=20)
    themes = tmp_path / "themes.json"
    themes.write_text(json.dumps(THEMES))
    r = _run(
        "train_classifier.py",
        "--data",
        str(data),
        "--themes",
        str(themes),
        "--test-ids",
        str(tmp_path / "ids.txt"),
        "--registry",
        str(reg),
        "--models-dir",
        str(tmp_path / "m"),
    )
    assert r.returncode != 0 and "Not enough labelled reports" in r.stderr
