"""Email addresses for officers and CHPs, for sending login codes and replies by email when
there is no budget for SMS.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("email", sa.String(254), nullable=True))
    op.add_column("chp", sa.Column("email", sa.String(254), nullable=True))


def downgrade() -> None:
    op.drop_column("chp", "email")
    op.drop_column("app_user", "email")
