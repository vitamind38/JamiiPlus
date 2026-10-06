"""The public demo: what it shows, and what it refuses to do."""

import pytest
from helpers import csrf_of

from jamii_api import demo
from jamii_api.config import Settings, get_settings
from jamii_api.db import get_engine
from jamii_api.models import Report
from jamii_api.sms import ConsoleBackend

KEYS = {"secret_key": "s" * 40, "pseudonym_key": "p" * 40}


@pytest.fixture
def demo_on(monkeypatch):
    monkeypatch.setattr(get_settings(), "demo_mode", True)


def test_demo_never_sends_real_sms():
    with pytest.raises(RuntimeError, match="never sends real SMS"):
        Settings(environment="staging", demo_mode=True, sms_backend="africastalking", **KEYS).check()


def test_demo_is_never_production():
    with pytest.raises(RuntimeError, match="never allowed in production"):
        Settings(environment="production", demo_mode=True, **KEYS).check()


def test_demo_settings_pass_with_console_sms():
    s = Settings(environment="staging", demo_mode=True, sms_backend="console", **KEYS)
    s.check()
    assert s.shows_codes_on_screen


def test_codes_stay_off_screen_outside_local_and_demo():
    with pytest.raises(RuntimeError, match="only allowed in local"):
        Settings(environment="staging", dev_show_otp=True, **KEYS).check()
    assert not Settings(environment="production", **KEYS).shows_codes_on_screen


def test_hosted_database_url_is_picked_up_and_given_a_driver(monkeypatch):
    monkeypatch.delenv("JAMII_DATABASE_URL", raising=False)
    monkeypatch.delenv("JAMII_AUDIT_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require")
    s = Settings()
    assert s.database_url == "postgresql+psycopg://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require"
    assert s.audit_database_url == s.database_url


def test_jamii_url_wins_over_provider_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://other/db")
    monkeypatch.setenv("JAMII_DATABASE_URL", "postgresql+psycopg://mine/db")
    assert Settings().database_url == "postgresql+psycopg://mine/db"


def test_demo_login_page_lists_accounts_and_shows_the_code(demo_on, client, make):
    page = client.get("/login").text
    assert "Demo with made-up data" in page
    assert "Demo logins" in page and "0700 000 004" in page
    officer = make.user("county", county="Nairobi")
    r = client.post("/login", data={"phone": officer.phone, "csrf": csrf_of(page), "next": "/"})
    assert "Demo: your code is" in r.text
    assert ConsoleBackend.sent  # printed, never sent


def test_no_demo_banner_normally(client):
    page = client.get("/login").text
    assert "Demo with made-up data" not in page and "Demo logins" not in page


def test_bootstrap_loads_demo_data_once(demo_on, db):
    if get_engine().dialect.name == "postgresql":
        pytest.skip("the PostgreSQL path (lock + Alembic) is tested in test_migrations.py")
    first = demo.bootstrap()
    assert first and first["reports"] > 0
    count = db.query(Report).count()
    assert demo.bootstrap() == {}
    assert db.query(Report).count() == count


def test_bootstrap_does_nothing_outside_demo(db):
    assert demo.bootstrap() is None
    assert db.query(Report).count() == 0
