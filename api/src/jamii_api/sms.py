"""Outbound messages: SMS through Africa's Talking, email (free, through a Gmail account), or the
server log for local work. The rest of the code calls them all "SMS".

Every message except one-time codes goes through the sms_outbox table first, so a message
is never lost if the queue or the provider is down; workers retry with backoff.
"""

import logging
import smtplib
import ssl
from dataclasses import dataclass
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from functools import lru_cache
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from jamii_api.config import get_settings
from jamii_api.db.base import utcnow
from jamii_api.models import SmsOutbox
from jamii_api.security import mask_email, mask_phone

log = logging.getLogger("jamii.sms")

MAX_ATTEMPTS = 6
AT_SUCCESS_CODES = {100, 101, 102}  # processed, sent, queued


@dataclass
class SendResult:
    ok: bool
    provider_id: str | None = None
    error: str | None = None
    retryable: bool = True


class SmsBackend(Protocol):
    def send(self, phone: str, message: str) -> SendResult: ...


class ConsoleBackend:
    """Logs messages instead of sending them: local development, tests, and staging before an SMS
    account exists (an operator reads their first login code from the server log)."""

    sent: list[tuple[str, str]] = []

    def send(self, phone: str, message: str) -> SendResult:
        ConsoleBackend.sent.append((phone, message))
        log.info("SMS to %s: %s", mask_phone(phone), message)
        return SendResult(ok=True, provider_id=f"console-{len(ConsoleBackend.sent)}")


class AfricasTalkingBackend:
    def __init__(self) -> None:
        s = get_settings()
        host = "api.sandbox.africastalking.com" if s.at_sandbox else "api.africastalking.com"
        self.url = f"https://{host}/version1/messaging"
        self.username = s.at_username
        self.api_key = s.at_api_key
        self.sender_id = s.at_sender_id

    def send(self, phone: str, message: str) -> SendResult:
        data = {"username": self.username, "to": phone, "message": message}
        if self.sender_id:
            data["from"] = self.sender_id
        try:
            r = httpx.post(
                self.url,
                data=data,
                headers={"apiKey": self.api_key, "Accept": "application/json"},
                timeout=15,
            )
        except httpx.HTTPError as e:
            return SendResult(ok=False, error=f"network: {e.__class__.__name__}")
        if r.status_code >= 500:
            return SendResult(ok=False, error=f"provider {r.status_code}")
        if r.status_code >= 400:
            return SendResult(ok=False, error=f"rejected {r.status_code}: {r.text[:120]}", retryable=False)
        try:
            recipient = r.json()["SMSMessageData"]["Recipients"][0]
        except (ValueError, KeyError, IndexError):
            return SendResult(ok=False, error=f"unexpected response: {r.text[:120]}")
        code = int(recipient.get("statusCode", 0))
        if code in AT_SUCCESS_CODES:
            return SendResult(ok=True, provider_id=recipient.get("messageId"))
        # 403 invalid number, 404 unsupported number, 406 blacklisted: retrying will not help.
        return SendResult(ok=False, error=f"AT {code} {recipient.get('status')}", retryable=code not in {403, 404, 406})


