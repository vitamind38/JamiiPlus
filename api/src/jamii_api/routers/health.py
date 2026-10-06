"""Liveness, readiness and Prometheus metrics (queue depth, failed SMS, model agreement)."""

import time

from fastapi import APIRouter, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Counter, Histogram, generate_latest
from prometheus_client.core import GaugeMetricFamily
from sqlalchemy import func, select, text

from jamii_api.db import get_sessionmaker
from jamii_api.models import HUMAN_QUEUES, Report, ReportStatus, SmsOutbox
from jamii_api.services.stats import agreement_rate

router = APIRouter(tags=["health"])

REQUESTS = Counter("jamii_http_requests_total", "HTTP requests", ["method", "route", "status"])
LATENCY = Histogram("jamii_http_request_seconds", "HTTP request latency", ["route"])


async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    REQUESTS.labels(request.method, path, str(response.status_code)).inc()
    LATENCY.labels(path).observe(time.perf_counter() - start)
    return response


class QueueCollector:
    """Read at scrape time, so the numbers are the database's, not a worker's memory."""

    def collect(self):
        queue = GaugeMetricFamily("jamii_review_queue", "Reports waiting for a person", labels=["queue"])
        sms = GaugeMetricFamily("jamii_sms_outbox", "Outbound SMS by state", labels=["status"])
        stuck = GaugeMetricFamily("jamii_reports_processing", "Reports waiting for workers")
        agree = GaugeMetricFamily("jamii_model_agreement", "Reviewer agreement with model-accepted themes, 4 weeks")
        try:
            with get_sessionmaker()() as db:
                counts = dict(
                    db.execute(
                        select(Report.status, func.count())
                        .where(Report.status.in_([*HUMAN_QUEUES, ReportStatus.PROCESSING]))
                        .group_by(Report.status)
                    ).all()
                )
                for s in HUMAN_QUEUES:
                    queue.add_metric([s.value], counts.get(s.value, 0))
                stuck.add_metric([], counts.get(ReportStatus.PROCESSING.value, 0))
                for status, n in db.execute(select(SmsOutbox.status, func.count()).group_by(SmsOutbox.status)):
                    sms.add_metric([status], n)
                rate = agreement_rate(db)
                if rate is not None:
                    agree.add_metric([], rate)
        except Exception:
            return
        yield from (queue, sms, stuck, agree)


REGISTRY.register(QueueCollector())


@router.get("/healthz")
def healthz():
    return {"ok": True}


@router.get("/readyz")
def readyz(response: Response):
    try:
        with get_sessionmaker()() as db:
            db.execute(text("select 1"))
    except Exception:
        response.status_code = 503
        return {"ok": False, "database": False}
    return {"ok": True, "database": True}


@router.get("/metrics")
def metrics():
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
