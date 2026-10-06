"""One scripted end-to-end run per release: submit a voice note, see it classified, answer it,
receive the SMS. Run inside the API container on staging:

    docker compose -f infra/docker-compose.yml exec -T api jamii e2e

The CHP side goes over real HTTP. The reviewer and officer act through the same service
functions the web pages call. Everything it creates is synthetic and withdrawn at the end.
The manual gate (a real phone, a real SIM) is still done by a person; see docs/runbooks/release.md.
"""

import io
import struct
import sys
import time
import uuid
import wave

import httpx
from sqlalchemy import select

from jamii_api import sms
from jamii_api.config import get_settings
from jamii_api.db import get_sessionmaker
from jamii_api.models import (
    HUMAN_QUEUES,
    Chp,
    CommunityHealthUnit,
    Report,
    ReportStatus,
    Resolution,
    ResponseKind,
    Role,
    SmsOutbox,
    User,
)
from jamii_api.security import issue_token
from jamii_api.seed import seed_themes
from jamii_api.services import issues, review

E2E_UNIT = "E2E-0001"
E2E_CHP = "+254711000999"
E2E_OFFICER = "+254722000999"
E2E_REVIEWER = "+254722000998"


class Failed(Exception):
    pass


def _silence_wav(seconds: float = 1.0) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(struct.pack("<h", 0) * int(8000 * seconds))
    return buf.getvalue()


def _fixtures(db):
    seed_themes(db)
    unit = db.scalar(select(CommunityHealthUnit).where(CommunityHealthUnit.code == E2E_UNIT))
    if unit is None:
        unit = CommunityHealthUnit(
            code=E2E_UNIT, name="E2E test unit", ward="E2E Ward", sub_county="E2E Sub", county="E2E County"
        )
        db.add(unit)
        db.flush()
    chp = db.scalar(select(Chp).where(Chp.phone == E2E_CHP))
    if chp is None:
        chp = Chp(phone=E2E_CHP, chu_id=unit.id, language="sw", consent_version=get_settings().consent_version)
        db.add(chp)
    chp.consent_version = get_settings().consent_version
    chp.active = True
    people = {}
    for phone, name, role in ((E2E_OFFICER, "E2E Officer", Role.COUNTY), (E2E_REVIEWER, "E2E Reviewer", Role.REVIEWER)):
        u = db.scalar(select(User).where(User.phone == phone))
        if u is None:
            u = User(phone=phone, name=name, role=role, county="E2E County", can_review=role == Role.REVIEWER)
            db.add(u)
        people[role] = u
    db.commit()
    return chp, people[Role.COUNTY], people[Role.REVIEWER]


def _wait(db, report_id: int, until, timeout: float) -> Report:
    deadline = time.monotonic() + timeout
    while True:
        db.expire_all()
        report = db.get(Report, report_id)
        if until(report):
            return report
        if time.monotonic() > deadline:
            raise Failed(f"timed out waiting on report {report_id} (status {report.status})")
        time.sleep(1)


def run(base_url: str, timeout: float = 120) -> None:
    started = time.monotonic()
    db = get_sessionmaker()()
    try:
        chp, officer, reviewer = _fixtures(db)
        headers = {"Authorization": "Bearer " + issue_token("chp", chp.id, chp.token_version, 1)}
        http = httpx.Client(base_url=base_url, headers=headers, timeout=30)

        r = http.post(
            "/api/v1/reports",
            data={"client_id": uuid.uuid4().hex, "theme_code": "stockout"},
            files={"audio": ("e2e.wav", _silence_wav(), "audio/wav")},
        )
        if r.status_code != 201:
            raise Failed(f"submit: HTTP {r.status_code} {r.text[:200]}")
        report_id = r.json()["id"]
        print(f"1. voice note submitted over HTTP as report #{report_id}")

        report = _wait(db, report_id, lambda x: x.status != ReportStatus.PROCESSING, timeout)
        queue = report.status
        if queue in HUMAN_QUEUES:
            review.save(
                db,
                report,
                reviewer,
                final_theme="stockout",
                transcript="E2E: hakuna dawa ya ORS" if report.audio_key else None,
                new_issue=True,
            )
            db.commit()
            print(f"2. report went to the {queue} queue; reviewed by the E2E reviewer")
        else:
            print(f"2. report classified by {report.classification.model_version} and grouped")
        report = _wait(db, report_id, lambda x: x.status == ReportStatus.GROUPED, 10)
        issue = report.issue

        draft = issues.draft_response(db, issue, officer, ResponseKind.ACTION_TAKEN, "E2E check, please ignore")
        resp, ids = issues.release_response(db, issue, officer, draft)
        db.commit()
        sms.dispatch(db, ids)
        print(f"3. officer answered issue #{issue.id}; {len(ids)} SMS queued")

        deadline = time.monotonic() + 60
        while True:
            db.expire_all()
            rows = db.scalars(select(SmsOutbox).where(SmsOutbox.response_id == resp.id)).all()
            if rows and all(x.status == "sent" for x in rows):
                break
            if any(x.status == "failed" for x in rows) or time.monotonic() > deadline:
                raise Failed(f"SMS not sent: {[(x.status, x.last_error) for x in rows]}")
            time.sleep(1)
        print(f"4. SMS sent to the E2E CHP ({rows[0].provider_id})")

        mine = http.get("/api/v1/reports/mine").json()
        seen = next((x for x in mine if x["id"] == report_id), None)
        if not seen or seen["status"] != "action_taken" or not seen["responses"]:
            raise Failed(f"CHP does not see the answer: {seen}")
        print("5. the CHP's app sees 'action taken' and the officer's message")

        http.post(f"/api/v1/reports/{report_id}/withdraw").raise_for_status()
        db.expire_all()
        cleanup = issues.draft_response(
            db, db.get(type(issue), issue.id), officer, ResponseKind.RESOLVED, "E2E cleanup", Resolution.NOT_ACTIONED
        )
        issues.release_response(db, db.get(type(issue), issue.id), officer, cleanup)
        db.commit()
        print(f"PASS in {time.monotonic() - started:.1f}s (test report withdrawn, issue closed)")
    finally:
        db.close()


def main(base_url: str, allow_production: bool) -> None:
    if get_settings().is_production and not allow_production:
        sys.exit("Refusing to run in production. Use staging, or pass --allow-production deliberately.")
    try:
        run(base_url)
    except Failed as e:
        sys.exit(f"FAIL: {e}")
