"""Age confirmation, AI-consent withdrawal, optional gender and current residence.

Revision ID: 0014
Revises: 0013
"""
from alembic import op
import sqlalchemy as sa

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

_PROFILE_COLUMNS = (("gender", sa.String), ("residence_name", sa.String), ("residence_state", sa.String),
                    ("residence_country", sa.String), ("residence_lat", sa.Float),
                    ("residence_lon", sa.Float), ("residence_timezone_name", sa.String))


def upgrade() -> None:
    op.add_column("users", sa.Column("age_confirmed_at", sa.DateTime, nullable=True))
    op.add_column("users", sa.Column("ai_withdrawn_at", sa.DateTime, nullable=True))
    for name, kind in _PROFILE_COLUMNS:
        op.add_column("birth_profiles", sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("birth_profiles") as batch:
        for name, _ in reversed(_PROFILE_COLUMNS):
            batch.drop_column(name)
    with op.batch_alter_table("users") as batch:
        batch.drop_column("ai_withdrawn_at")
        batch.drop_column("age_confirmed_at")
