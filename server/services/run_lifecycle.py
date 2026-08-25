from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from packages.database.queries.heartbeat import transition_run_to_terminal
from packages.database.schema import Agent as AgentRow
from packages.database.schema import HeartbeatRun as HeartbeatRunRow
from packages.shared.constants.heartbeat import HeartbeatRunStatus
from packages.shared.types.heartbeat import HeartbeatRun


class RunLifecycleHost(Protocol):
    """Narrow host contract used by lifecycle services during extraction."""

    _session: Any

    async def _complete_finalized_run_impl(
        self,
        *,
        agent: AgentRow,
        running: HeartbeatRunRow,
        final: HeartbeatRunRow,
        final_status: HeartbeatRunStatus,
        result: Any,
        sequence: int,
    ) -> HeartbeatRunRow: ...

    async def _reconcile_terminal_effects_impl(
        self,
        run: HeartbeatRunRow,
        *,
        result: Any | None = None,
        sequence: int | None = None,
    ) -> HeartbeatRunRow: ...

    async def _restore_system_blocked_issue_after_recovery(
        self, final: HeartbeatRunRow
    ) -> bool: ...

    async def _recover_orphaned_runs_impl(
        self,
        *,
        require_process_loss: bool = False,
        run_ids: set[str] | None = None,
    ) -> list[HeartbeatRun]: ...


class RunFinalizationService:
    """Own Run terminal CAS and idempotent terminal-effects orchestration."""

    def __init__(self, host: RunLifecycleHost) -> None:
        self._host = host

    async def transition(
        self,
        run_id: str,
        status: HeartbeatRunStatus,
        values: dict[str, Any],
        *,
        expected_statuses: Sequence[str] = ("running",),
        expected_owner_token: str | None = None,
    ) -> HeartbeatRunRow | None:
        return await transition_run_to_terminal(
            self._host._session,
            run_id,
            status,
            values,
            expected_statuses=expected_statuses,
            expected_owner_token=expected_owner_token,
        )

    async def complete(
        self,
        *,
        agent: AgentRow,
        running: HeartbeatRunRow,
        final: HeartbeatRunRow,
        final_status: HeartbeatRunStatus,
        result: Any,
        sequence: int,
    ) -> HeartbeatRunRow:
        return await self._host._complete_finalized_run_impl(
            agent=agent,
            running=running,
            final=final,
            final_status=final_status,
            result=result,
            sequence=sequence,
        )

    async def reconcile(
        self,
        run: HeartbeatRunRow,
        *,
        result: Any | None = None,
        sequence: int | None = None,
    ) -> HeartbeatRunRow:
        return await self._host._reconcile_terminal_effects_impl(
            run,
            result=result,
            sequence=sequence,
        )

    async def restore_system_blocked_issue_after_recovery(
        self, run: HeartbeatRunRow
    ) -> bool:
        return await self._host._restore_system_blocked_issue_after_recovery(run)


class RunRecoveryService:
    """Own evidence-based recovery decisions for persisted Run state."""

    def __init__(self, host: RunLifecycleHost) -> None:
        self._host = host

    async def recover(
        self,
        *,
        require_process_loss: bool = False,
        run_ids: set[str] | None = None,
    ) -> list[HeartbeatRun]:
        return await self._host._recover_orphaned_runs_impl(
            require_process_loss=require_process_loss,
            run_ids=run_ids,
        )
