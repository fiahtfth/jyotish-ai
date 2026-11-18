"""Allow readings for profiles previously blocked by the opening checks."""
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE birth_profiles SET predictions_allowed = TRUE "
               "WHERE calibration_state IN ('uncalibrated', 'insufficient_history')")


def downgrade():
    op.execute("UPDATE birth_profiles SET predictions_allowed = FALSE "
               "WHERE calibration_state IN ('uncalibrated', 'insufficient_history', 'skipped')")
    op.execute("UPDATE birth_profiles SET calibration_state = 'pending' WHERE calibration_state = 'skipped'")
