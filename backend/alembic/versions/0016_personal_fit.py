"""personal_fit on birth_profiles (core-engine chart check result).

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("birth_profiles", sa.Column("personal_fit", sa.String, nullable=True))


def downgrade() -> None:
    op.drop_column("birth_profiles", "personal_fit")
