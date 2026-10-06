"""Dashboard views for Metabase, in their own schema.

Charts read these views, never the tables, so tables can change without breaking charts.
The views carry no CHP identifiers and no report text. A read-only `metabase_reader` role
(created in infra/postgres/init) is granted this schema and nothing else.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-06
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

VIEWS = {
    "reports": """
        SELECT r.id AS report_id,
               r.created_at,
               date_trunc('week', r.created_at)::date AS week,
               r.channel,
               r.language,
               r.county, r.sub_county, r.ward,
               u.name AS unit,
               c.final_theme AS theme,
               t.label_en AS theme_label,
               r.status AS pipeline_status,
               coalesce(i.status, 'received') AS loop_status,
               r.issue_id,
               r.audio_key IS NOT NULL AS has_audio,
               (c.reviewed_by IS NOT NULL) AS human_reviewed,
               c.theme AS model_theme,
               c.confidence AS model_confidence,
               c.model_version
        FROM report r
        JOIN community_health_unit u ON u.id = r.chu_id
        LEFT JOIN classification c ON c.report_id = r.id
        LEFT JOIN theme t ON t.code = c.final_theme
        LEFT JOIN issue i ON i.id = r.issue_id
        WHERE r.status <> 'withdrawn'
    """,
    "issues": """
        SELECT i.id AS issue_id,
               i.theme_code AS theme,
               t.label_en AS theme_label,
               i.county, i.sub_county, i.ward,
               i.level, i.status, i.resolution,
               i.report_count,
               i.first_reported_at, i.last_reported_at, i.first_response_at, i.resolved_at,
               extract(epoch FROM (i.first_response_at - i.first_reported_at)) / 86400.0 AS days_to_first_response,
               (i.status = 'action_taken' OR (i.status = 'resolved' AND i.resolution = 'actioned')) AS has_action
        FROM issue i
        JOIN theme t ON t.code = i.theme_code
    """,
    "report_response_times": """
        SELECT r.id AS report_id,
               r.created_at,
               date_trunc('week', r.created_at)::date AS week,
               r.county, r.sub_county, r.ward,
               c.final_theme AS theme,
               fr.first_response_at,
               extract(epoch FROM (fr.first_response_at - r.created_at)) / 86400.0 AS days_to_first_response
        FROM report r
        LEFT JOIN classification c ON c.report_id = r.id
        LEFT JOIN LATERAL (
            SELECT min(x.created_at) AS first_response_at
            FROM response x
            WHERE x.issue_id = r.issue_id AND x.kind <> 'escalated' AND x.created_at >= r.created_at
        ) fr ON true
        WHERE r.status = 'grouped'
    """,
    "weekly_theme_counts": """
        SELECT date_trunc('week', r.created_at)::date AS week,
               r.county, r.sub_county, r.ward,
               coalesce(c.final_theme, 'untagged') AS theme,
               count(*) AS reports
        FROM report r
        LEFT JOIN classification c ON c.report_id = r.id
        WHERE r.status <> 'withdrawn'
        GROUP BY 1, 2, 3, 4, 5
    """,
    "response_summary": """
        SELECT i.county, i.sub_county,
               count(*) AS issues,
               count(*) FILTER (WHERE i.status = 'action_taken'
                                OR (i.status = 'resolved' AND i.resolution = 'actioned')) AS issues_with_action,
               percentile_cont(0.5) WITHIN GROUP (
                   ORDER BY extract(epoch FROM (i.first_response_at - i.first_reported_at)) / 86400.0
               ) AS median_days_to_first_response
        FROM issue i
        GROUP BY 1, 2
    """,
    "review_queue": """
        SELECT r.status AS queue,
               r.county, r.sub_county,
               count(*) AS waiting,
               extract(epoch FROM (now() - min(r.created_at))) / 3600.0 AS oldest_waiting_hours
        FROM report r
        WHERE r.status IN ('needs_redaction', 'needs_transcription', 'needs_tagging', 'processing')
        GROUP BY 1, 2, 3
    """,
    "model_agreement_weekly": """
        SELECT date_trunc('week', coalesce(c.rechecked_at, c.reviewed_at))::date AS week,
               c.model_version,
               count(*) FILTER (WHERE c.rechecked_at IS NOT NULL) AS rechecked,
               count(*) FILTER (WHERE c.rechecked_at IS NOT NULL AND c.recheck_theme = c.theme) AS recheck_agreed,
               count(*) FILTER (WHERE c.reviewed_by IS NOT NULL) AS suggestions_reviewed,
               count(*) FILTER (WHERE c.reviewed_by IS NOT NULL AND c.final_theme = c.theme) AS suggestions_agreed
        FROM classification c
        WHERE c.theme IS NOT NULL AND coalesce(c.rechecked_at, c.reviewed_at) IS NOT NULL
        GROUP BY 1, 2
    """,
    "unit_map": """
        SELECT u.id AS unit_id, u.name AS unit, u.ward, u.sub_county, u.county,
               ST_Y(ST_PointOnSurface(u.geom)) AS latitude,
               ST_X(ST_PointOnSurface(u.geom)) AS longitude,
               count(r.id) FILTER (WHERE r.created_at >= now() - interval '90 days') AS reports_90d
        FROM community_health_unit u
        LEFT JOIN report r ON r.chu_id = u.id AND r.status <> 'withdrawn'
        GROUP BY u.id
    """,
}


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS dashboards")
    for name, sql in VIEWS.items():
        op.execute(f"CREATE OR REPLACE VIEW dashboards.{name} AS {sql}")
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'metabase_reader') THEN
            GRANT USAGE ON SCHEMA dashboards TO metabase_reader;
            GRANT SELECT ON ALL TABLES IN SCHEMA dashboards TO metabase_reader;
            ALTER DEFAULT PRIVILEGES IN SCHEMA dashboards GRANT SELECT ON TABLES TO metabase_reader;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for name in reversed(list(VIEWS)):
        op.execute(f"DROP VIEW IF EXISTS dashboards.{name}")
    op.execute("DROP SCHEMA IF EXISTS dashboards")
