from alembic import context
from sqlalchemy import engine_from_config, pool

from jamii_api import models  # noqa: F401  (registers the tables)
from jamii_api.config import get_settings
from jamii_api.db import Base

config = context.config
# A caller (the demo bootstrap) may pass a direct, unpooled URL; otherwise use the app's.
url = config.attributes.get("database_url") or get_settings().database_url
config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # PostGIS owns spatial_ref_sys and its own schemas; the dashboards schema holds views.
    if type_ == "table" and (
        name == "spatial_ref_sys" or getattr(obj, "schema", None) in {"dashboards", "tiger", "topology"}
    ):
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, include_object=include_object, compare_type=False
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
