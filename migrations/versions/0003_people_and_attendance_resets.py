"""Add custom person types, age, and recoverable attendance deletions."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("people", sa.Column("custom_type", sa.String(80), nullable=True))
    op.add_column("people", sa.Column("age", sa.Integer(), nullable=True))
    op.create_table(
        "attendance_deletions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("records", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(160), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("restored_at", sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table("attendance_deletions")
    op.drop_column("people", "age")
    op.drop_column("people", "custom_type")
