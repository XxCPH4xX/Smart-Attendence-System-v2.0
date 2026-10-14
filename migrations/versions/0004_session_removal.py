"""Allow sessions to be removed without deleting their attendance history."""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("attendance_sessions", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.drop_index("ix_station_day", table_name="attendance_sessions")
    op.create_index(
        "ix_station_day",
        "attendance_sessions",
        ["station_day"],
        unique=True,
        sqlite_where=sa.text("archived_at IS NULL"),
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade():
    duplicate = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT station_day FROM attendance_sessions WHERE station_day IS NOT NULL "
                "GROUP BY station_day HAVING COUNT(*) > 1 LIMIT 1"
            )
        )
        .first()
    )
    if duplicate:
        raise RuntimeError("Cannot downgrade while removed and active stations share a date")
    op.drop_index("ix_station_day", table_name="attendance_sessions")
    op.create_index("ix_station_day", "attendance_sessions", ["station_day"], unique=True)
    op.drop_column("attendance_sessions", "archived_at")
