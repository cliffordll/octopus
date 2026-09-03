from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol

from packages.database.queries.heartbeat import transition_run_to_terminal
from packages.database.schema import Agent as AgentRow
from packages.database.schema import HeartbeatRun as HeartbeatRunRow
from packages.database.schema import Issue as IssueRow
from packages.shared.constants.heartbeat import HeartbeatRunStatus
from packages.shared.types.heartbeat import HeartbeatRun
from server.identity.system_access import SystemOperationAccess

if TYPE_CHECKING:
    from .issue_completion import IssueCompletionResult
    from .parent_closeout_governance import ParentCloseoutResult


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

    async def _queue_issue_review_wakeup_after_success(
        self, final: HeartbeatRunRow, issue: IssueRow
    ) -> None: ...

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
        self._system_access = SystemOperationAccess()

    def _authorize(self, run: HeartbeatRunRow) -> None:
        self._system_access.require(
            system_id="run_finalization",
            org_id=run.org_id,
            permission="runs:finalize",
            reason="Finalize Run state and terminal effects",
            entity_type="run",
            entity_id=run.id,
        )

    async def transition(
        self,
        run_id: str,
        status: HeartbeatRunStatus,
        values: dict[str, Any],
        *,
        expected_statuses: Sequence[str] = ("running",),
        expected_owner_token: str | None = None,
    ) -> HeartbeatRunRow | None:
        from packages.database.queries.heartbeat import get_run

        run = await get_run(self._host._session, run_id)
        if run is None:
            return None
        self._authorize(run)
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
        self._authorize(running)
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
        self._authorize(run)
        return await self._host._reconcile_terminal_effects_impl(
            run,
            result=result,
            sequence=sequence,
        )

    async def restore_system_blocked_issue_after_recovery(
        self, run: HeartbeatRunRow
    ) -> bool:
        self._authorize(run)
        return await self._host._restore_system_blocked_issue_after_recovery(run)

    async def finalize_parent_closeout(
        self, run: HeartbeatRunRow, issue: IssueRow
    ) -> "ParentCloseoutResult":
        self._authorize(run)
        from .parent_closeout_governance import ParentCloseoutGovernance

        result = await ParentCloseoutGovernance(
            self._host._session
        ).finalize_parent_output_request(run, issue)
        if result.completed:
            await self._host._session.refresh(issue)
            if issue.status == "in_review":
                await self._host._queue_issue_review_wakeup_after_success(run, issue)
        return result

    async def validate_parent_closeout(
        self, run: HeartbeatRunRow, issue: IssueRow
    ) -> "ParentCloseoutResult":
        """Validate policy evidence before the Run terminal CAS."""

        self._authorize(run)

        from .parent_closeout_governance import ParentCloseoutGovernance

        return await ParentCloseoutGovernance(
            self._host._session
        ).finalize_parent_output_request(run, issue, apply=False)

    async def finalize_issue_completion(
        self, run: HeartbeatRunRow, issue: IssueRow
    ) -> "IssueCompletionResult":
        self._authorize(run)
        from .issue_completion import IssueCompletionGovernance

        result = await IssueCompletionGovernance(self._host._session).validate(
            run, issue, apply=True
        )
        if result.completed:
            await self._host._session.refresh(issue)
            if issue.status == "in_review":
                await self._host._queue_issue_review_wakeup_after_success(run, issue)
        return result

    async def validate_issue_completion(
        self, run: HeartbeatRunRow, issue: IssueRow
    ) -> "IssueCompletionResult":
        self._authorize(run)
        from .issue_completion import IssueCompletionGovernance

        return await IssueCompletionGovernance(self._host._session).validate(
            run, issue, apply=False
        )

    async def block_failed_issue_completion(
        self, run: HeartbeatRunRow, issue: IssueRow
    ) -> bool:
        self._authorize(run)
        from .issue_completion import IssueCompletionGovernance

        return await IssueCompletionGovernance(
            self._host._session
        ).block_failed_request(run, issue)


class RunRecoveryService:
    """Own evidence-based recovery decisions for persisted Run state."""

    def __init__(self, host: RunLifecycleHost) -> None:
        self._host = host
        self._system_access = SystemOperationAccess()

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

    def authorize(self, run: HeartbeatRunRow) -> None:
        self._system_access.require(
            system_id="run_recovery",
            org_id=run.org_id,
            permission="runs:recover",
            reason="Recover persisted Run execution state",
            entity_type="run",
            entity_id=run.id,
        )
