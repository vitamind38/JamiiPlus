from datetime import UTC, datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, MetaData, Text, TypeDecorator
from sqlalchemy.orm import DeclarativeBase

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def utcnow() -> datetime:
    return datetime.now(UTC)


class _UTCDateTime(TypeDecorator):
    """Timestamps are stored with a time zone and always come back as aware UTC values."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:  # SQLite drops the zone
            value = value.replace(tzinfo=UTC)
        return value


TZDateTime = _UTCDateTime()


class GeometryType(TypeDecorator):
    """PostGIS geometry (SRID 4326) on PostgreSQL; EWKT text in the SQLite unit-test database.

    The app only writes EWKT strings ("SRID=4326;POINT(lon lat)"), which PostGIS casts
    implicitly; maps and spatial queries happen in SQL views. The GIST index is declared
    on the model so migrations and models match.
    """

    impl = Text
    cache_ok = True
    # Read directly by GeoAlchemy2's DDL hooks; without them the lookup falls through to Text.
    spatial_index = False  # the GIST index is declared on the model
    use_typmod = None  # a plain geometry(GEOMETRY,4326) column, not one managed by AddGeometryColumn()

    def load_dialect_impl(self, dialect):
        if dialect is None:  # GeoAlchemy2's DDL hooks inspect column types with no dialect
            return Text()
        if dialect.name == "postgresql":
            return dialect.type_descriptor(Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False))
        return dialect.type_descriptor(Text())
