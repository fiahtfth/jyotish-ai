"""Frozen prediction protocol; old rows remain explicitly legacy."""
from alembic import op
import sqlalchemy as sa
revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    for name, typ in [("protocol", sa.String()), ("forecast", sa.String()),
                      ("event_type", sa.String()), ("success_criteria", sa.Text()), ("snapshot_json", sa.Text()), ("event_date", sa.Date())]:
        op.add_column("prediction_records", sa.Column(name, typ, nullable=True))


def downgrade():
    for name in ("event_date", "snapshot_json", "success_criteria", "event_type", "forecast", "protocol"):
        op.drop_column("prediction_records", name)
