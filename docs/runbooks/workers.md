# Workers or the queue

**Nothing is lost when workers stop.** The API falls back to doing work inline (SMS) or routing to people (reports), and `sweep_stuck` moves reports waiting more than 30 minutes to the review queue.

1. `docker compose ... ps worker beat redis` and `logs --tail=200 worker`.
2. Restart: `docker compose ... restart worker beat`.
3. Run a job by hand if the scheduler is down:
   `docker compose ... exec worker python -m jamii_workers.jobs flush_outbox` (also `sweep_stuck`, `purge_expired`, `sample_for_recheck`, `detect_spikes`).
