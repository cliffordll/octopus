"""Add issue comment request idempotency.

Revision ID: 20260825_000029
Revises: 20260817_000027
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260825_000029"
down_revision = "20260817_000027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("issue_comments")}
    if "request_id" not in columns:
        op.add_column(
            "issue_comments",
            sa.Column("request_id", sa.String(length=128), nullable=True),
        )
    indexes = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("issue_comments")
        if isinstance(index.get("name"), str)
    }
    if "issue_comments_org_issue_request_id_uq" not in indexes:
        op.create_index(
            "issue_comments_org_issue_request_id_uq",
            "issue_comments",
            ["org_id", "issue_id", "request_id"],
            unique=True,
            sqlite_where=sa.text("request_id is not null"),
            postgresql_where=sa.text("request_id is not null"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = {
        index["name"]
        for index in inspector.get_indexes("issue_comments")
        if isinstance(index.get("name"), str)
    }
    if "issue_comments_org_issue_request_id_uq" in indexes:
        op.drop_index(
            "issue_comments_org_issue_request_id_uq",
            table_name="issue_comments",
        )
    columns = {
        column["name"] for column in sa.inspect(bind).get_columns("issue_comments")
    }
    if "request_id" in columns:
        op.drop_column("issue_comments", "request_id")
