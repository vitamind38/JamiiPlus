"""Scheduled jobs for hosting without Celery beat: Vercel Cron calls /internal/cron/daily.

On the Kenyan server beat runs the jobs, CRON_SECRET is unset and Caddy hides /internal/ anyway.
"""

import hmac

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from jamii_api import audit, jobs
from jamii_api.config import get_settings

router = APIRouter(tags=["internal"], include_in_schema=False)


@router.get("/internal/cron/{schedule}")
def run_schedule(schedule: str, request: Request):
    secret = get_settings().cron_secret
    # Compared as bytes so a header with odd characters is refused, not a 500.
    given = request.headers.get("authorization", "").encode()
    if not secret or not hmac.compare_digest(given, f"Bearer {secret}".encode()) or schedule not in jobs.CRON:
        raise HTTPException(404)
    results, failed = jobs.run_jobs(jobs.CRON[schedule])
    audit.record("cron.ran", actor_type="system", schedule=schedule, failed=failed, **results)
    # A failed job shows as a failed run in Vercel's cron log; the others still ran.
    return JSONResponse({"schedule": schedule, "results": results, "failed": failed}, 500 if failed else 200)
