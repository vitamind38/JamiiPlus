"""Theme classifiers: the keyword baseline and a trained scikit-learn model.

Both return a theme and a confidence. The confidence is not calibrated in advance; the
pilot sets the threshold at which reviewers agree with the model often enough.
"""

import math
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class Prediction:
    theme: str
    confidence: float
    scores: dict[str, float]


class Classifier(Protocol):
    version: str

    def predict(self, text: str, language: str, themes: list[dict]) -> Prediction: ...


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text)


class KeywordClassifier:
    """Counts keyword hits per theme. Cheap, fast, and easy to audit: the week-one baseline."""

    def __init__(self, version: str = "keyword-baseline-v1"):
        self.version = version

    def predict(self, text: str, language: str, themes: list[dict]) -> Prediction:
        body = " " + normalise(text) + " "
        scores: dict[str, float] = {}
        for t in themes:
            hits = 0
            for kw in t.get("keywords") or []:
                kw = normalise(kw).strip()
                if not kw:
                    continue
                # Long keywords match word starts, so Swahili suffixes still count ("dawa" in "dawani").
                # Short ones must be whole words, so "kit" does not fire inside "kitanda".
                tail = r"(?![a-z0-9])" if len(kw) <= 4 else ""
                if re.search(r"(?<![a-z0-9])" + re.escape(kw) + tail, body):
                    hits += 1
            scores[t["code"]] = float(hits)
        total = sum(scores.values())
        if total == 0:
            fallback = "other" if any(t["code"] == "other" for t in themes) else themes[0]["code"]
            return Prediction(fallback, 0.0, scores)
        theme = max(scores, key=lambda k: (scores[k], k != "other"))
        top = scores[theme]
        # Share of all hits, damped when there is only one hit to go on.
        confidence = (top / total) * (1 - math.exp(-top))
        return Prediction(theme, round(confidence, 4), scores)


class SklearnClassifier:
    """A TF-IDF + logistic regression pipeline saved by ml/scripts/train_classifier.py."""

    def __init__(self, path: Path, version: str):
        import joblib

        bundle = joblib.load(path)
        self.pipeline = bundle["pipeline"]
        self.classes = list(self.pipeline.classes_)
        self.version = version

    def predict(self, text: str, language: str, themes: list[dict]) -> Prediction:
        probs = self.pipeline.predict_proba([normalise(text)])[0]
        scores = {c: float(p) for c, p in zip(self.classes, probs, strict=True)}
        active = {t["code"] for t in themes}
        allowed = {c: p for c, p in scores.items() if c in active} or scores
        theme = max(allowed, key=allowed.get)
        # A theme that has been retired since training is never offered with confidence.
        confidence = allowed[theme] if theme in active else 0.0
        return Prediction(theme, round(confidence, 4), scores)
