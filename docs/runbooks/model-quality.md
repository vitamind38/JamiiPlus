# Model agreement low

Reviewers disagree with themes the model accepted on its own more than 15% of the time.

1. Stop auto-accepting now: set `JAMII_CLASSIFY_MIN_CONFIDENCE=1.01` and restart `api worker`. Every report goes back to people; nothing else breaks.
2. Look at the week's re-checks (dashboard → Model agreement; Metabase → `dashboards.model_agreement_weekly`): one theme, or all?
3. New kind of report (a new theme, a new place, a new language)? Retrain: `ml/scripts/train_classifier.py`, then `promote.py` (it refuses models that do not beat the baseline).
4. Or roll back: `python ml/scripts/promote.py --rollback` inside the model container, then restart it.
5. Recompute the threshold: `ml/scripts/thresholds.py`.
