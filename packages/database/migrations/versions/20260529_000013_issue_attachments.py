from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260529_000013"
down_revision = "20260529_000012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "issue_attachments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("issue_id", sa.String(length=36), nullable=False),
        sa.Column("issue_comment_id", sa.String(length=36), nullable=True),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("usage", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["issue_comment_id"], ["issue_comments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "issue_attachments_company_issue_idx",
        "issue_attachments",
        ["org_id", "issue_id"],
    )
    op.create_index(
        "issue_attachments_comment_idx", "issue_attachments", ["issue_comment_id"]
    )
    op.create_index("issue_attachments_asset_idx", "issue_attachments", ["asset_id"])


def downgrade() -> None:
    op.drop_index("issue_attachments_asset_idx", table_name="issue_attachments")
    op.drop_index("issue_attachments_comment_idx", table_name="issue_attachments")
    op.drop_index("issue_attachments_company_issue_idx", table_name="issue_attachments")
    op.drop_table("issue_attachments")
