"""Fast tests on SQLite. CI runs the same suite against PostGIS (TEST_DATABASE_URL)."""

import os
import re
import tempfile
import uuid
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="jamii-test-"))
os.environ.update(
    {
        "JAMII_ENVIRONMENT": "local",
        "JAMII_DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp / 'test.db'}"),
        "JAMII_AUDIT_DATABASE_URL": os.environ.get("TEST_AUDIT_DATABASE_URL", f"sqlite:///{_tmp / 'audit.db'}"),
        "JAMII_STORAGE_BACKEND": "local",
        "JAMII_STORAGE_LOCAL_DIR": str(_tmp / "audio"),
        "JAMII_SMS_BACKEND": "console",
        "JAMII_QUEUE_ENABLED": "false",
        "JAMII_PIPELINE_MODE": "manual",
        "JAMII_CHANNEL_CALLBACK_TOKEN": "test-token",
        "JAMII_SECRET_KEY": "test-secret-key-for-unit-tests-only",
        "JAMII_PSEUDONYM_KEY": "test-pseudonym-key-for-unit-tests",
    }
)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from jamii_api.config import get_settings  # noqa: E402
from jamii_api.db import Base, get_engine, get_sessionmaker  # noqa: E402
from jamii_api.models import Chp, CommunityHealthUnit, Role, User  # noqa: E402
from jamii_api.security import issue_token  # noqa: E402
from jamii_api.seed import seed_themes  # noqa: E402
from jamii_api.sms import ConsoleBackend  # noqa: E402

CONSENT = get_settings().consent_version


@pytest.fixture(autouse=True)
def fresh_db():
    engine = get_engine()
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with get_sessionmaker()() as s:
        seed_themes(s)
        s.commit()
    ConsoleBackend.sent.clear()
    yield


@pytest.fixture
def db():
    s = get_sessionmaker()()
    yield s
    s.close()


@pytest.fixture
def client():
    from jamii_api.main import app

    with TestClient(app) as c:
        yield c


class Factory:
    def __init__(self, db):
        self.db = db
        self.n = 0

    def unit(self, ward="Kawangware", sub_county="Dagoretti North", county="Nairobi", name=None):
        self.n += 1
        u = CommunityHealthUnit(
            code=f"CHU-{self.n:04d}",
            name=name or f"{ward} CHU {self.n}",
            ward=ward,
            sub_county=sub_county,
            county=county,
        )
        self.db.add(u)
        self.db.commit()
        return u

    def chp(self, unit, language="sw", consented=True):
        self.n += 1
        c = Chp(
            phone=f"+2547110{self.n:05d}",
            chu_id=unit.id,
            language=language,
            consent_version=CONSENT if consented else None,
        )
        self.db.add(c)
        self.db.commit()
        return c

    def user(self, role, unit=None, sub_county=None, county=None, can_review=False, name=None):
        self.n += 1
        u = User(
            phone=f"+2547220{self.n:05d}",
            name=name or f"{role} {self.n}",
            role=role,
            chu_id=unit.id if unit else None,
            sub_county=unit.sub_county if unit else sub_county,
            county=unit.county if unit else county,
            can_review=can_review or role == Role.REVIEWER,
        )
        self.db.add(u)
        self.db.commit()
        return u


@pytest.fixture
def make(db):
    return Factory(db)


def bearer(chp) -> dict:
    return {"Authorization": "Bearer " + issue_token("chp", chp.id, chp.token_version, 30)}


def last_code(phone: str) -> str:
    for to, msg in reversed(ConsoleBackend.sent):
        if to == phone:
            m = re.search(r"\b(\d{6})\b", msg)
            if m:
                return m.group(1)
    raise AssertionError("no code sent")


def csrf_of(html: str) -> str:
    m = re.search(r'name="csrf" value="([^"]+)"', html)
    assert m, "no csrf token on page"
    return m.group(1)


def web_login(client, user) -> str:
    """Log an officer in through the real OTP flow. Returns a CSRF token for later posts."""
    page = client.get("/login")
    token = csrf_of(page.text)
    r = client.post("/login", data={"phone": user.phone, "csrf": token, "next": "/"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    r = client.post("/login/verify", data={"code": last_code(user.phone), "csrf": token}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return csrf_of(client.get("/").text)


def post_report(client, chp, **fields):
    data = {"client_id": fields.pop("client_id", uuid.uuid4().hex)}
    files = None
    if "audio" in fields:
        files = {"audio": ("note.m4a", fields.pop("audio"), "audio/mp4")}
    data.update({k: v for k, v in fields.items() if v is not None})
    return client.post("/api/v1/reports", data=data, files=files, headers=bearer(chp))
