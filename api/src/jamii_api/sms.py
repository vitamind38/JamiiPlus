"""Outbound SMS through Africa's Talking, with a console backend for local work.

Every message except one-time codes goes through the sms_outbox table first, so a message
is never lost if the queue or the provider is down; workers retry with backoff.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from jamii_api.config import get_settings
from jamii_api.db.base import utcnow
from jamii_api.models import SmsOutbox
from jamii_api.security import mask_phone

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


@lru_cache
def get_backend() -> SmsBackend:
    if get_settings().sms_backend == "africastalking":
        return AfricasTalkingBackend()
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
