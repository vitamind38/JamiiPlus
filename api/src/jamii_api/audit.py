"""Who viewed or changed what. Written to a separate database that the app can only append to.

Audit writes never block the main action: if the audit database is down, the event is
logged to stderr with the same fields so it can be replayed, and the request continues.
"""

import json
import logging
from datetime import datetime
from functools import lru_cache

from sqlalchemy import JSON, Engine, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from jamii_api.config import get_settings
from jamii_api.db.base import TZDateTime, utcnow
from jamii_api.db.session import make_engine

log = logging.getLogger("jamii.audit")


class AuditBase(DeclarativeBase):
    pass


class AuditLog(AuditBase):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(TZDateTime, default=utcnow, index=True)
    actor_type: Mapped[str] = mapped_column(String(10))  # user | chp | system | channel
    actor_id: Mapped[int | None] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(60), index=True)
    object_type: Mapped[str | None] = mapped_column(String(40))
    object_id: Mapped[str | None] = mapped_column(String(40))
    ip: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSON, default=dict)


@lru_cache
def get_audit_engine() -> Engine:
    engine = make_engine(get_settings().audit_database_url)
    AuditBase.metadata.create_all(engine)
    return engine


@lru_cache
def _audit_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_audit_engine())


def record(
    action: str,
    *,
    actor_type: str,
    actor_id: int | None = None,
    object_type: str | None = None,
    object_id: object = None,
    ip: str | None = None,
    **details: object,
) -> None:
    entry = {
        "action": action,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "object_type": object_type,
        "object_id": None if object_id is None else str(object_id),
        "ip": ip,
        "details": details,
    }
    try:
        with _audit_sessionmaker()() as s:
            s.add(AuditLog(**entry))
            s.commit()
    except Exception:
        log.exception("AUDIT_WRITE_FAILED %s", json.dumps(entry, default=str))
