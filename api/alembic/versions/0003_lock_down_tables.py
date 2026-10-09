"""Row-level security on every table, and no access for Supabase's public API roles.

Supabase publishes the public schema through its REST API to the `anon` and `authenticated`
roles, whose key is public by design. Jamii Pulse never uses that API: the app connects as
the table owner, which row-level security does not restrict. So this turns RLS on with no
policies (deny all to anyone but the owner) and revokes the API roles' grants, including
for tables created later. On plain Postgres the roles do not exist and only RLS changes.

On Supabase the audit log shares this database, so it is created here too, locked down the
same way; elsewhere it lives in its own database (infra/postgres/init).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-10
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

TABLES = [
    "community_health_unit", "chp", "app_user", "theme", "issue", "report", "transcript",
    "classification", "response", "sms_outbox", "otp_challenge", "spike_alert", "alembic_version",
]


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            CREATE TABLE IF NOT EXISTS audit_log (
              id          SERIAL PRIMARY KEY,
              at          TIMESTAMPTZ NOT NULL DEFAULT now(),
              actor_type  VARCHAR(10) NOT NULL,
              actor_id    INTEGER,
              action      VARCHAR(60) NOT NULL,
              object_type VARCHAR(40),
              object_id   VARCHAR(40),
              ip          VARCHAR(64),
              details     JSON NOT NULL DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS ix_audit_log_at ON audit_log (at);
            CREATE INDEX IF NOT EXISTS ix_audit_log_action ON audit_log (action);
            ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
          END IF;
        END $$;
        """
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;
            REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM anon, authenticated;
            REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM anon, authenticated;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM anon, authenticated;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM anon, authenticated;
            ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON FUNCTIONS FROM anon, authenticated;
            REVOKE ALL ON SCHEMA dashboards FROM anon, authenticated;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    # The API roles' grants are not restored: Jamii Pulse never needs them.
