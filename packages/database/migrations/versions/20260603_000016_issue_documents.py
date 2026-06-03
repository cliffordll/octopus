from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260603_000016"
down_revision = "20260602_000015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("latest_body", sa.Text(), nullable=False),
        sa.Column("latest_revision_id", sa.String(length=36), nullable=True),
        sa.Column("latest_revision_number", sa.Integer(), nullable=False),
        sa.Column("created_by_agent_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column("updated_by_agent_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_user_id", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["created_by_agent_id"], ["agents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(
            ["updated_by_agent_id"], ["agents.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "documents_company_updated_idx", "documents", ["org_id", "updated_at"]
    )
    op.create_index(
        "documents_company_created_idx", "documents", ["org_id", "created_at"]
    )

    op.create_table(
        "document_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("change_summary", sa.Text(), nullable=True),
        sa.Column("created_by_agent_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_user_id", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["created_by_agent_id"], ["agents.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "revision_number",
            name="document_revisions_document_revision_uq",
        ),
    )
    op.create_index(
        "document_revisions_company_document_created_idx",
        "document_revisions",
        ["org_id", "document_id", "created_at"],
    )

    op.create_table(
        "issue_documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("org_id", sa.String(length=36), nullable=False),
        sa.Column("issue_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
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
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["org_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "org_id",
            "issue_id",
            "key",
            name="issue_documents_company_issue_key_uq",
        ),
        sa.UniqueConstraint("document_id", name="issue_documents_document_uq"),
    )
    op.create_index(
        "issue_documents_company_issue_updated_idx",
        "issue_documents",
        ["org_id", "issue_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "issue_documents_company_issue_updated_idx", table_name="issue_documents"
    )
    op.drop_table("issue_documents")
    op.drop_index(
        "document_revisions_company_document_created_idx",
        table_name="document_revisions",
    )
    op.drop_table("document_revisions")
    op.drop_index("documents_company_created_idx", table_name="documents")
    op.drop_index("documents_company_updated_idx", table_name="documents")
    op.drop_table("documents")
