"""Replace delegated closeout mode with a structured closeout policy.

Revision ID: 20260826_000031
Revises: 20260825_000030
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260826_000031"
down_revision = "20260825_000030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("issues")}
    if "closeout_policy" not in columns:
        op.add_column(
            "issues",
            sa.Column("closeout_policy", sa.JSON(), nullable=True),
        )
    if "closeout_mode" in columns:
        op.drop_column("issues", "closeout_mode")


def downgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("issues")}
    if "closeout_mode" not in columns:
        op.add_column(
            "issues",
            sa.Column("closeout_mode", sa.Text(), nullable=True),
        )
    if "closeout_policy" in columns:
        op.drop_column("issues", "closeout_policy")
