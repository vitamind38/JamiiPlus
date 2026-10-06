"""PostgreSQL DDL checks that need no database, so they also run in the fast SQLite suite."""

from geoalchemy2 import Geometry
from geoalchemy2.admin.dialects.common import _get_gis_cols
from geoalchemy2.admin.dialects.postgresql import check_management
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from jamii_api.db import Base
from jamii_api.models import CommunityHealthUnit


def test_geoalchemy_hooks_accept_our_geometry_type():
    # GeoAlchemy2 runs these on every CREATE/DROP TABLE on PostgreSQL, calling
    # load_dialect_impl(None) on TypeDecorators. It must not crash, for any table.
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            check_management(col)
        assert _get_gis_cols(table, Geometry, dialect, check_col_management=check_management) == []


def test_geometry_column_and_gist_index_compile_for_postgis():
    dialect = postgresql.dialect()
    table = CommunityHealthUnit.__table__
    assert "geom geometry(GEOMETRY,4326)" in str(CreateTable(table).compile(dialect=dialect))
    gist = next(i for i in table.indexes if i.name == "ix_community_health_unit_geom")
    assert "USING gist (geom)" in str(CreateIndex(gist).compile(dialect=dialect))
