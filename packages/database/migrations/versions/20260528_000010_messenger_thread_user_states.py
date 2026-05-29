"""add messenger thread user state table

Revision ID: 20260528_000010
Revises: 20260528_000009
Create Date: 2026-05-28 00:00:10
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260528_000010"
down_revision = "20260528_000009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "messenger_thread_user_states",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("thread_key", sa.Text(), nullable=False),
        sa.Column(
            "last_read_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "org_id",
            "thread_key",
            "user_id",
            name="messenger_thread_user_states_org_thread_user_idx",
        ),
    )
    op.create_index(
        "messenger_thread_user_states_org_user_idx",
        "messenger_thread_user_states",
        ["org_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "messenger_thread_user_states_org_user_idx",
        table_name="messenger_thread_user_states",
    )
    op.drop_table("messenger_thread_user_states")
