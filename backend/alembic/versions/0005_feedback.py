"""Tester feedback: per-message thumbs and free-text problem reports.

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_feedback",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("message_id", sa.Integer, sa.ForeignKey("messages.id"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rating", sa.Integer, nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", sa.DateTime),
        sa.UniqueConstraint("message_id", "user_id", name="uq_message_feedback_msg_user"),
    )
    op.create_index("ix_message_feedback_message_id", "message_feedback", ["message_id"])
    op.create_index("ix_message_feedback_user_id", "message_feedback", ["user_id"])
    op.create_table(
        "problem_reports",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("context_json", sa.Text),
        sa.Column("created_at", sa.DateTime),
    )
    op.create_index("ix_problem_reports_user_id", "problem_reports", ["user_id"])


def downgrade() -> None:
    op.drop_table("problem_reports")
    op.drop_table("message_feedback")