class EmailBackend:
    """Sends each message to the email address on file for that phone number. With a Gmail app
    password this costs nothing (about 500 messages a day). No address on file, no message."""

    def __init__(self) -> None:
        s = get_settings()
        self.host, self.port = s.smtp_host, s.smtp_port
        self.username, self.password = s.smtp_username, s.smtp_password
        self.sender = s.mail_from or s.smtp_username

    def send(self, phone: str, message: str) -> SendResult:
        to = email_for(phone)
        if not to:
            return SendResult(ok=False, error="no email address on file", retryable=False)
        mail = EmailMessage()
        mail["From"] = formataddr(("Jamii Pulse", self.sender))
        mail["To"] = to
        mail["Subject"] = email_subject(message)
        mail["Date"] = formatdate()
        mail["Message-ID"] = make_msgid(domain=self.sender.partition("@")[2] or None)
        mail.set_content(f"{message}\n\n-- \nJamii Pulse")
        try:
            with self._connect() as smtp:
                smtp.send_message(mail)
        except smtplib.SMTPRecipientsRefused:
            return SendResult(ok=False, error="email address refused", retryable=False)
        except (smtplib.SMTPException, OSError) as e:
            return SendResult(ok=False, error=f"email: {e.__class__.__name__}")
        log.info("email to %s", mask_email(to))  # never the body: it may hold a login code
        return SendResult(ok=True, provider_id=mail["Message-ID"][:80])

    def _connect(self) -> smtplib.SMTP:
        context = ssl.create_default_context()
        if self.port == 465:
            smtp = smtplib.SMTP_SSL(self.host, self.port, timeout=15, context=context)
        else:
            smtp = smtplib.SMTP(self.host, self.port, timeout=15)
        try:
            if self.port != 465:
                smtp.starttls(context=context)
            smtp.login(self.username, self.password)
        except Exception:
            smtp.close()
            raise
        return smtp


def email_for(phone: str) -> str | None:
    from jamii_api.db import get_sessionmaker
    from jamii_api.models import Chp, User

    with get_sessionmaker()() as db:
        for model in (Chp, User):
            email = db.scalar(select(model.email).where(model.phone == phone, model.email.isnot(None)).limit(1))
            if email:
                return email
    return None


def email_subject(message: str) -> str:
    """The message's first sentence, so a login code shows in the inbox list."""
    first = message.removeprefix("Jamii Pulse:").strip().split(". ")[0].rstrip(".")
    return f"Jamii Pulse: {first[:70]}"


@lru_cache
def get_backend() -> SmsBackend:
    backend = get_settings().sms_backend
    if backend == "africastalking":
        return AfricasTalkingBackend()
    if backend == "email":
        return EmailBackend()
    return ConsoleBackend()


def queue_sms(
    db: Session, *, phone: str, message: str, kind: str, chp_id: int | None = None, response_id: int | None = None
) -> SmsOutbox:
    row = SmsOutbox(phone=phone, message=message, kind=kind, chp_id=chp_id, response_id=response_id)
    db.add(row)
    db.flush()
    return row


def deliver(db: Session, row: SmsOutbox) -> bool:
    """Try one send. The caller commits."""
    if row.status != "queued":
        return row.status == "sent"
    result = get_backend().send(row.phone, row.message)
    row.attempts += 1
    if result.ok:
        row.status = "sent"
        row.sent_at = utcnow()
        row.provider_id = result.provider_id
        row.last_error = None
    else:
        row.last_error = (result.error or "")[:300]
        if not result.retryable or row.attempts >= MAX_ATTEMPTS:
            row.status = "failed"
        else:
            row.next_attempt_at = utcnow() + timedelta(minutes=2**row.attempts)
    if row.response_id is not None:
        _mark_response_sent(db, row.response_id)
    return result.ok


def _mark_response_sent(db: Session, response_id: int) -> None:
    from jamii_api.models import Response

    db.flush()
    pending = db.scalar(
        select(SmsOutbox.id).where(SmsOutbox.response_id == response_id, SmsOutbox.status == "queued").limit(1)
    )
    if pending is None:
        resp = db.get(Response, response_id)
        if resp is not None:
            resp.sms_sent = True


def dispatch(db: Session, ids: list[int]) -> None:
    """Hand queued messages to the workers; if the queue is unreachable, send them now."""
    from jamii_api import tasks

    if not ids:
        return
    if tasks.enqueue_many("jamii.send_sms", [[i] for i in ids]):
        return
    log.warning("queue unavailable, sending %d SMS inline", len(ids))
    for row in db.scalars(select(SmsOutbox).where(SmsOutbox.id.in_(ids))):
        deliver(db, row)
    db.commit()


def send_now(phone: str, message: str) -> SendResult:
    """For one-time codes only: sent directly and never written to the database."""
    return get_backend().send(phone, message)
