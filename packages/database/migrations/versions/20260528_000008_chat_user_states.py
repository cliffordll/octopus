"""add chat user state table

Revision ID: 20260528_000008
Revises: 20260528_000007
Create Date: 2026-05-28 00:00:08
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260528_000008"
down_revision = "20260528_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_conversation_user_states",
        sa.Column("id", sa.String(length=36), primary_key=True, nullable=False),
        sa.Column(
            "org_id",
            sa.String(length=36),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "conversation_id",
            sa.String(length=36),
            sa.ForeignKey("chat_conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column(
            "last_read_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("pinned_at", sa.DateTime(timezone=True), nullable=True),
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
            "conversation_id",
            "user_id",
            name="chat_conversation_user_states_org_conversation_user_idx",
        ),
    )
    op.create_index(
        "chat_conversation_user_states_org_conversation_idx",
        "chat_conversation_user_states",
        ["org_id", "conversation_id"],
    )
    op.create_index(
        "chat_conversation_user_states_org_user_idx",
        "chat_conversation_user_states",
        ["org_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "chat_conversation_user_states_org_user_idx",
        table_name="chat_conversation_user_states",
    )
    op.drop_index(
        "chat_conversation_user_states_org_conversation_idx",
        table_name="chat_conversation_user_states",
    )
    op.drop_table("chat_conversation_user_states")
