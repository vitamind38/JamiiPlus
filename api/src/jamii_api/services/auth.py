"""Phone-number login with one-time codes, rate limits and lockout."""

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from jamii_api import audit, messages, sms
from jamii_api.config import get_settings
from jamii_api.db.base import utcnow
from jamii_api.models import Chp, OtpChallenge, User
from jamii_api.security import codes_match, new_otp, normalize_phone, otp_hash, phone_hash


class AuthError(ValueError):
    pass


class TooManyAttempts(AuthError):
    pass


@dataclass
class OtpSent:
    phone: str
    dev_code: str | None = None  # only in local development or the public demo (no real SMS there)


def _locked(db: Session, ph: str) -> bool:
    s = get_settings()
    since = utcnow() - timedelta(minutes=s.lockout_minutes)
    failed = db.scalar(
        select(func.coalesce(func.sum(OtpChallenge.failed_attempts), 0)).where(
            OtpChallenge.phone_hash == ph, OtpChallenge.created_at >= since
        )
    )
    return failed >= s.otp_max_failed_attempts


def request_code(db: Session, raw_phone: str, audience: str, ip: str | None = None) -> OtpSent:
    """Send a code if the phone belongs to an active account of this audience ("chp" or "officer").

    The response is the same whether or not the number is registered.
    """
    s = get_settings()
    phone = normalize_phone(raw_phone)
    ph = phone_hash(phone)
    if _locked(db, ph):
        raise TooManyAttempts(f"Too many wrong codes. Try again in {s.lockout_minutes} minutes.")
    since = utcnow() - timedelta(minutes=s.otp_request_window_minutes)
    recent = db.scalar(
        select(func.count(OtpChallenge.id)).where(OtpChallenge.phone_hash == ph, OtpChallenge.created_at >= since)
    )
    if recent >= s.otp_max_requests:
        raise TooManyAttempts("Too many codes requested. Wait a few minutes and try again.")

    account = _account(db, phone, audience)
    code = new_otp()
    db.add(
        OtpChallenge(
            phone_hash=ph, code_hash=otp_hash(phone, code), expires_at=utcnow() + timedelta(seconds=s.otp_ttl_seconds)
        )
    )
    db.commit()
    if account is None:
        audit.record("auth.code_unknown_number", actor_type="system", ip=ip, audience=audience)
        return OtpSent(phone)
    language = getattr(account, "language", "en")
    sms.send_now(phone, messages.sms("otp", language, code=code, minutes=s.otp_ttl_seconds // 60))
    audit.record("auth.code_sent", actor_type="chp" if audience == "chp" else "user", actor_id=account.id, ip=ip)
    return OtpSent(phone, code if s.shows_codes_on_screen else None)


def _account(db: Session, phone: str, audience: str) -> Chp | User | None:
    model = Chp if audience == "chp" else User
    return db.scalar(select(model).where(model.phone == phone, model.active.is_(True)))


def verify_code(db: Session, raw_phone: str, code: str, audience: str, ip: str | None = None) -> Chp | User:
    s = get_settings()
    phone = normalize_phone(raw_phone)
    ph = phone_hash(phone)
    if _locked(db, ph):
        raise TooManyAttempts(f"Too many wrong codes. Try again in {s.lockout_minutes} minutes.")
    challenge = db.scalar(
        select(OtpChallenge)
        .where(OtpChallenge.phone_hash == ph, OtpChallenge.consumed_at.is_(None))
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
    )
    now = utcnow()
    if challenge is None or challenge.expires_at < now:
        raise AuthError("The code has expired. Ask for a new one.")
    account = _account(db, phone, audience)
    if account is None or not codes_match(challenge.code_hash, otp_hash(phone, (code or "").strip())):
        challenge.failed_attempts += 1
        db.commit()
        audit.record("auth.code_wrong", actor_type="system", ip=ip, audience=audience)
        raise AuthError("That code is not right.")
    challenge.consumed_at = now
    db.commit()
    audit.record("auth.login", actor_type="chp" if audience == "chp" else "user", actor_id=account.id, ip=ip)
    return account
