"""Baseline: full schema as of the pre-Alembic releases.

Revision ID: 0001
Revises:
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("token_nonce", sa.String, nullable=False),
        sa.Column("email", sa.String, nullable=False),
        sa.Column("password_hash", sa.String, nullable=False),
        sa.Column("display_name", sa.String),
        sa.Column("llm_consent", sa.Boolean),
        sa.Column("llm_consent_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "birth_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), unique=True),
        sa.Column("display_name", sa.String),
        sa.Column("year", sa.Integer), sa.Column("month", sa.Integer),
        sa.Column("day", sa.Integer), sa.Column("hour", sa.Integer),
        sa.Column("minute", sa.Integer), sa.Column("second", sa.Integer),
        sa.Column("place_name", sa.String), sa.Column("place_state", sa.String),
        sa.Column("place_country", sa.String), sa.Column("latitude", sa.Float),
        sa.Column("longitude", sa.Float), sa.Column("timezone_name", sa.String),
        sa.Column("utc_offset_hours", sa.Float),
        sa.Column("birth_time_precision", sa.String),
        sa.Column("chart_json", sa.Text),
        sa.Column("calc_fingerprint", sa.String),
        sa.Column("calibration_state", sa.String),
        sa.Column("predictions_allowed", sa.Boolean),
        sa.Column("rectified_from", sa.String, nullable=True),
    )
    op.create_table(
        "calibration_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("birth_profiles.id")),
        sa.Column("event_id", sa.String), sa.Column("domain", sa.String),
        sa.Column("predicted_event", sa.Text),
        sa.Column("predicted_window_start", sa.String),
        sa.Column("predicted_window_end", sa.String),
        sa.Column("user_feedback", sa.String), sa.Column("actual_date", sa.String),
        sa.Column("matched", sa.Boolean), sa.Column("rules_evaluated", sa.Text),
        sa.Column("pillars_json", sa.Text), sa.Column("chat_text", sa.Text),
        sa.Column("calc_fingerprint", sa.String), sa.Column("asked", sa.Boolean),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("title", sa.String), sa.Column("state", sa.String),
        sa.Column("pending_event_id", sa.String),
        sa.Column("created_at", sa.DateTime), sa.Column("updated_at", sa.DateTime),
    )
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("conversation_id", sa.Integer, sa.ForeignKey("conversations.id")),
        sa.Column("role", sa.String), sa.Column("content", sa.Text),
        sa.Column("kind", sa.String), sa.Column("meta_json", sa.Text),
        sa.Column("created_at", sa.DateTime),
    )


def downgrade() -> None:
    for t in ("messages", "conversations", "calibration_events", "birth_profiles", "users"):
        op.drop_table(t)
