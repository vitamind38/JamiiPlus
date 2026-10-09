"""Start-up for serverless hosting (Vercel): migrate the database, load the theme list, and
create the first admin. Demo deployments also load synthetic data.

Runs at every cold start and is cheap after the first: one advisory lock, one Alembic
version check, a few queries. Off unless JAMII_AUTO_MIGRATE or JAMII_DEMO_MODE is set.
"""

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.exc import OperationalError

from jamii_api import audit
from jamii_api.config import Settings, get_settings
from jamii_api.db import Base, get_engine, session_scope
from jamii_api.db.session import make_engine
from jamii_api.models import Report, Role, User
from jamii_api.security import normalize_phone
from jamii_api.seed import demo_data, seed_themes

log = logging.getLogger("jamii.bootstrap")

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
LOCK_ID = 7_265_431  # any constant; serialises start-ups across instances


def bootstrap() -> dict[str, int] | None:
    settings = get_settings()
    if not (settings.auto_migrate or settings.demo_mode):
        return None
    if get_engine().dialect.name != "postgresql":
        Base.metadata.create_all(get_engine())  # local try-out on SQLite
        return _prepare(settings)
    url, engine, conn = _migration_connection(settings)
    try:
        with conn:
            # A session-level lock only means something on a session pooler or direct connection.
            locking = ":6543/" not in url
            if locking:
                conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
            else:
                log.warning("migrating over a transaction pooler: set JAMII_MIGRATION_DATABASE_URL to port 5432")
            try:
                cfg = Config(str(ALEMBIC_INI))
                cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
                cfg.attributes["database_url"] = url
                command.upgrade(cfg, "head")
                return _prepare(settings)
            finally:
                if locking:
                    conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
                    conn.commit()
    finally:
        engine.dispose()


def _migration_connection(settings: Settings) -> tuple[str, Engine, Connection]:
    """The migration URL if it answers, else the app's own. Some hosts hand out a direct address
    that serverless functions cannot reach (Supabase's direct host is IPv6 only)."""
    url = settings.migration_database_url or settings.database_url
    engine = make_engine(url)
    try:
        return url, engine, engine.connect()
    except OperationalError:
        engine.dispose()
        if url == settings.database_url:
            raise
        log.warning("cannot reach the migration database URL; migrating over the app's connection")
    engine = make_engine(settings.database_url)
    return settings.database_url, engine, engine.connect()


def _prepare(settings: Settings) -> dict[str, int]:
    result: dict[str, int] = {}
    with session_scope() as db:
        result["themes_added"] = seed_themes(db)
        if settings.bootstrap_admin_phone:
            result["admin_created"] = int(
                ensure_admin(db, settings.bootstrap_admin_phone, settings.bootstrap_admin_name)
            )
        if settings.demo_mode and db.scalar(select(Report.id).limit(1)) is None:
            result.update(demo_data(db))
            log.info("demo data loaded: %s", result)
    return result


def ensure_admin(db, raw_phone: str, name: str) -> bool:
    """The first admin, only while there is none. Never touches an existing admin."""
    if db.scalar(select(User.id).where(User.role == Role.ADMIN, User.active.is_(True)).limit(1)):
        return False
    phone = normalize_phone(raw_phone)
    user = db.scalar(select(User).where(User.phone == phone))
    if user is None:
        db.add(User(phone=phone, name=name, role=Role.ADMIN))
    else:
        user.role, user.active = Role.ADMIN, True
    db.flush()
    audit.record("admin.bootstrapped", actor_type="system")
    log.info("first admin created")
    return True
