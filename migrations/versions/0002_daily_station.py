"""Add a shared daily attendance station."""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("attendance_sessions", sa.Column("station_day", sa.Date(), nullable=True))
    op.create_index("ix_station_day", "attendance_sessions", ["station_day"], unique=True)


def downgrade():
    op.drop_index("ix_station_day", table_name="attendance_sessions")
    op.drop_column("attendance_sessions", "station_day")
