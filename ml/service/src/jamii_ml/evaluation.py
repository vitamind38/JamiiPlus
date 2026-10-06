"""Evaluation shared by the training, promotion and threshold scripts."""

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

from sklearn.metrics import accuracy_score, f1_score


@dataclass
class Row:
    report_id: int
    text: str
    label: str
    language: str = "sw"
    model_theme: str = ""
    model_confidence: float | None = None
    human_reviewed: bool = True


def read_labelled(path: Path, human_only: bool = True) -> list[Row]:
    """Reads the CSV from `jamii export-labelled`. Only people's labels are ground truth."""
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            human = r.get("human_reviewed", "1") in ("1", "true", "True")
            if human_only and not human:
                continue
            if not (r.get("text") or "").strip():
                continue
            conf = r.get("model_confidence") or ""
            rows.append(
                Row(
                    int(r["report_id"]),
                    r["text"],
                    r["final_theme"],
                    r.get("language", "sw"),
                    r.get("model_theme", ""),
                    float(conf) if conf else None,
                    human,
                )
            )
    return rows


def frozen_test_ids(rows: list[Row], path: Path, share: float = 0.2) -> set[int]:
    """The held-out test set. Created once and never trained on; later runs only read it.

    Membership is decided by a hash of the report id, so it is stable and stratification-free
    but needs no randomness to reproduce.
    """
    if path.exists():
        return {int(line) for line in path.read_text().split() if line.strip()}
    ids = {
        r.report_id
        for r in rows
        if int(hashlib.sha256(str(r.report_id).encode()).hexdigest(), 16) % 1000 < share * 1000
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(str(i) for i in sorted(ids)) + "\n")
    return ids


def scores(y_true: list[str], y_pred: list[str]) -> dict:
    labels = sorted(set(y_true))
    per_theme = f1_score(y_true, y_pred, labels=labels, average=None, zero_division=0)
    return {
        "n": len(y_true),
        "accuracy": round(float(accuracy_score(y_true, y_pred)), 4),
        "macro_f1": round(float(f1_score(y_true, y_pred, labels=labels, average="macro", zero_division=0)), 4),
        "per_theme_f1": {lab: round(float(s), 4) for lab, s in zip(labels, per_theme, strict=True)},
        "support": {lab: y_true.count(lab) for lab in labels},
    }


def word_error_rate(reference: str, hypothesis: str) -> tuple[int, int]:
    """(edits, reference words) by word-level edit distance."""
    ref, hyp = reference.lower().split(), hypothesis.lower().split()
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1], len(ref)
