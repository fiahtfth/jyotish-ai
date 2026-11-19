"""Store permission for shared profiles and optional forecast follow-ups.

Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("prediction_followups", sa.Boolean, nullable=False, server_default=sa.false()))
    op.add_column("birth_profiles", sa.Column("permission_confirmed_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("birth_profiles") as batch:
        batch.drop_column("permission_confirmed_at")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("prediction_followups")
