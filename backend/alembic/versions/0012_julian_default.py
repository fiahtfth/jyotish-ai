"""Retain the chosen year convention for profiles created before the new default.

Revision ID: 0012
Revises: 0011
"""
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE birth_profiles SET calc_preset = 'legacy_tropical' WHERE calc_preset = 'default'")


def downgrade() -> None:
    op.execute("UPDATE birth_profiles SET calc_preset = 'default' WHERE calc_preset = 'legacy_tropical'")
