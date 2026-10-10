"""Login codes and replies by email: free through a Gmail account when there is no SMS budget."""

import re
import smtplib

import pytest
from helpers import bearer, csrf_of, web_login

from jamii_api import bootstrap, sms
from jamii_api.config import Settings, get_settings
from jamii_api.db import get_engine
from jamii_api.models import Chp, Role, User

KEYS = {"secret_key": "s" * 40, "pseudonym_key": "p" * 40}


class FakeSMTP:
    """Stands in for smtplib.SMTP_SSL and records what would have been sent."""

    sent: list = []
    refuse: set = set()
    fail_login = False

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port = host, port

    def login(self, user, password):
        if FakeSMTP.fail_login:
            raise smtplib.SMTPAuthenticationError(535, b"Username and Password not accepted")

    def send_message(self, mail):
        if mail["To"] in FakeSMTP.refuse:
            raise smtplib.SMTPRecipientsRefused({mail["To"]: (550, b"No such user")})
        FakeSMTP.sent.append(mail)

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@pytest.fixture
def by_email(monkeypatch):
    FakeSMTP.sent, FakeSMTP.refuse, FakeSMTP.fail_login = [], set(), False
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    s = get_settings()
    monkeypatch.setattr(s, "sms_backend", "email")
    monkeypatch.setattr(s, "smtp_username", "jamii.tests@example.org")
    monkeypatch.setattr(s, "smtp_password", "app-password")
    sms.get_backend.cache_clear()
    yield FakeSMTP
    sms.get_backend.cache_clear()


def code_in(mail) -> str:
    return re.search(r"\b(\d{6})\b", mail.get_content()).group(1)


def test_officer_logs_in_with_a_code_sent_by_email(by_email, client, make, db):
    officer = make.user("county", county="Nairobi")
    officer.email = "officer@example.org"
    db.commit()
    page = client.get("/login").text
    assert "one-time code by email" in page
    token = csrf_of(page)
    r = client.post("/login", data={"phone": officer.phone, "csrf": token, "next": "/"})
    assert "email address on file" in r.text and "spam" in r.text
    mail = by_email.sent[-1]
    assert mail["To"] == "officer@example.org"
    assert mail["From"] == "Jamii Pulse <jamii.tests@example.org>"
    assert code_in(mail) in mail["Subject"]  # the code shows in the inbox list
    r = client.post("/login/verify", data={"code": code_in(mail), "csrf": token}, follow_redirects=False)
    assert r.status_code == 303


def test_no_email_on_file_sends_nothing_and_looks_the_same(by_email, client, make):
    officer = make.user("county", county="Nairobi")
    token = csrf_of(client.get("/login").text)
    r = client.post("/login", data={"phone": officer.phone, "csrf": token, "next": "/"}, follow_redirects=False)
    assert r.status_code == 303 and by_email.sent == []


def test_the_app_is_told_where_the_code_went(by_email, client, make, db):
    chp = make.chp(make.unit())
    chp.email = "chp@example.org"
    db.commit()
    r = client.post("/api/v1/auth/otp/request", json={"phone": chp.phone})
    assert r.status_code == 202 and r.json()["channel"] == "email"
    assert by_email.sent[-1]["To"] == "chp@example.org"
    assert "Nambari yako ya kuingia" in by_email.sent[-1].get_content()  # in the CHP's language


def test_sms_servers_still_say_sms(client, make):
    r = client.post("/api/v1/auth/otp/request", json={"phone": make.chp(make.unit()).phone})
    assert r.json()["channel"] == "sms"


def test_replies_go_through_the_outbox_by_email(by_email, make, db):
    unit = make.unit()
    with_email, without, refused = make.chp(unit), make.chp(unit), make.chp(unit)
    with_email.email, refused.email = "a@example.org", "gone@example.org"
    db.commit()
    by_email.refuse.add("gone@example.org")
    rows = [
        sms.queue_sms(db, phone=c.phone, message="Jamii Pulse: Action on Medicines. Done", kind="status", chp_id=c.id)
        for c in (with_email, without, refused)
    ]
    db.commit()
    assert [sms.deliver(db, r) for r in rows] == [True, False, False]
    assert [r.status for r in rows] == ["sent", "failed", "failed"]  # retrying would not help the last two
    assert rows[1].last_error == "no email address on file"
    assert by_email.sent[0]["Subject"] == "Jamii Pulse: Action on Medicines"


def test_a_wrong_app_password_is_retried_later(by_email, make, db):
    chp = make.chp(make.unit())
    chp.email = "a@example.org"
    db.commit()
    by_email.fail_login = True
    row = sms.queue_sms(db, phone=chp.phone, message="Jamii Pulse: hello", kind="status", chp_id=chp.id)
    assert sms.deliver(db, row) is False
    assert row.status == "queued" and row.attempts == 1 and "SMTPAuthenticationError" in row.last_error


def test_email_needs_the_gmail_login_outside_local():
    with pytest.raises(RuntimeError, match="JAMII_SMTP_USERNAME"):
        Settings(environment="production", sms_backend="email", **KEYS).check()
    Settings(environment="production", sms_backend="email", smtp_username="x", smtp_password="y", **KEYS).check()
    Settings(environment="local", sms_backend="email").check()


def test_admin_adds_and_changes_email_addresses(client, make, db):
    admin = make.user("admin", name="Daudi")
    chp = make.chp(make.unit())
    csrf = web_login(client, admin)
    client.post(
        "/admin/users",
        data={
            "csrf": csrf,
            "phone": "0700 000 093",
            "name": "Tester",
            "role": "county",
            "county": "Nairobi",
            "email": " Tester@Example.org ",
        },
    )
    assert db.query(User).filter_by(phone="+254700000093").one().email == "tester@example.org"
    r = client.post(f"/admin/users/{admin.id}/email", data={"csrf": csrf, "email": "not an email"})
    assert "does not look like an email address" in r.text
    r = client.post(f"/admin/users/{admin.id}/email", data={"csrf": csrf, "email": "daudi@example.org"})
    assert "Email saved: da***@example.org" in r.text
    client.post(f"/admin/chps/{chp.id}/email", data={"csrf": csrf, "email": "chp@example.org"})
    db.expire_all()
    assert db.get(User, admin.id).email == "daudi@example.org" and db.get(Chp, chp.id).email == "chp@example.org"
    assert "chp@example.org" not in client.get("/admin").text  # shown masked, like phone numbers


def test_start_up_gives_the_first_admin_an_email_once(db, monkeypatch):
    if get_engine().dialect.name == "postgresql":
        pytest.skip("the PostgreSQL path (lock + Alembic) is tested in test_migrations.py")
    s = get_settings()
    monkeypatch.setattr(s, "auto_migrate", True)
    monkeypatch.setattr(s, "bootstrap_admin_phone", "0700 000 091")
    monkeypatch.setattr(s, "bootstrap_admin_email", "Daudi@Example.org")
    assert bootstrap.bootstrap()["admin_email_set"] == 1
    admin = db.query(User).filter_by(role=Role.ADMIN).one()
    assert admin.email == "daudi@example.org"
    monkeypatch.setattr(s, "bootstrap_admin_email", "someone.else@example.org")
    assert bootstrap.bootstrap()["admin_email_set"] == 0  # never overwrites
    db.expire_all()
    assert db.get(User, admin.id).email == "daudi@example.org"


def test_tokens_still_work_for_the_app(client, make):
    # Changing how codes travel must not touch existing sessions.
    chp = make.chp(make.unit())
    assert client.get("/api/v1/me", headers=bearer(chp)).status_code == 200
