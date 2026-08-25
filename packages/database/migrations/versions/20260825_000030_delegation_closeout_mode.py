"""Add delegated child batch provenance and closeout mode.

Revision ID: 20260825_000030
Revises: 20260825_000029
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260825_000030"
down_revision = "20260825_000029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("issues")}
    if "closeout_mode" not in columns:
        op.add_column(
            "issues",
            sa.Column("closeout_mode", sa.Text(), nullable=True),
        )
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("issues")
        if isinstance(index.get("name"), str)
    }
    if "issues_delegation_batch_idx" not in indexes:
        op.create_index(
            "issues_delegation_batch_idx",
            "issues",
            ["org_id", "parent_id", "origin_kind", "origin_run_id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {
        index["name"]
        for index in inspector.get_indexes("issues")
        if isinstance(index.get("name"), str)
    }
    if "issues_delegation_batch_idx" in indexes:
        op.drop_index("issues_delegation_batch_idx", table_name="issues")
    columns = {column["name"] for column in sa.inspect(bind).get_columns("issues")}
    if "closeout_mode" in columns:
        op.drop_column("issues", "closeout_mode")
