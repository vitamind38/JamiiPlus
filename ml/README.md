# ML

The model service (`service/`) is the only place AI runs. It classifies, transcribes and
redacts. It never decides anything about a patient, never ranks a CHP, never sends a message
and never adds a theme. Workers call it; nothing else can reach it.

Every task returns 503 when it has no approved model, and the workers treat that exactly
like the service being down: the report goes to a person.

## Build order (from the build guide)

| Step | What | Gate to the next step |
|---|---|---|
| Phases 1–2 | No ML. `JAMII_PIPELINE_MODE=manual`. People transcribe and tag every report | Enough labelled reports and county responses |
| Baseline | Keyword rules (`keyword-baseline-v1`, active by default) pre-fill reviewers' choices in assisted mode | A trained model beats it on the held-out set |
| Classifier | `scripts/train_classifier.py` → `scripts/promote.py` | Beats the baseline; reviewers agree (weekly re-check) |
| Speech-to-text | Fine-tune a Whisper-family model on Kiswahili hand transcripts; measure with `scripts/eval_wer.py`; register under `transcriber` | Word error rate acceptable to reviewers |
| Clustering and spikes | `JAMII_SPIKE_ALERTS_ENABLED=true` (statistical rise per ward, confirmed by a person) | Enough volume per ward |

## Routine

Run inside the containers on the server. Never copy reports to a laptop.

```bash
# API container: export labelled data (no CHP identifiers)
jamii export-labelled --human-only --out /tmp/labelled.csv
jamii export-themes --out /tmp/themes.json

# Model container: train (registers but does not activate), then promote if it passes
python ml/scripts/train_classifier.py --data /tmp/labelled.csv --themes /tmp/themes.json
python ml/scripts/promote.py --version tfidf-logreg-YYYYMMDD
python ml/scripts/promote.py --rollback            # back to the previous version

# Pick the auto-accept threshold from reviewers' decisions
python ml/scripts/thresholds.py --data /tmp/labelled.csv --target 0.95
```

The held-out test set (`/srv/ml/data/test_ids.txt`) is frozen the first time training runs
and never trained on. Every version keeps its scores in `registry.yaml`, macro-F1 per theme,
so rare themes are not hidden by a good average.
