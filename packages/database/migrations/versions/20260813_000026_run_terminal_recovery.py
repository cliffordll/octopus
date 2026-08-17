"""add recoverable run terminal effects and execution leases

Revision ID: 20260813_000026
Revises: 20260701_000025
Create Date: 2026-08-13 00:00:26
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260813_000026"
down_revision = "20260701_000025"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {
        name
        for index in inspector.get_indexes(table_name)
        if isinstance(name := index["name"], str)
    }


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name not in _column_names(table_name):
        op.add_column(table_name, column)


def _clear_duplicate_wakeup_idempotency_keys() -> None:
    wakeups = sa.table(
        "agent_wakeup_requests",
        sa.column("id", sa.String()),
        sa.column("org_id", sa.String()),
        sa.column("agent_id", sa.String()),
        sa.column("idempotency_key", sa.Text()),
        sa.column("requested_at", sa.DateTime(timezone=True)),
    )
    rows = op.get_bind().execute(
        sa.select(
            wakeups.c.id,
            wakeups.c.org_id,
            wakeups.c.agent_id,
            wakeups.c.idempotency_key,
        )
        .where(wakeups.c.idempotency_key.is_not(None))
        .order_by(
            wakeups.c.org_id,
            wakeups.c.agent_id,
            wakeups.c.idempotency_key,
            wakeups.c.requested_at.desc(),
            wakeups.c.id.desc(),
        )
    )
    retained_keys: set[tuple[str, str, str]] = set()
    for row in rows:
        scoped_key = (row.org_id, row.agent_id, row.idempotency_key)
        if scoped_key not in retained_keys:
            retained_keys.add(scoped_key)
            continue
        op.get_bind().execute(
            wakeups.update().where(wakeups.c.id == row.id).values(idempotency_key=None)
        )


def upgrade() -> None:
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column("process_exited_at", sa.DateTime(timezone=True), nullable=True),
    )
    _add_column_if_missing(
        "heartbeat_runs", sa.Column("execution_owner_token", sa.Text(), nullable=True)
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column(
            "execution_lease_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column(
            "terminal_effects_pending",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    _add_column_if_missing(
        "heartbeat_runs", sa.Column("terminal_effects_json", sa.JSON(), nullable=True)
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column("terminal_effects_completed_json", sa.JSON(), nullable=True),
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column("terminal_effects_dead_lettered_json", sa.JSON(), nullable=True),
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column("terminal_effects_attempts_json", sa.JSON(), nullable=True),
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column(
            "terminal_effects_next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column(
            "terminal_effects_dead_lettered_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column("terminal_effects_claim_token", sa.Text(), nullable=True),
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column(
            "terminal_effects_claimed_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column(
            "terminal_effects_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    _add_column_if_missing(
        "heartbeat_runs",
        sa.Column("terminal_effects_last_error", sa.Text(), nullable=True),
    )
    if "heartbeat_runs_status_execution_lease_created_idx" not in _index_names(
        "heartbeat_runs"
    ):
        op.create_index(
            "heartbeat_runs_status_execution_lease_created_idx",
            "heartbeat_runs",
            ["status", "execution_lease_expires_at", "created_at"],
        )

    _add_column_if_missing(
        "heartbeat_run_events",
        sa.Column("idempotency_key", sa.Text(), nullable=True),
    )
    if "heartbeat_run_events_run_idempotency_key_uq" not in _index_names(
        "heartbeat_run_events"
    ):
        op.create_index(
            "heartbeat_run_events_run_idempotency_key_uq",
            "heartbeat_run_events",
            ["run_id", "idempotency_key"],
            unique=True,
            postgresql_where=sa.text("idempotency_key is not null"),
            sqlite_where=sa.text("idempotency_key is not null"),
        )
    if "agent_wakeup_requests_company_agent_idempotency_key_uq" not in _index_names(
        "agent_wakeup_requests"
    ):
        _clear_duplicate_wakeup_idempotency_keys()
        op.create_index(
            "agent_wakeup_requests_company_agent_idempotency_key_uq",
            "agent_wakeup_requests",
            ["org_id", "agent_id", "idempotency_key"],
            unique=True,
            postgresql_where=sa.text("idempotency_key is not null"),
            sqlite_where=sa.text("idempotency_key is not null"),
        )


def downgrade() -> None:
    op.drop_index(
        "agent_wakeup_requests_company_agent_idempotency_key_uq",
        table_name="agent_wakeup_requests",
    )
    op.drop_index(
        "heartbeat_run_events_run_idempotency_key_uq",
        table_name="heartbeat_run_events",
    )
    op.drop_column("heartbeat_run_events", "idempotency_key")

    op.drop_index(
        "heartbeat_runs_status_execution_lease_created_idx",
        table_name="heartbeat_runs",
    )
    for column in (
        "terminal_effects_last_error",
        "terminal_effects_attempt_count",
        "terminal_effects_claimed_at",
        "terminal_effects_claim_token",
        "terminal_effects_dead_lettered_at",
        "terminal_effects_next_attempt_at",
        "terminal_effects_attempts_json",
        "terminal_effects_dead_lettered_json",
        "terminal_effects_completed_json",
        "terminal_effects_json",
        "terminal_effects_pending",
        "execution_lease_expires_at",
        "execution_owner_token",
        "process_exited_at",
    ):
        op.drop_column("heartbeat_runs", column)
