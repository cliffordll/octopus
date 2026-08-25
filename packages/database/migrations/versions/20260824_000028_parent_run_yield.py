"""Persist parent Run yield requests.

Revision ID: 20260824_000028
Revises: 20260817_000027
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_000028"
down_revision = "20260817_000027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("heartbeat_runs")}
    if "yield_requested_at" not in columns:
        op.add_column(
            "heartbeat_runs",
            sa.Column("yield_requested_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("heartbeat_runs")}
    if "yield_requested_at" in columns:
        op.drop_column("heartbeat_runs", "yield_requested_at")
