"""add atomic execution workspace operation leases

Revision ID: 20260630_000025
Revises: 20260619_000024
Create Date: 2026-06-30 00:00:25
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260630_000025"
down_revision = "20260619_000024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_operations",
        sa.Column("lease_key", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "workspace_operations_active_lease_key_uq",
        "workspace_operations",
        ["lease_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "workspace_operations_active_lease_key_uq",
        table_name="workspace_operations",
    )
    op.drop_column("workspace_operations", "lease_key")
