"""Migrations against real PostGIS (CI). Skipped on the SQLite unit-test database."""

from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import text

from jamii_api.db import Base, get_engine

pytestmark = pytest.mark.postgres

ALEMBIC_INI = Path(__file__).parents[1] / "alembic.ini"


@pytest.fixture
def pg():
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("needs PostgreSQL with PostGIS (set TEST_DATABASE_URL)")
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS dashboards CASCADE"))
    Base.metadata.drop_all(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    cfg = Config(str(ALEMBIC_INI))
    yield engine, cfg
    command.downgrade(cfg, "base")
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


def test_migrations_match_models_and_reverse(pg):
    engine, cfg = pg
    command.upgrade(cfg, "head")

    def include(obj, name, type_, reflected, compare_to):
        return not (type_ == "table" and name in {"spatial_ref_sys", "alembic_version"})

    with engine.connect() as conn:
        mc = MigrationContext.configure(conn, opts={"include_object": include, "compare_type": False})
        diff = compare_metadata(mc, Base.metadata)
    assert diff == [], f"models and migrations differ: {diff}"

    command.downgrade(cfg, "0001")
    command.upgrade(cfg, "head")


def test_dashboard_views_query(pg, db):
    engine, cfg = pg
    command.upgrade(cfg, "head")
    from jamii_api.seed import demo_data

    demo_data(db)
    db.commit()
    with engine.connect() as conn:
        for view in (
            "reports",
            "issues",
            "report_response_times",
            "weekly_theme_counts",
            "response_summary",
            "review_queue",
            "model_agreement_weekly",
            "unit_map",
        ):
            conn.execute(text(f"SELECT * FROM dashboards.{view} LIMIT 5")).all()
        cols = conn.execute(text("SELECT * FROM dashboards.reports LIMIT 1")).keys()
        assert "chp_id" not in cols and "raw_text" not in cols


def test_demo_bootstrap_migrates_and_seeds_once(pg, db, monkeypatch):
    from jamii_api import bootstrap
    from jamii_api.config import get_settings
    from jamii_api.models import Report

    monkeypatch.setattr(get_settings(), "demo_mode", True)
    first = bootstrap.bootstrap()  # takes the advisory lock, runs Alembic, loads demo data
    assert first and first["reports"] > 0
    assert "reports" not in bootstrap.bootstrap()  # a second cold start changes nothing
    assert db.query(Report).count() == first["reports"]
    engine, _ = pg
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"


def test_bootstrap_falls_back_when_the_migration_url_is_unreachable(pg, db, monkeypatch):
    from jamii_api import bootstrap
    from jamii_api.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "auto_migrate", True)
    monkeypatch.setattr(s, "migration_database_url", "postgresql+psycopg://x:y@127.0.0.1:1/nowhere")
    assert bootstrap.bootstrap()["themes_added"] == 9  # migrated and seeded over the app's URL
    engine, _ = pg
    with engine.connect() as conn:
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"
