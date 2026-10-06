"""Phone numbers, pseudonyms, one-time codes and tokens."""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

import jwt

from jamii_api.config import get_settings

_KE_PHONE = re.compile(r"^(?:\+?254|0)?([17]\d{8})$")


class InvalidPhone(ValueError):
    pass


def normalize_phone(raw: str) -> str:
    """Kenyan mobile numbers in any common form -> E.164 (+2547XXXXXXXX / +2541XXXXXXXX)."""
    digits = re.sub(r"[\s\-().]", "", raw or "")
    m = _KE_PHONE.match(digits)
    if not m:
        raise InvalidPhone("Enter a Kenyan mobile number, for example 0712 345 678")
    return "+254" + m.group(1)


def _hmac(key: str, value: str) -> str:
    return hmac.new(key.encode(), value.encode(), hashlib.sha256).hexdigest()


def phone_hash(phone: str) -> str:
    return _hmac(get_settings().secret_key, "phone:" + phone)


def pseudonym(chp_id: int) -> str:
    """How supervisors see a CHP: stable, but not reversible without the key."""
    return "CHP-" + _hmac(get_settings().pseudonym_key, f"chp:{chp_id}")[:6].upper()


def mask_phone(phone: str) -> str:
    return phone[:7] + "***" + phone[-2:] if len(phone) > 9 else "***"


def new_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def otp_hash(phone: str, code: str) -> str:
    return _hmac(get_settings().secret_key, f"otp:{phone}:{code}")


def codes_match(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def issue_token(subject_type: str, subject_id: int, token_version: int, days: int) -> str:
    now = datetime.now(UTC)
    claims = {
        "sub": str(subject_id),
        "typ": subject_type,
        "ver": token_version,
        "iat": now,
        "exp": now + timedelta(days=days),
    }
    return jwt.encode(claims, get_settings().secret_key, algorithm="HS256")


def read_token(token: str) -> dict:
    return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
