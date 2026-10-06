"""Initial schema: the seven core tables plus theme, app_user, sms_outbox, otp_challenge, spike_alert.

No table holds a patient identity. The audit log lives in a separate database.

Revision ID: 0001
Revises:
Create Date: 2026-10-06
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

TS = sa.DateTime(timezone=True)

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "community_health_unit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("ward", sa.String(length=120), nullable=False),
        sa.Column("sub_county", sa.String(length=120), nullable=False),
        sa.Column("county", sa.String(length=120), nullable=False),
        sa.Column("geom", Geometry(geometry_type="GEOMETRY", srid=4326, spatial_index=False), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_community_health_unit")),
        sa.UniqueConstraint("code", name=op.f("uq_community_health_unit_code")),
    )
    op.create_index(op.f("ix_community_health_unit_county"), "community_health_unit", ["county"], unique=False)
    op.create_index(op.f("ix_community_health_unit_sub_county"), "community_health_unit", ["sub_county"], unique=False)
    op.create_index(op.f("ix_community_health_unit_ward"), "community_health_unit", ["ward"], unique=False)
    op.create_table(
        "otp_challenge",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone_hash", sa.String(length=64), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("consumed_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_otp_challenge")),
    )
    op.create_index(op.f("ix_otp_challenge_created_at"), "otp_challenge", ["created_at"], unique=False)
    op.create_index(op.f("ix_otp_challenge_phone_hash"), "otp_challenge", ["phone_hash"], unique=False)
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("can_review", sa.Boolean(), nullable=False),
        sa.Column("chu_id", sa.Integer(), nullable=True),
        sa.Column("sub_county", sa.String(length=120), nullable=True),
        sa.Column("county", sa.String(length=120), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["chu_id"], ["community_health_unit.id"], name=op.f("fk_app_user_chu_id_community_health_unit")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_app_user")),
        sa.UniqueConstraint("phone", name=op.f("uq_app_user_phone")),
    )
    op.create_table(
        "chp",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("chu_id", sa.Integer(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("consent_version", sa.String(length=32), nullable=True),
        sa.Column("consented_at", TS, nullable=True),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.ForeignKeyConstraint(
            ["chu_id"], ["community_health_unit.id"], name=op.f("fk_chp_chu_id_community_health_unit")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chp")),
        sa.UniqueConstraint("phone", name=op.f("uq_chp_phone")),
    )
    op.create_index(op.f("ix_chp_chu_id"), "chp", ["chu_id"], unique=False)
    op.create_table(
        "theme",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("label_en", sa.String(length=120), nullable=False),
        sa.Column("label_sw", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], name=op.f("fk_theme_created_by_app_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_theme")),
        sa.UniqueConstraint("code", name=op.f("uq_theme_code")),
    )
    op.create_table(
        "issue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theme_code", sa.String(length=40), nullable=False),
        sa.Column("ward", sa.String(length=120), nullable=False),
        sa.Column("sub_county", sa.String(length=120), nullable=False),
        sa.Column("county", sa.String(length=120), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("resolution", sa.String(length=20), nullable=True),
        sa.Column("owner_id", sa.Integer(), nullable=True),
        sa.Column("report_count", sa.Integer(), nullable=False),
        sa.Column("first_reported_at", TS, nullable=False),
        sa.Column("last_reported_at", TS, nullable=False),
        sa.Column("first_response_at", TS, nullable=True),
        sa.Column("resolved_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.ForeignKeyConstraint(["owner_id"], ["app_user.id"], name=op.f("fk_issue_owner_id_app_user")),
        sa.ForeignKeyConstraint(["theme_code"], ["theme.code"], name=op.f("fk_issue_theme_code_theme")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_issue")),
    )
    op.create_index(op.f("ix_issue_county"), "issue", ["county"], unique=False)
    op.create_index(op.f("ix_issue_status"), "issue", ["status"], unique=False)
    op.create_index(op.f("ix_issue_sub_county"), "issue", ["sub_county"], unique=False)
    op.create_index(op.f("ix_issue_theme_code"), "issue", ["theme_code"], unique=False)
    op.create_index(op.f("ix_issue_ward"), "issue", ["ward"], unique=False)
    op.create_table(
        "spike_alert",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("theme_code", sa.String(length=40), nullable=False),
        sa.Column("ward", sa.String(length=120), nullable=False),
        sa.Column("sub_county", sa.String(length=120), nullable=False),
        sa.Column("county", sa.String(length=120), nullable=False),
        sa.Column("window_start", TS, nullable=False),
        sa.Column("window_end", TS, nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.Column("baseline", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.ForeignKeyConstraint(["reviewed_by"], ["app_user.id"], name=op.f("fk_spike_alert_reviewed_by_app_user")),
        sa.ForeignKeyConstraint(["theme_code"], ["theme.code"], name=op.f("fk_spike_alert_theme_code_theme")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_spike_alert")),
    )
    op.create_index(op.f("ix_spike_alert_county"), "spike_alert", ["county"], unique=False)
    op.create_index(op.f("ix_spike_alert_status"), "spike_alert", ["status"], unique=False)
    op.create_index(op.f("ix_spike_alert_sub_county"), "spike_alert", ["sub_county"], unique=False)
    op.create_table(
        "report",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chp_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=True),
        sa.Column("channel", sa.String(length=10), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False),
        sa.Column("chu_id", sa.Integer(), nullable=False),
        sa.Column("ward", sa.String(length=120), nullable=False),
        sa.Column("sub_county", sa.String(length=120), nullable=False),
        sa.Column("county", sa.String(length=120), nullable=False),
        sa.Column("chp_theme_code", sa.String(length=40), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("redaction", sa.String(length=20), nullable=False),
        sa.Column("audio_key", sa.String(length=200), nullable=True),
        sa.Column("audio_mime", sa.String(length=60), nullable=True),
        sa.Column("audio_expires_at", TS, nullable=True),
        sa.Column("text_expires_at", TS, nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("hold_reason", sa.String(length=200), nullable=True),
        sa.Column("issue_id", sa.Integer(), nullable=True),
        sa.Column("reported_at", TS, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.Column("withdrawn_at", TS, nullable=True),
        sa.ForeignKeyConstraint(["chp_id"], ["chp.id"], name=op.f("fk_report_chp_id_chp")),
        sa.ForeignKeyConstraint(
            ["chu_id"], ["community_health_unit.id"], name=op.f("fk_report_chu_id_community_health_unit")
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["issue.id"], name=op.f("fk_report_issue_id_issue")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report")),
        sa.UniqueConstraint("chp_id", "client_id", name="uq_report_chp_client"),
    )
    op.create_index(op.f("ix_report_audio_expires_at"), "report", ["audio_expires_at"], unique=False)
    op.create_index(op.f("ix_report_chp_id"), "report", ["chp_id"], unique=False)
    op.create_index(op.f("ix_report_chu_id"), "report", ["chu_id"], unique=False)
    op.create_index(op.f("ix_report_county"), "report", ["county"], unique=False)
    op.create_index(op.f("ix_report_created_at"), "report", ["created_at"], unique=False)
    op.create_index(op.f("ix_report_issue_id"), "report", ["issue_id"], unique=False)
    op.create_index(op.f("ix_report_status"), "report", ["status"], unique=False)
    op.create_index(op.f("ix_report_sub_county"), "report", ["sub_county"], unique=False)
    op.create_index(op.f("ix_report_text_expires_at"), "report", ["text_expires_at"], unique=False)
    op.create_index(op.f("ix_report_updated_at"), "report", ["updated_at"], unique=False)
    op.create_index(op.f("ix_report_ward"), "report", ["ward"], unique=False)
    op.create_table(
        "response",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("officer_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("action_text", sa.Text(), nullable=False),
        sa.Column("sms_text", sa.Text(), nullable=False),
        sa.Column("recipients", sa.Integer(), nullable=False),
        sa.Column("sms_sent", sa.Boolean(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.ForeignKeyConstraint(["issue_id"], ["issue.id"], name=op.f("fk_response_issue_id_issue")),
        sa.ForeignKeyConstraint(["officer_id"], ["app_user.id"], name=op.f("fk_response_officer_id_app_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_response")),
    )
    op.create_index(op.f("ix_response_issue_id"), "response", ["issue_id"], unique=False)
    op.create_table(
        "classification",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("theme", sa.String(length=40), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model_version", sa.String(length=80), nullable=True),
        sa.Column("final_theme", sa.String(length=40), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", TS, nullable=True),
        sa.Column("recheck_theme", sa.String(length=40), nullable=True),
        sa.Column("rechecked_by", sa.Integer(), nullable=True),
        sa.Column("rechecked_at", TS, nullable=True),
        sa.Column("recheck_requested_at", TS, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.ForeignKeyConstraint(["final_theme"], ["theme.code"], name=op.f("fk_classification_final_theme_theme")),
        sa.ForeignKeyConstraint(
            ["rechecked_by"], ["app_user.id"], name=op.f("fk_classification_rechecked_by_app_user")
        ),
        sa.ForeignKeyConstraint(
            ["report_id"], ["report.id"], name=op.f("fk_classification_report_id_report"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["reviewed_by"], ["app_user.id"], name=op.f("fk_classification_reviewed_by_app_user")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_classification")),
        sa.UniqueConstraint("report_id", name=op.f("uq_classification_report_id")),
    )
    op.create_index(op.f("ix_classification_final_theme"), "classification", ["final_theme"], unique=False)
    op.create_index(
        op.f("ix_classification_recheck_requested_at"), "classification", ["recheck_requested_at"], unique=False
    )
    op.create_table(
        "sms_outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("chp_id", sa.Integer(), nullable=True),
        sa.Column("phone", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("response_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("provider_id", sa.String(length=80), nullable=True),
        sa.Column("delivery_status", sa.String(length=40), nullable=True),
        sa.Column("next_attempt_at", TS, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("sent_at", TS, nullable=True),
        sa.ForeignKeyConstraint(["chp_id"], ["chp.id"], name=op.f("fk_sms_outbox_chp_id_chp")),
        sa.ForeignKeyConstraint(["response_id"], ["response.id"], name=op.f("fk_sms_outbox_response_id_response")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sms_outbox")),
    )
    op.create_index(op.f("ix_sms_outbox_chp_id"), "sms_outbox", ["chp_id"], unique=False)
    op.create_index(op.f("ix_sms_outbox_response_id"), "sms_outbox", ["response_id"], unique=False)
    op.create_index(op.f("ix_sms_outbox_status"), "sms_outbox", ["status"], unique=False)
    op.create_table(
        "transcript",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("report_id", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model_version", sa.String(length=80), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("machine_text", sa.Text(), nullable=True),
        sa.Column("machine_model_version", sa.String(length=80), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("updated_at", TS, nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["app_user.id"], name=op.f("fk_transcript_created_by_app_user")),
        sa.ForeignKeyConstraint(
            ["report_id"], ["report.id"], name=op.f("fk_transcript_report_id_report"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transcript")),
        sa.UniqueConstraint("report_id", name=op.f("uq_transcript_report_id")),
    )
    op.create_index("ix_community_health_unit_geom", "community_health_unit", ["geom"], postgresql_using="gist")


def downgrade() -> None:
    op.drop_index("ix_community_health_unit_geom", table_name="community_health_unit")
    op.drop_table("transcript")
    op.drop_index(op.f("ix_sms_outbox_status"), table_name="sms_outbox")
    op.drop_index(op.f("ix_sms_outbox_response_id"), table_name="sms_outbox")
    op.drop_index(op.f("ix_sms_outbox_chp_id"), table_name="sms_outbox")
    op.drop_table("sms_outbox")
    op.drop_index(op.f("ix_classification_recheck_requested_at"), table_name="classification")
    op.drop_index(op.f("ix_classification_final_theme"), table_name="classification")
    op.drop_table("classification")
    op.drop_index(op.f("ix_response_issue_id"), table_name="response")
    op.drop_table("response")
    op.drop_index(op.f("ix_report_ward"), table_name="report")
    op.drop_index(op.f("ix_report_updated_at"), table_name="report")
    op.drop_index(op.f("ix_report_text_expires_at"), table_name="report")
    op.drop_index(op.f("ix_report_sub_county"), table_name="report")
    op.drop_index(op.f("ix_report_status"), table_name="report")
    op.drop_index(op.f("ix_report_issue_id"), table_name="report")
    op.drop_index(op.f("ix_report_created_at"), table_name="report")
    op.drop_index(op.f("ix_report_county"), table_name="report")
    op.drop_index(op.f("ix_report_chu_id"), table_name="report")
    op.drop_index(op.f("ix_report_chp_id"), table_name="report")
    op.drop_index(op.f("ix_report_audio_expires_at"), table_name="report")
    op.drop_table("report")
    op.drop_index(op.f("ix_spike_alert_sub_county"), table_name="spike_alert")
    op.drop_index(op.f("ix_spike_alert_status"), table_name="spike_alert")
    op.drop_index(op.f("ix_spike_alert_county"), table_name="spike_alert")
    op.drop_table("spike_alert")
    op.drop_index(op.f("ix_issue_ward"), table_name="issue")
    op.drop_index(op.f("ix_issue_theme_code"), table_name="issue")
    op.drop_index(op.f("ix_issue_sub_county"), table_name="issue")
    op.drop_index(op.f("ix_issue_status"), table_name="issue")
    op.drop_index(op.f("ix_issue_county"), table_name="issue")
    op.drop_table("issue")
    op.drop_table("theme")
    op.drop_index(op.f("ix_chp_chu_id"), table_name="chp")
    op.drop_table("chp")
    op.drop_table("app_user")
    op.drop_index(op.f("ix_otp_challenge_phone_hash"), table_name="otp_challenge")
    op.drop_index(op.f("ix_otp_challenge_created_at"), table_name="otp_challenge")
    op.drop_table("otp_challenge")
    op.drop_index(op.f("ix_community_health_unit_ward"), table_name="community_health_unit")
    op.drop_index(op.f("ix_community_health_unit_sub_county"), table_name="community_health_unit")
    op.drop_index(op.f("ix_community_health_unit_county"), table_name="community_health_unit")
    op.drop_table("community_health_unit")
