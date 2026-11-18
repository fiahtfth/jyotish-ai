"""Dated life milestones and rectification bookkeeping.

Revision ID: 0004
Revises: 0003
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("birth_profiles", sa.Column("rectification_attempted", sa.Boolean,
                                              nullable=False, server_default=sa.false()))
    op.add_column("birth_profiles", sa.Column("milestone_search_done", sa.Boolean,
                                              nullable=False, server_default=sa.false()))
    # profiles already rectified before this revision count as attempted
    op.execute("UPDATE birth_profiles SET rectification_attempted = "
               + ("true" if op.get_bind().dialect.name == "postgresql" else "1")
               + " WHERE rectified_from IS NOT NULL")
    op.create_table(
        "user_milestones",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile_id", sa.Integer, sa.ForeignKey("birth_profiles.id"), nullable=False),
        sa.Column("domain", sa.String, nullable=True),
        sa.Column("description", sa.Text),
        sa.Column("year", sa.Integer, nullable=False),
        sa.Column("month", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_index("ix_user_milestones_profile_id", "user_milestones", ["profile_id"])


def downgrade() -> None:
    op.drop_table("user_milestones")
    with op.batch_alter_table("birth_profiles") as b:
        b.drop_column("milestone_search_done")
        b.drop_column("rectification_attempted")
