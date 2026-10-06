"""Bootstrap for the public demo (Vercel): migrate, then load synthetic data once.

Runs at every cold start and is cheap after the first: one advisory lock, one Alembic
version check, one query. Only ever runs with JAMII_DEMO_MODE on.
"""

import logging
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select, text

from jamii_api.config import Settings, get_settings, with_psycopg_driver
from jamii_api.db import Base, get_engine, session_scope
from jamii_api.db.session import make_engine
from jamii_api.models import Report
from jamii_api.seed import demo_data, seed_themes

log = logging.getLogger("jamii.demo")

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"
LOCK_ID = 7_265_431  # any constant; serialises bootstraps across instances


def _direct_url(settings: Settings) -> str:
    """Migrations need a session-level lock, so they use Neon's direct (unpooled) connection."""
    raw = os.environ.get("DATABASE_URL_UNPOOLED")
    return with_psycopg_driver(raw) if raw else settings.database_url


def bootstrap() -> dict[str, int] | None:
    settings = get_settings()
    if not settings.demo_mode:
        return None
    if get_engine().dialect.name != "postgresql":
        Base.metadata.create_all(get_engine())  # local try-out on SQLite
        return _seed()
    engine = make_engine(_direct_url(settings))
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
            try:
                cfg = Config(str(ALEMBIC_INI))
                cfg.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
                cfg.attributes["database_url"] = _direct_url(settings)
                command.upgrade(cfg, "head")
                return _seed()
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
                conn.commit()
    finally:
        engine.dispose()


def _seed() -> dict[str, int]:
    with session_scope() as db:
        seed_themes(db)
        if db.scalar(select(Report.id).limit(1)) is None:
            result = demo_data(db)
            log.info("demo data loaded: %s", result)
            return result
    return {}
