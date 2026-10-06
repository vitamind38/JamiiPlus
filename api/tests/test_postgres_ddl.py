"""PostgreSQL DDL checks that need no database, so they also run in the fast SQLite suite."""

import pytest
from geoalchemy2 import Geometry
from geoalchemy2.admin.dialects import postgresql as gis_pg
from geoalchemy2.admin.dialects.common import _get_gis_cols
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from jamii_api.db import Base
from jamii_api.models import CommunityHealthUnit


class _NoSqlBind:
    """Stands in for a PostgreSQL connection; the hooks must not need to run any SQL."""

    dialect = postgresql.dialect()

    def execute(self, stmt, *a, **kw):
        raise AssertionError(f"GeoAlchemy2 tried to run SQL for our geometry column: {stmt}")


@pytest.mark.parametrize("table", Base.metadata.sorted_tables, ids=lambda t: t.name)
def test_geoalchemy_create_and_drop_hooks(table):
    # GeoAlchemy2 runs these on every CREATE/DROP TABLE on PostgreSQL. Our column is a plain
    # typmod column with its own declared index, so the hooks must leave it alone.
    bind = _NoSqlBind()
    indexes = set(table.indexes)
    gis_pg.before_create(table, bind)
    gis_pg.after_create(table, bind)
    gis_pg.before_drop(table, bind)
    gis_pg.after_drop(table, bind)
    assert set(table.indexes) == indexes
    assert _get_gis_cols(table, Geometry, bind.dialect, check_col_management=gis_pg.check_management) == []


def test_geometry_column_and_gist_index_compile_for_postgis():
    dialect = postgresql.dialect()
    table = CommunityHealthUnit.__table__
    assert "geom geometry(GEOMETRY,4326)" in str(CreateTable(table).compile(dialect=dialect))
    gist = next(i for i in table.indexes if i.name == "ix_community_health_unit_geom")
    assert "USING gist (geom)" in str(CreateIndex(gist).compile(dialect=dialect))
