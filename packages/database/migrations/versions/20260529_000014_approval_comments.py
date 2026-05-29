from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260529_000014"
down_revision = "20260529_000013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_comments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("approval_id", sa.String(length=36), nullable=False),
        sa.Column("author_agent_id", sa.String(length=36), nullable=True),
        sa.Column("author_user_id", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["approval_id"], ["approvals.id"]),
        sa.ForeignKeyConstraint(["author_agent_id"], ["agents.id"]),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("approval_comments_company_idx", "approval_comments", ["org_id"])
    op.create_index(
        "approval_comments_approval_idx", "approval_comments", ["approval_id"]
    )
    op.create_index(
        "approval_comments_approval_created_idx",
        "approval_comments",
        ["approval_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "approval_comments_approval_created_idx", table_name="approval_comments"
    )
    op.drop_index("approval_comments_approval_idx", table_name="approval_comments")
    op.drop_index("approval_comments_company_idx", table_name="approval_comments")
    op.drop_table("approval_comments")
