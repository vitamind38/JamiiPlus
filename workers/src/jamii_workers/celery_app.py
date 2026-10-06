"""Celery app, tasks and the beat schedule. Run with:

celery -A jamii_workers.celery_app worker --loglevel=info
celery -A jamii_workers.celery_app beat --loglevel=info
"""

import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_process_init

from jamii_api.config import get_settings
from jamii_api.db import session_scope
from jamii_workers import jobs
from jamii_workers.pipeline import process_report as run_pipeline

log = logging.getLogger("jamii.worker")

settings = get_settings()
app = Celery("jamii", broker=settings.redis_url)
app.conf.update(
    timezone="Africa/Nairobi",
    task_acks_late=True,  # a crashed worker's task is redelivered, not lost
    worker_prefetch_multiplier=1,
    task_reject_on_worker_lost=True,
    task_time_limit=300,
    broker_connection_retry_on_startup=True,
)
app.conf.beat_schedule = {
    "flush-outbox": {"task": "jamii.flush_outbox", "schedule": 60.0},
    "sweep-stuck": {"task": "jamii.sweep_stuck", "schedule": 600.0},
    "purge-expired": {"task": "jamii.purge_expired", "schedule": crontab(hour=2, minute=0)},
    "sample-recheck": {"task": "jamii.sample_for_recheck", "schedule": crontab(hour=6, minute=0, day_of_week=1)},
    "detect-spikes": {"task": "jamii.detect_spikes", "schedule": crontab(hour=5, minute=0)},
}


@worker_process_init.connect
def _init_sentry(**_):
    if settings.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=settings.sentry_dsn, environment=settings.environment, send_default_pii=False)


@app.task(name="jamii.process_report", bind=True, max_retries=2, default_retry_delay=30)
def process_report(self, report_id: int) -> str:
    with session_scope() as db:
        outcome = run_pipeline(db, report_id)
    log.info("report %s: %s", report_id, outcome)
    return outcome


@app.task(name="jamii.send_sms")
def send_sms(outbox_id: int) -> bool:
    with session_scope() as db:
        return jobs.send_one(db, outbox_id)


def _job(name: str):
    def run():
        with session_scope() as db:
            result = jobs.JOBS[name](db)
        log.info("%s: %s", name, result)
        return result

    run.__name__ = name
    return app.task(name=f"jamii.{name}")(run)


flush_outbox = _job("flush_outbox")
sweep_stuck = _job("sweep_stuck")
purge_expired = _job("purge_expired")
sample_for_recheck = _job("sample_for_recheck")
detect_spikes = _job("detect_spikes")
