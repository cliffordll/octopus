"""separate heartbeat timer checks from run activity

Revision ID: 20260817_000027
Revises: 20260813_000026
Create Date: 2026-08-17 00:00:27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260817_000027"
down_revision = "20260813_000026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("agents")}
    if "last_heartbeat_check_at" not in columns:
        op.add_column(
            "agents",
            sa.Column(
                "last_heartbeat_check_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("agents")}
    if "last_heartbeat_check_at" in columns:
        op.drop_column("agents", "last_heartbeat_check_at")
