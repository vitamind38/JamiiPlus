"""The public demo: what it shows, and what it refuses to do."""

import pytest
from helpers import csrf_of

from jamii_api import bootstrap
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
    first = bootstrap.bootstrap()
    assert first and first["reports"] > 0
    count = db.query(Report).count()
    assert "reports" not in bootstrap.bootstrap()
    assert db.query(Report).count() == count


def test_bootstrap_does_nothing_unless_asked(db):
    assert bootstrap.bootstrap() is None
    assert db.query(Report).count() == 0


def test_demo_replies_are_never_in_the_future(db):
    from jamii_api.db.base import utcnow
    from jamii_api.models import Response
    from jamii_api.seed import demo_data

    demo_data(db)
    db.commit()
    assert db.query(Response).count() > 0
    assert all(r.created_at <= utcnow() for r in db.query(Response))


def test_supabase_urls_are_picked_up_and_cleaned(monkeypatch):
    for name in ("JAMII_DATABASE_URL", "JAMII_AUDIT_DATABASE_URL", "JAMII_MIGRATION_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    host = "aws-0-eu-west-1.pooler.supabase.com"
    monkeypatch.setenv(
        "POSTGRES_URL",
        f"postgres://postgres.ref:pw@{host}:6543/postgres?sslmode=require&supa=base-pooler.x"
        "&workaround=supabase-pooler.vercel",
    )
    monkeypatch.setenv("POSTGRES_URL_NON_POOLING", f"postgres://postgres.ref:pw@{host}:5432/postgres?sslmode=require")
    monkeypatch.setenv("DATABASE_URL", "postgresql://neon/db")  # a leftover provider loses to Supabase's
    s = Settings()
    assert s.database_url == f"postgresql+psycopg://postgres.ref:pw@{host}:6543/postgres?sslmode=require"
    assert s.audit_database_url == s.database_url
    assert s.migration_database_url == f"postgresql+psycopg://postgres.ref:pw@{host}:5432/postgres?sslmode=require"


def test_production_needs_a_real_sms_account():
    with pytest.raises(RuntimeError, match="JAMII_SMS_BACKEND=africastalking"):
        Settings(environment="production", sms_backend="console", **KEYS).check()
    with pytest.raises(RuntimeError, match="JAMII_AT_API_KEY"):
        Settings(environment="staging", sms_backend="africastalking", at_api_key="", **KEYS).check()
    Settings(environment="production", sms_backend="africastalking", at_api_key="k", **KEYS).check()
    Settings(environment="staging", sms_backend="console", **KEYS).check()  # staging may log instead


def test_logged_sms_hide_most_of_the_phone_number(caplog):
    caplog.set_level("INFO", logger="jamii.sms")
    ConsoleBackend().send("+254700000091", "Your code is 123456")
    assert "+254700***91" in caplog.text and "+254700000091" not in caplog.text


def test_metrics_need_the_token_when_one_is_set(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "metrics_token", "t0ken")
    assert client.get("/metrics").status_code == 404
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 404
    assert client.get("/metrics", headers={"Authorization": "Bearer t0ken"}).status_code == 200


def test_real_deployment_start_up_loads_themes_and_first_admin_only(db, monkeypatch):
    from jamii_api.models import Role, Theme, User

    s = get_settings()
    monkeypatch.setattr(s, "auto_migrate", True)
    monkeypatch.setattr(s, "bootstrap_admin_phone", "0700 000 091")
    monkeypatch.setattr(s, "bootstrap_admin_name", "Daudi")
    if get_engine().dialect.name == "postgresql":
        pytest.skip("the PostgreSQL path (lock + Alembic) is tested in test_migrations.py")
    db.query(Theme).delete()
    db.commit()
    first = bootstrap.bootstrap()
    assert first == {"themes_added": 9, "admin_created": 1}
    admin = db.query(User).one()
    assert admin.role == Role.ADMIN and admin.phone == "+254700000091" and admin.name == "Daudi"
    assert db.query(Report).count() == 0  # no demo data
    # Later cold starts change nothing, even if the setting stays or names another phone.
    monkeypatch.setattr(s, "bootstrap_admin_phone", "0700 000 092")
    assert bootstrap.bootstrap() == {"themes_added": 0, "admin_created": 0}
    assert db.query(User).count() == 1
