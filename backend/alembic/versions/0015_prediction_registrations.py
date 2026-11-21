"""Immutable pre-registration of each saved prediction (outcome tracking).

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prediction_registrations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("prediction_id", sa.Integer, sa.ForeignKey("prediction_records.id"),
                  nullable=False, unique=True),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("payload_sha256", sa.String, nullable=False),
        sa.Column("created_at", sa.DateTime),
    )


def downgrade() -> None:
    op.drop_table("prediction_registrations")
