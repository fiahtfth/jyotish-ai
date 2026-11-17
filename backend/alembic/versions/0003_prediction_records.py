"""Prediction records for outcome follow-ups.

Revision ID: 0003
Revises: 0002
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prediction_records",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("birth_profiles.id"), nullable=False),
        sa.Column("domain", sa.String), sa.Column("question", sa.Text),
        sa.Column("window_start", sa.Date), sa.Column("window_end", sa.Date),
        sa.Column("convergence", sa.String),
        sa.Column("created_at", sa.DateTime),
        sa.Column("followup_asked_at", sa.DateTime, nullable=True),
        sa.Column("outcome", sa.String, nullable=True),
        sa.Column("outcome_at", sa.DateTime, nullable=True),
    )
    op.create_index("ix_prediction_records_profile_id", "prediction_records", ["profile_id"])


def downgrade() -> None:
    op.drop_table("prediction_records")
