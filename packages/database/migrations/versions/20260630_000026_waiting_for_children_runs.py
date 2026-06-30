"""backfill delegated parent runs as waiting for children

Revision ID: 20260630_000026
Revises: 20260630_000025
Create Date: 2026-06-30 00:00:26
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260630_000026"
down_revision = "20260630_000025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE heartbeat_runs
            SET status = 'waiting_for_children',
                error = NULL,
                error_code = NULL
            WHERE status = 'succeeded'
              AND EXISTS (
                  SELECT 1
                  FROM activity_log
                  WHERE activity_log.run_id = heartbeat_runs.id
                    AND activity_log.action = 'issue.waiting_for_children'
              )
            """
        )
    )


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE heartbeat_runs
            SET status = 'succeeded'
            WHERE status = 'waiting_for_children'
              AND EXISTS (
                  SELECT 1
                  FROM activity_log
                  WHERE activity_log.run_id = heartbeat_runs.id
                    AND activity_log.action = 'issue.waiting_for_children'
              )
            """
        )
    )
