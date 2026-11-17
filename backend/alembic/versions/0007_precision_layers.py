"""Prediction records gain a per-filter verdict trail.

The precision layer (astro/precision.py) records what each filter said —
core pillars, yogini, sudarshana, kakshya timing, magnitude, ithasala,
eclipse — so follow-up outcomes can later be compared against filtered
and unfiltered windows.

Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("prediction_records", sa.Column("layer_verdicts", sa.Text, nullable=True))


def downgrade() -> None:
    op.drop_column("prediction_records", "layer_verdicts")
