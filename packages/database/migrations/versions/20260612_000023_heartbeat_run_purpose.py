"""add heartbeat run purpose

Revision ID: 20260612_000023
Revises: 20260612_000022
Create Date: 2026-06-12 00:00:23
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "20260612_000023"
down_revision = "20260612_000022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "heartbeat_runs",
        sa.Column(
            "run_purpose",
            sa.Text(),
            nullable=False,
            server_default="task_execution",
        ),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            """
            select id, invocation_source, context_snapshot
            from heartbeat_runs
            """
        )
    ).mappings()
    for row in rows:
        context = row["context_snapshot"]
        if isinstance(context, str):
            try:
                context = json.loads(context)
            except json.JSONDecodeError:
                context = None
        wake_reason = context.get("wakeReason") if isinstance(context, dict) else None
        purpose = (
            "closeout_followup"
            if wake_reason == "issue_passive_followup"
            else "review"
            if row["invocation_source"] == "review"
            else "heartbeat"
            if row["invocation_source"] == "timer"
            else "task_execution"
        )
        connection.execute(
            sa.text(
                """
                update heartbeat_runs
                set run_purpose = :purpose
                where id = :run_id
                """
            ),
            {"purpose": purpose, "run_id": row["id"]},
        )


def downgrade() -> None:
    op.drop_column("heartbeat_runs", "run_purpose")
