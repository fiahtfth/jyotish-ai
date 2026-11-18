"""Birth profiles record how local time became UTC, and the calculation preset.

time_basis (zone|lmt|manual), manual offset, DST fold, the offset source and
warnings produced when it was resolved, the tz database version, and the
calc_preset (default|drik|jh) the chart is computed under.

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("birth_profiles", sa.Column("time_basis", sa.String, nullable=False,
                                              server_default="zone"))
    op.add_column("birth_profiles", sa.Column("utc_offset_manual", sa.Float, nullable=True))
    op.add_column("birth_profiles", sa.Column("dst_fold", sa.Integer, nullable=True))
    op.add_column("birth_profiles", sa.Column("offset_source", sa.String, nullable=True))
    op.add_column("birth_profiles", sa.Column("tz_warnings", sa.Text, nullable=True))
    op.add_column("birth_profiles", sa.Column("tzdb_version", sa.String, nullable=True))
    op.add_column("birth_profiles", sa.Column("calc_preset", sa.String, nullable=False,
                                              server_default="default"))


def downgrade() -> None:
    with op.batch_alter_table("birth_profiles") as batch:
        for col in ("calc_preset", "tzdb_version", "tz_warnings", "offset_source",
                    "dst_fold", "utc_offset_manual", "time_basis"):
            batch.drop_column(col)
