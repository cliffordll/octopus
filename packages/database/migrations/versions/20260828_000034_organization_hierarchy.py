"""Add unified organization reporting relationships.

Revision ID: 20260828_000034
Revises: 20260827_000033
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260828_000034"
down_revision = "20260827_000033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("roles") as batch_op:
        batch_op.add_column(
            sa.Column("reports_to", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "roles_reports_to_fkey", "roles", ["reports_to"], ["id"]
        )
    op.create_index(
        "roles_scope_reports_to_idx",
        "roles",
        ["scope_type", "scope_id", "reports_to"],
    )


def downgrade() -> None:
    op.drop_index("roles_scope_reports_to_idx", table_name="roles")
    with op.batch_alter_table("roles") as batch_op:
        batch_op.drop_constraint("roles_reports_to_fkey", type_="foreignkey")
        batch_op.drop_column("reports_to")
