"""Record service terms acceptance without fabricating acceptance for old accounts."""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("terms_version", sa.String, nullable=True))
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime, nullable=True))


def downgrade() -> None:
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "terms_version")
