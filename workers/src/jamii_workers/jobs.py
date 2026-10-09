"""Scheduled jobs: SMS retries, retention, stuck-report sweep, weekly re-check sample, spike flags.

The jobs themselves live in jamii_api.jobs, so the Vercel deployment (no workers) runs the same
code from Vercel Cron. Celery beat schedules them here; run one by hand
(`python -m jamii_workers.jobs purge_expired`) if the scheduler is down.
"""

import sys

from jamii_api.db import session_scope
from jamii_api.jobs import (
    JOBS,
    detect_spikes,
    flush_outbox,
    purge_expired,
    sample_for_recheck,
    send_one,
    sweep_stuck,
)

__all__ = ["JOBS", "detect_spikes", "flush_outbox", "purge_expired", "sample_for_recheck", "send_one", "sweep_stuck"]

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in JOBS:
        sys.exit(f"usage: python -m jamii_workers.jobs [{'|'.join(JOBS)}]")
    with session_scope() as session:
        print(JOBS[sys.argv[1]](session))
