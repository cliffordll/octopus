from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
import logging
import os
from pathlib import Path
from typing import Any, ClassVar, cast

import psutil
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from packages.database.clients import enable_write_transactions
from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import (
    advance_agent_heartbeat_check,
    get_agent_by_id,
    list_org_agents,
    update_agent,
)
from packages.database.queries.agent_state import (
    create_runtime_state,
    get_runtime_state,
    update_runtime_state,
)
from packages.database.queries.issues import (
    get_issue_by_id,
    list_agent_actionable_heartbeat_issues,
    update_issue,
)
from packages.database.queries.agent_skills import list_enabled_skill_keys
from packages.database.queries.heartbeat import (
    append_run_event,
    claim_expired_run_execution,
    claim_run_terminal_effects,
    claim_due_wakeup_request,
    claim_queued_run,
    complete_run_terminal_effects,
    create_run,
    create_wakeup_request_idempotent,
    get_run,
    get_wakeup_by_idempotency_key,
    has_active_agent_run,
    has_active_timer_run,
    list_pending_runless_wakeup_requests,
    list_queued_agent_ids,
    list_queued_runs,
    list_due_wakeup_request_ids,
    list_run_events,
    list_running_run_ids,
    list_runs,
    list_runs_by_status,
    list_runs_with_pending_terminal_effects,
    list_wakeup_requests_by_status,
    renew_run_execution_lease,
    update_run,
    update_wakeup_request,
    fail_run_terminal_effects,
)
from packages.database.schema import (
    AgentWakeupRequest as AgentWakeupRequestRow,
    Agent as AgentRow,
    HeartbeatRun as HeartbeatRunRow,
    HeartbeatRunEvent as HeartbeatRunEventRow,
    Issue as IssueRow,
    IssueWorkProduct,
    ActivityLog,
)
from packages.runtimes import (
    RuntimeExecutionContext,
    RuntimeExecutionResult,
    get_runtime_adapter,
)
from packages.shared.constants.heartbeat import (
    AGENT_RUN_CONCURRENCY_DEFAULT,
    AGENT_RUN_CONCURRENCY_MAX,
    AGENT_RUN_CONCURRENCY_MIN,
    HEARTBEAT_INTERVAL_DEFAULT_SEC,
    HeartbeatInvocationSource,
    HeartbeatRunPurpose,
    HeartbeatRunStatus,
    WakeupTriggerDetail,
)
from packages.shared.types.heartbeat import (
    HeartbeatRun,
    HeartbeatRunEvent,
    WakeAgentPayload,
)

from packages.database.clients.cleanup import (
    close_session_shielded as _shielded_session_close,
    rollback_session_shielded as _shielded_session_rollback,
)

from .agents import AgentConflictError, prepare_agent_runtime_config
from .costs import CostService
from .issue_hierarchy import IssueHierarchyPolicy
from .logs import (
    LogReadResult,
    append_local_file_log,
    finalize_local_file_log,
    read_local_file_log,
)
from .runtime_providers import inject_runtime_provider_config
from .run_lifecycle import RunFinalizationService, RunRecoveryService
from .parent_continuation import ParentContinuationCoordinator
from .parent_closeout_governance import ParentCloseoutGovernance
from .delegation_closeout import DelegationBatchStore
from .workspace_paths import ensure_octopus_run_log_dir
from .workspace_access import workspace_access_strategy
from .workspaces import (
    WorkspaceService,
    _expected_work_product_paths,
)

logger = logging.getLogger(__name__)

LOCAL_CHILD_PROCESS_RUNTIMES = {
    "process",
    "claude_local",
    "codex_local",
    "gemini_local",
    "opencode_local",
    "pi_local",
    "hermes_local",
}

# Only adapters that report stdout/stderr incrementally can safely use an
# output-silence watchdog by default. Other adapters may opt in explicitly.
STREAMING_LOCAL_RUNTIMES = {"opencode_local"}

ISSUE_PASSIVE_FOLLOWUP_REASON = "issue_passive_followup"
ISSUE_PASSIVE_FOLLOWUP_WAKE_SOURCE = "passive_issue_followup"
ISSUE_PASSIVE_FOLLOWUP_FAILURE_REASON = "missing_closure"
ISSUE_PASSIVE_FOLLOWUP_MAX_ATTEMPTS = 2
ISSUE_PASSIVE_FOLLOWUP_DELAY_ENV = "OCTOPUS_ISSUE_PASSIVE_FOLLOWUP_DELAY_SECONDS"
ISSUE_PASSIVE_FOLLOWUP_DELAY_DEFAULT_SECONDS = 30 * 60
RUN_RECOVERY_GRACE_SECONDS = 5 * 60
HUMAN_INTERVENTION_ACTOR_TYPES = {"board", "user"}
WAKEUP_TRIGGER_DETAIL_VALUES = {"manual", "ping", "callback", "system"}


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.AccessDenied:
        return True
    except (psutil.NoSuchProcess, psutil.ZombieProcess, ValueError):
        return False


def _terminate_verified_run_process_tree(
    pid: int, process_started_at: datetime | None
) -> bool:
    """Terminate a detached runtime tree only when PID start evidence matches."""

    if pid <= 0 or process_started_at is None:
        return False
    expected = process_started_at
    if expected.tzinfo is None:
        expected = expected.replace(tzinfo=UTC)
    try:
        process = psutil.Process(pid)
        actual = datetime.fromtimestamp(process.create_time(), tz=UTC)
        if abs((actual - expected).total_seconds()) > 10:
            return False
        processes = [*reversed(process.children(recursive=True)), process]
        for candidate in processes:
            with contextlib.suppress(psutil.NoSuchProcess, psutil.ZombieProcess):
                candidate.terminate()
        _, alive = psutil.wait_procs(processes, timeout=3)
        for candidate in alive:
            with contextlib.suppress(psutil.NoSuchProcess, psutil.ZombieProcess):
                candidate.kill()
        psutil.wait_procs(alive, timeout=3)
        return not _is_process_alive(pid)
    except (
        psutil.AccessDenied,
        psutil.NoSuchProcess,
        psutil.ZombieProcess,
        ValueError,
    ):
        return not _is_process_alive(pid)


def _issue_passive_followup_delay() -> timedelta:
    raw_value = os.environ.get(ISSUE_PASSIVE_FOLLOWUP_DELAY_ENV)
    if raw_value is None:
        return timedelta(seconds=ISSUE_PASSIVE_FOLLOWUP_DELAY_DEFAULT_SECONDS)
    try:
        seconds = max(0.0, float(raw_value))
    except ValueError:
        seconds = float(ISSUE_PASSIVE_FOLLOWUP_DELAY_DEFAULT_SECONDS)
    return timedelta(seconds=seconds)


def _run_purpose(
    invocation_source: str, context_snapshot: dict[str, Any] | None
) -> HeartbeatRunPurpose:
    context = context_snapshot if isinstance(context_snapshot, dict) else {}
    if context.get("wakeReason") == ISSUE_PASSIVE_FOLLOWUP_REASON:
        return "closeout_followup"
    if invocation_source == "review":
        return "review"
    if (
        invocation_source == "timer"
        or context.get("wakeReason") == "runtime_diagnostic"
    ):
        return "heartbeat"
    return "task_execution"


def _run_log_dir() -> Path:
    return ensure_octopus_run_log_dir()


def _database_log_fields(fields: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "logBytes" in fields:
        result["log_bytes"] = fields["logBytes"]
    if "logSha256" in fields:
        result["log_sha256"] = fields["logSha256"]
    if "logCompressed" in fields:
        result["log_compressed"] = fields["logCompressed"]
    return result


def _exception_message(exc: BaseException) -> str:
    message = str(exc).strip()
    return message or type(exc).__name__


class WorkspacePreparationError(RuntimeError):
    """Marks a failure that happened before the runtime adapter was invoked."""


class RunExecutionFinalizationError(RuntimeError):
    """Carries the original execution failure across a poisoned DB session."""

    def __init__(self, *, run_id: str, message: str, error_code: str) -> None:
        super().__init__(message)
        self.run_id = run_id
        self.error_code = error_code


class HeartbeatService:
    _DEFERRED_CONTEXT_KEY = "__deferredContextSnapshot"
    _RETRY_OF_RUN_KEY = "__retryOfRunId"
    _RETRY_PURPOSE_KEY = "__retryRunPurpose"
    _RETRY_PROCESS_LOSS_COUNT_KEY = "__retryProcessLossCount"
    PARENT_COORDINATION_GRACE_SECONDS = 120.0
    PARENT_ADAPTER_STOP_GRACE_SECONDS = 10.0
    RUNTIME_PROGRESS_INTERVAL_SECONDS = 15.0
    RUNTIME_NO_OUTPUT_TIMEOUT_SECONDS = 300.0
    _start_locks: ClassVar[dict[str, asyncio.Lock]] = {}
    _diagnostic_locks: ClassVar[dict[str, asyncio.Lock]] = {}
    _active_run_ids: ClassVar[dict[str, set[str]]] = {}
    _cancel_events: ClassVar[dict[str, asyncio.Event]] = {}

    def __init__(
        self,
        session: AsyncSession,
        *,
        commit_process_metadata: bool = False,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._session = session
        self._commit_process_metadata = commit_process_metadata
        self._session_factory = session_factory
        self.last_wakeup_reused = False

    @property
    def finalizer(self) -> RunFinalizationService:
        return RunFinalizationService(self)

    @property
    def recovery(self) -> RunRecoveryService:
        return RunRecoveryService(self)

    @property
    def parent_continuation(self) -> ParentContinuationCoordinator:
        return ParentContinuationCoordinator(self._session, self)

    @property
    def parent_closeout(self) -> ParentCloseoutGovernance:
        return ParentCloseoutGovernance(self._session)

    async def wakeup(
        self,
        agent_id: str,
        payload: WakeAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
        execute_immediately: bool = True,
    ) -> HeartbeatRun | None:
        self.last_wakeup_reused = False
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None:
            return None
        if agent.status in ("terminated", "pending_approval"):
            raise AgentConflictError("Agent is not invokable in its current state")
        policy = self._heartbeat_policy(agent)
        if payload.get("source", "on_demand") != "timer" and not policy["wakeOnDemand"]:
            await self._create_skipped_wakeup(
                agent,
                payload,
                actor_type=actor_type,
                actor_id=actor_id,
                error="heartbeat.wakeOnDemand.disabled",
            )
            return None
        from .budgets import BudgetService

        context = {
            **self._payload_context(payload.get("payload")),
            **self._payload_context_snapshot(payload.get("contextSnapshot")),
        }
        block = await BudgetService(self._session).get_invocation_block(
            agent.org_id,
            agent.id,
            project_id=cast(str | None, context.get("projectId")),
        )
        if block is not None:
            raise ValueError(block.reason)
        diagnostic = (
            payload.get("reason") == "runtime_diagnostic"
            or context.get("wakeReason") == "runtime_diagnostic"
        )
        if diagnostic:
            return await self._wakeup_runtime_diagnostic(
                agent,
                payload,
                actor_type=actor_type,
                actor_id=actor_id,
                execute_immediately=execute_immediately,
            )
        idempotency_key = payload.get("idempotencyKey")
        if idempotency_key:
            existing = await get_wakeup_by_idempotency_key(
                self._session, agent.id, idempotency_key
            )
            if existing is not None and existing.run_id:
                existing_run = await get_run(self._session, existing.run_id)
                if existing_run is not None:
                    self.last_wakeup_reused = True
                    return self._to_run(existing_run)
            if existing is not None and existing.status == "deferred_agent_paused":
                await update_wakeup_request(
                    self._session,
                    existing.id,
                    {"coalesced_count": existing.coalesced_count + 1},
                )
                return None
            if existing is not None and existing.status == "deferred_issue_execution":
                await update_wakeup_request(
                    self._session,
                    existing.id,
                    {"coalesced_count": existing.coalesced_count + 1},
                )
                return None
        if agent.status == "paused":
            await create_wakeup_request_idempotent(
                self._session,
                self._wakeup_values(
                    agent,
                    payload,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    status="deferred_agent_paused",
                ),
            )
            return None
        if await self._defer_issue_wakeup_if_locked(
            agent,
            payload,
            actor_type=actor_type,
            actor_id=actor_id,
        ):
            return None
        run = await self._create_queued_run(
            agent,
            payload,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        if run is None:
            return None
        if not execute_immediately:
            return self._to_run(run)
        executed = await self._start_if_capacity(agent, run)
        return self._to_run(executed)

    async def is_active_parent_run(
        self,
        parent_issue_id: str,
        run_id: str | None,
        *,
        expected_org_id: str | None = None,
        expected_agent_id: str | None = None,
    ) -> bool:
        if not run_id:
            return False
        run = await get_run(self._session, run_id)
        return bool(
            run is not None
            and run.status == "running"
            and (expected_org_id is None or run.org_id == expected_org_id)
            and (expected_agent_id is None or run.agent_id == expected_agent_id)
            and _issue_id_from_context(run.context_snapshot) == parent_issue_id
        )

    async def _wakeup_runtime_diagnostic(
        self,
        agent: AgentRow,
        payload: WakeAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
        execute_immediately: bool,
    ) -> HeartbeatRun | None:
        diagnostic_payload: WakeAgentPayload = {
            **payload,
            "contextSnapshot": {
                **self._payload_context_snapshot(payload.get("contextSnapshot")),
                "wakeReason": "runtime_diagnostic",
            },
        }
        lock = self._diagnostic_locks.setdefault(agent.id, asyncio.Lock())
        async with lock:
            if agent.status == "paused":
                await self._create_skipped_wakeup(
                    agent,
                    diagnostic_payload,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    error="agent.paused",
                )
                await self._session.commit()
                return None
            # PostgreSQL serializes through the Agent row. SQLite is serialized
            # by the process-wide lock, held until this transaction commits.
            await self._session.execute(
                select(AgentRow.id).where(AgentRow.id == agent.id).with_for_update()
            )
            run: HeartbeatRunRow | None = None
            idempotency_key = diagnostic_payload.get("idempotencyKey")
            if idempotency_key:
                existing_wakeup = await get_wakeup_by_idempotency_key(
                    self._session, agent.id, idempotency_key
                )
                if existing_wakeup is not None and existing_wakeup.run_id:
                    run = await get_run(self._session, existing_wakeup.run_id)
            if run is None:
                for existing in await list_runs(self._session, agent.org_id, agent.id):
                    existing_context = existing.context_snapshot or {}
                    if (
                        existing.status in {"queued", "running"}
                        and existing.invocation_source == "on_demand"
                        and existing_context.get("wakeReason") == "runtime_diagnostic"
                    ):
                        run = existing
                        break
            if run is not None:
                self.last_wakeup_reused = True
            else:
                run = await self._create_queued_run(
                    agent,
                    diagnostic_payload,
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
            if run is not None:
                await self.record_invoked_activity(
                    self._to_run(run),
                    actor_type=actor_type,
                    actor_id=actor_id,
                )
            await self._session.commit()
        if run is None:
            return None
        if not execute_immediately:
            return self._to_run(run)
        return self._to_run(await self._start_if_capacity(agent, run))

    async def wakeup_if_actionable(
        self,
        agent_id: str,
        payload: WakeAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
        execute_immediately: bool = True,
    ) -> HeartbeatRun | None:
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None:
            return None
        if agent.status in ("terminated", "pending_approval"):
            raise AgentConflictError("Agent is not invokable in its current state")
        if agent.status == "paused":
            await self._create_skipped_wakeup(
                agent,
                payload,
                actor_type=actor_type,
                actor_id=actor_id,
                error="agent.paused",
            )
            return None
        checked_at = datetime.now(UTC)
        recovered_parent = await self._recover_settled_parent_continuation_for_timer(
            agent
        )
        if recovered_parent is not None:
            await advance_agent_heartbeat_check(self._session, agent.id, checked_at)
            if execute_immediately:
                recovered_parent = await self._start_if_capacity(
                    agent, recovered_parent
                )
            return self._to_run(recovered_parent)
        recovered = await self._recover_pending_wakeup_for_timer(agent, checked_at)
        if recovered is not None:
            await advance_agent_heartbeat_check(self._session, agent.id, checked_at)
            if execute_immediately:
                recovered = await self._start_if_capacity(agent, recovered)
            return self._to_run(recovered)
        preflight = await self._evaluate_timer_preflight(agent, checked_at)
        if not preflight["shouldRun"]:
            reason = cast(str, preflight["reason"])
            skipped_payload: WakeAgentPayload = {
                **payload,
                "source": "on_demand",
                "triggerDetail": "manual",
                "reason": reason,
                "payload": {
                    **self._payload_context(payload.get("payload")),
                    "preflight": preflight,
                },
            }
            await self._create_skipped_wakeup(
                agent,
                skipped_payload,
                actor_type=actor_type,
                actor_id=actor_id,
                error=reason,
            )
            await advance_agent_heartbeat_check(self._session, agent.id, checked_at)
            return None
        context_snapshot = {
            **self._payload_context_snapshot(payload.get("contextSnapshot")),
            "wakeReason": "manual_wakeup",
            "heartbeatPreflight": preflight,
        }
        run = await self.wakeup(
            agent.id,
            {
                **payload,
                "source": "on_demand",
                "triggerDetail": "manual",
                "reason": "manual_wakeup",
                "contextSnapshot": context_snapshot,
            },
            actor_type=actor_type,
            actor_id=actor_id,
            execute_immediately=execute_immediately,
        )
        await advance_agent_heartbeat_check(self._session, agent.id, checked_at)
        return run

    async def _defer_issue_wakeup_if_locked(
        self,
        agent: AgentRow,
        payload: WakeAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> bool:
        context = {
            **self._payload_context(payload.get("payload")),
            **self._payload_context_snapshot(payload.get("contextSnapshot")),
        }
        issue_id = _issue_id_from_context(context)
        if issue_id is None:
            return False
        if (
            payload.get("source") == "review"
            or payload.get("reason") == "issue_review_requested"
            or context.get("wakeReason") == "issue_review_requested"
            or context.get("role") == "reviewer"
        ):
            return False
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None or issue.org_id != agent.org_id:
            return False
        run_ids = [
            value for value in (issue.execution_run_id, issue.checkout_run_id) if value
        ]
        active_run_ids: set[str] = set()
        if run_ids:
            active_run_ids.update(
                row.id
                for row in (
                    await self._session.execute(
                        select(HeartbeatRunRow).where(
                            HeartbeatRunRow.id.in_(run_ids),
                            HeartbeatRunRow.status.in_(("queued", "running")),
                        )
                    )
                )
                .scalars()
                .all()
            )
        if not active_run_ids:
            active_run_ids.update(
                row.id
                for row in await list_runs(self._session, issue.org_id, agent.id)
                if row.status in {"queued", "running"}
                and _issue_id_from_context(row.context_snapshot) == issue_id
            )
        if not active_run_ids:
            return False

        deferred_payload = dict(payload.get("payload") or {})
        deferred_payload[self._DEFERRED_CONTEXT_KEY] = dict(
            payload.get("contextSnapshot") or {}
        )
        await create_wakeup_request_idempotent(
            self._session,
            {
                **self._wakeup_values(
                    agent,
                    {
                        **payload,
                        "payload": deferred_payload,
                    },
                    actor_type=actor_type,
                    actor_id=actor_id,
                    status="deferred_issue_execution",
                ),
                "run_id": None,
            },
        )
        return True

    async def record_invoked_activity(
        self, run: HeartbeatRun, *, actor_type: str, actor_id: str
    ) -> None:
        await insert_activity_log(
            self._session,
            org_id=run["orgId"],
            actor_type=actor_type,
            actor_id=actor_id,
            action="heartbeat.invoked",
            entity_type="heartbeat_run",
            entity_id=run["id"],
            agent_id=run["agentId"] if actor_type == "agent" else None,
            run_id=run["id"],
            details={"agentId": run["agentId"]},
        )

    async def record_run_activity(
        self, run: HeartbeatRun, *, action: str, actor_type: str, actor_id: str
    ) -> None:
        details: dict[str, Any] = {"agentId": run["agentId"]}
        if action == "heartbeat.retried":
            details.update(
                {
                    "originalRunId": run["retryOfRunId"],
                    "recoveryTrigger": "manual",
                }
            )
        await insert_activity_log(
            self._session,
            org_id=run["orgId"],
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type="heartbeat_run",
            entity_id=run["id"],
            run_id=run["id"],
            details=details,
        )

    async def list_for_org(
        self, org_id: str, agent_id: str | None = None
    ) -> list[HeartbeatRun]:
        rows = await list_runs(self._session, org_id, agent_id)
        return [self._to_run(row) for row in rows]

    async def get(self, run_id: str) -> HeartbeatRun | None:
        row = await get_run(self._session, run_id)
        return await self._to_run_with_issue_context(row) if row is not None else None

    async def list_for_issue(self, issue_id: str) -> list[dict[str, Any]] | None:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None:
            return None
        rows = await list_runs(self._session, issue.org_id)
        return [
            self._to_issue_run_summary(row, issue)
            for row in rows
            if _issue_id_from_context(row.context_snapshot) == issue.id
        ]

    async def get_active_for_issue(self, issue_id: str) -> HeartbeatRun | None:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None:
            return None
        rows = await list_runs(self._session, issue.org_id)
        for row in rows:
            if row.status in {"queued", "running"} and (
                _issue_id_from_context(row.context_snapshot) == issue.id
            ):
                return await self._to_run_with_issue_context(row)
        return None

    async def request_issue_passive_followup(
        self, issue_id: str, *, actor_type: str, actor_id: str
    ) -> HeartbeatRun | None:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None:
            return None
        if issue.status not in {"todo", "in_progress"}:
            raise ValueError(
                "Issue does not need passive follow-up in its current status"
            )
        if not issue.assignee_agent_id:
            raise ValueError("Issue must have an assignee before passive follow-up")
        agent = await get_agent_by_id(self._session, issue.assignee_agent_id)
        if agent is None:
            raise ValueError("Issue assignee is not invokable")

        scheduled = await self._scheduled_issue_passive_followup(issue, agent)
        if scheduled is not None:
            previous_run = await self._previous_run_for_passive_followup(scheduled)
            if (
                previous_run is not None
                and await self._issue_has_user_intervention_after(
                    issue, previous_run.finished_at or previous_run.created_at
                )
            ):
                await update_wakeup_request(
                    self._session,
                    scheduled.id,
                    {
                        "status": "skipped",
                        "finished_at": datetime.now(UTC),
                        "error": "Issue already has user intervention after the previous run",
                    },
                )
                raise ValueError(
                    "Issue already has user intervention after the previous run"
                )

        active = await self._active_issue_followup_run(issue)
        if active is not None:
            active_context = (
                active.context_snapshot
                if isinstance(active.context_snapshot, dict)
                else {}
            )
            previous_run_id = _passive_followup_context(active_context).get(
                "previousRunId"
            )
            previous_run = (
                await get_run(self._session, previous_run_id)
                if isinstance(previous_run_id, str)
                else None
            )
            if (
                previous_run is not None
                and await self._issue_has_user_intervention_after(
                    issue, previous_run.finished_at or previous_run.created_at
                )
            ):
                raise ValueError(
                    "Issue already has user intervention after the previous run"
                )
            return await self._to_run_with_issue_context(active)

        if scheduled is not None:
            await update_wakeup_request(
                self._session,
                scheduled.id,
                {
                    "requested_at": datetime.now(UTC),
                    "trigger_detail": "manual",
                    "error": None,
                },
            )
            return await self._materialize_manual_passive_followup(scheduled.id)

        previous_run = await self._latest_issue_run_missing_closeout(issue)
        if previous_run is None:
            raise ValueError("Issue has no successful run that needs passive follow-up")
        if await self._issue_has_user_intervention_after(
            issue, previous_run.finished_at or previous_run.created_at
        ):
            raise ValueError(
                "Issue already has user intervention after the previous run"
            )

        context = (
            previous_run.context_snapshot
            if isinstance(previous_run.context_snapshot, dict)
            else {}
        )
        passive_followup = _passive_followup_context(context)
        raw_attempt = passive_followup.get("attempt")
        current_attempt = (
            raw_attempt
            if isinstance(raw_attempt, int) and not isinstance(raw_attempt, bool)
            else 0
        )
        if current_attempt >= ISSUE_PASSIVE_FOLLOWUP_MAX_ATTEMPTS:
            raise ValueError("Issue passive follow-up attempts are exhausted")
        raw_origin_run_id = passive_followup.get("originRunId")
        origin_run_id = (
            raw_origin_run_id if isinstance(raw_origin_run_id, str) else previous_run.id
        )
        wakeup, _ = await create_wakeup_request_idempotent(
            self._session,
            self._wakeup_values(
                agent,
                {
                    "source": "automation",
                    "triggerDetail": "manual",
                    "reason": ISSUE_PASSIVE_FOLLOWUP_REASON,
                    "idempotencyKey": (
                        f"{ISSUE_PASSIVE_FOLLOWUP_REASON}:manual:{previous_run.id}"
                    ),
                    "requestedAt": datetime.now(UTC),
                    "payload": {
                        "issueId": issue.id,
                        "originRunId": origin_run_id,
                        "previousRunId": previous_run.id,
                        "attempt": current_attempt + 1,
                        "reason": ISSUE_PASSIVE_FOLLOWUP_FAILURE_REASON,
                    },
                },
                actor_type=actor_type,
                actor_id=actor_id,
                status="scheduled",
            ),
        )
        return await self._materialize_manual_passive_followup(wakeup.id)

    async def skip_scheduled_issue_passive_followups(
        self, issue_id: str, *, reason: str
    ) -> bool:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None or not issue.assignee_agent_id:
            return False
        skipped = False
        now = datetime.now(UTC)
        for wakeup in await list_wakeup_requests_by_status(
            self._session, issue.assignee_agent_id, "scheduled"
        ):
            payload = wakeup.payload if isinstance(wakeup.payload, dict) else {}
            if (
                wakeup.org_id == issue.org_id
                and wakeup.reason == ISSUE_PASSIVE_FOLLOWUP_REASON
                and payload.get("issueId") == issue.id
            ):
                await update_wakeup_request(
                    self._session,
                    wakeup.id,
                    {
                        "status": "skipped",
                        "finished_at": now,
                        "error": reason,
                    },
                )
                skipped = True
        return skipped

    async def cancel_open_issue_review_wakeups(
        self, issue_id: str, *, reason: str
    ) -> bool:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None or not issue.reviewer_agent_id:
            return False
        cancelled_any = False
        now = datetime.now(UTC)
        for status in ("queued", "claimed"):
            for wakeup in await list_wakeup_requests_by_status(
                self._session, issue.reviewer_agent_id, status
            ):
                payload = wakeup.payload if isinstance(wakeup.payload, dict) else {}
                if (
                    wakeup.org_id == issue.org_id
                    and wakeup.source == "review"
                    and wakeup.reason == "issue_review_requested"
                    and payload.get("issueId") == issue.id
                ):
                    await update_wakeup_request(
                        self._session,
                        wakeup.id,
                        {
                            "status": "skipped" if status == "queued" else "cancelled",
                            "finished_at": now,
                            "error": reason,
                        },
                    )
                    if wakeup.run_id:
                        run = await self._session.get(HeartbeatRunRow, wakeup.run_id)
                        if run is not None and run.status in {"queued", "running"}:
                            was_running = run.status == "running"
                            cancellation = self._cancel_events.get(run.id)
                            if cancellation is not None:
                                cancellation.set()
                            cancelled = await update_run(
                                self._session,
                                run.id,
                                {
                                    "status": "cancelled",
                                    "finished_at": now,
                                    "error": reason,
                                    "error_code": "cancelled",
                                },
                            )
                            if was_running and cancelled is not None:
                                await self._append_event(
                                    cancelled,
                                    await self._next_event_sequence(run.id),
                                    "lifecycle",
                                    message=reason,
                                    level="warning",
                                )
                                await WorkspaceService(
                                    self._session
                                ).mark_run_workspace_interrupted(
                                    run.id, reason="cancelled", message=reason
                                )
                                agent = await get_agent_by_id(
                                    self._session, run.agent_id
                                )
                                if agent is not None and agent.status == "running":
                                    await update_agent(
                                        self._session, agent.id, {"status": "idle"}
                                    )
                    cancelled_any = True
        return cancelled_any

    async def _active_issue_followup_run(
        self, issue: IssueRow
    ) -> HeartbeatRunRow | None:
        for row in await list_runs(self._session, issue.org_id):
            if (
                row.status in {"queued", "running"}
                and row.run_purpose == "closeout_followup"
                and _issue_id_from_context(row.context_snapshot) == issue.id
            ):
                return row
        return None

    async def _scheduled_issue_passive_followup(
        self, issue: IssueRow, agent: AgentRow
    ) -> AgentWakeupRequestRow | None:
        for wakeup in await list_wakeup_requests_by_status(
            self._session, agent.id, "scheduled"
        ):
            payload = wakeup.payload if isinstance(wakeup.payload, dict) else {}
            if (
                wakeup.org_id == issue.org_id
                and wakeup.reason == ISSUE_PASSIVE_FOLLOWUP_REASON
                and payload.get("issueId") == issue.id
            ):
                return wakeup
        return None

    async def _previous_run_for_passive_followup(
        self, wakeup: AgentWakeupRequestRow
    ) -> HeartbeatRunRow | None:
        payload = wakeup.payload if isinstance(wakeup.payload, dict) else {}
        previous_run_id = payload.get("previousRunId")
        if not isinstance(previous_run_id, str):
            return None
        return await get_run(self._session, previous_run_id)

    async def _latest_issue_run_missing_closeout(
        self, issue: IssueRow
    ) -> HeartbeatRunRow | None:
        issue_has_reviewer = bool(issue.reviewer_agent_id or issue.reviewer_user_id)
        for row in await list_runs(self._session, issue.org_id):
            if (
                row.agent_id != issue.assignee_agent_id
                or row.run_purpose != "task_execution"
                or not (
                    row.status == "succeeded"
                    or (row.status == "failed" and row.error_code == "closeout_missing")
                )
                or _issue_id_from_context(row.context_snapshot) != issue.id
            ):
                continue
            if not await self._run_has_issue_closeout_signal(
                row, issue.id, issue_has_reviewer=issue_has_reviewer
            ) and not await self._issue_has_user_intervention_after(
                issue, row.finished_at or row.created_at
            ):
                return row
        return None

    async def _materialize_manual_passive_followup(
        self, wakeup_id: str
    ) -> HeartbeatRun:
        await self.materialize_due_scheduled_wakeups()
        run = (
            await self._session.execute(
                select(HeartbeatRunRow).where(
                    HeartbeatRunRow.wakeup_request_id == wakeup_id
                )
            )
        ).scalar_one_or_none()
        if run is None:
            raise ValueError("Issue passive follow-up is no longer eligible")
        return await self._to_run_with_issue_context(run)

    async def list_events(
        self, run_id: str, *, after_seq: int = 0, limit: int = 200
    ) -> list[HeartbeatRunEvent]:
        rows = await list_run_events(
            self._session,
            run_id,
            after_seq=max(0, after_seq),
            limit=max(1, min(limit, 1000)),
        )
        return [self._to_event(row) for row in rows]

    async def read_log(
        self, run_id: str, *, offset: int = 0, limit_bytes: int = 256_000
    ) -> LogReadResult | None:
        run = await get_run(self._session, run_id)
        if run is None:
            return None
        if run.log_store != "local_file":
            return {"content": "", "endOffset": 0, "eof": True}
        return read_local_file_log(
            _run_log_dir(),
            run.log_ref,
            offset=offset,
            limit_bytes=limit_bytes,
        )

    async def _initialize_run_log(self, run: HeartbeatRunRow) -> HeartbeatRunRow:
        log_ref = f"{run.org_id}/{run.id}.ndjson"
        append_local_file_log(
            _run_log_dir(),
            log_ref,
            stream="system",
            chunk="run log initialized",
        )
        updated = await update_run(
            self._session,
            run.id,
            {
                "log_store": "local_file",
                "log_ref": log_ref,
                "log_bytes": 0,
                "log_compressed": False,
            },
        )
        assert updated is not None
        return updated

    async def _append_run_log(
        self, run: HeartbeatRunRow, *, stream: str, chunk: str
    ) -> None:
        if run.log_store != "local_file" or run.log_ref is None:
            return
        append_local_file_log(_run_log_dir(), run.log_ref, stream=stream, chunk=chunk)

    def _finalize_run_log_fields(self, run: HeartbeatRunRow) -> dict[str, Any]:
        if run.log_store != "local_file":
            return {}
        return _database_log_fields(
            finalize_local_file_log(_run_log_dir(), run.log_ref)
        )

    async def cancel_run(self, run_id: str) -> HeartbeatRun | None:
        run = await get_run(self._session, run_id)
        if run is None:
            return None
        if run.status not in ("queued", "running"):
            return self._to_run(run)
        cancellation = self._cancel_events.get(run.id)
        if cancellation is not None:
            cancellation.set()
        now = datetime.now(UTC)
        cancelled = await self.finalizer.transition(
            run.id,
            "cancelled",
            {
                "finished_at": now,
                "error": "run cancelled",
                "error_code": "cancelled",
                **self._finalize_run_log_fields(run),
            },
            expected_statuses=("queued", "running"),
            expected_owner_token=(
                run.execution_owner_token if run.status == "running" else None
            ),
        )
        if cancelled is None:
            current = await get_run(self._session, run.id)
            return self._to_run(current) if current is not None else None
        await WorkspaceService(self._session).mark_run_workspace_interrupted(
            run.id, reason="cancelled", message="run cancelled"
        )
        cancelled = await self._reconcile_terminal_effects(cancelled)
        return self._to_run(cancelled)

    async def retry_run(
        self,
        run_id: str,
        *,
        actor_type: str,
        actor_id: str,
        execute_immediately: bool = True,
        recovery_trigger: str = "manual",
    ) -> HeartbeatRun | None:
        original = await get_run(self._session, run_id)
        if original is None:
            return None
        if original.status not in ("failed", "timed_out", "cancelled"):
            raise AgentConflictError(
                "Only terminal failed or cancelled runs can be retried"
            )
        agent = await get_agent_by_id(self._session, original.agent_id)
        if agent is None:
            return None
        if agent.status in ("terminated", "pending_approval", "paused"):
            raise AgentConflictError("Agent is not invokable in its current state")
        context_snapshot = dict(original.context_snapshot or {})
        context_snapshot["recovery"] = {
            "originalRunId": original.id,
            "failureKind": original.error_code or original.status,
            "failureSummary": original.error,
            "recoveryTrigger": recovery_trigger,
            "recoveryMode": "continue_preferred",
        }
        is_passive_followup = (
            original.invocation_source == "automation"
            and context_snapshot.get("wakeReason") == ISSUE_PASSIVE_FOLLOWUP_REASON
        )
        invocation_source = (
            "automation"
            if recovery_trigger == "automatic" or is_passive_followup
            else "review"
            if original.invocation_source == "review"
            else "on_demand"
        )
        trigger_detail = "system" if recovery_trigger == "automatic" else "manual"
        retry_idempotency_key = f"run:{original.id}:retry"
        wakeup, created = await create_wakeup_request_idempotent(
            self._session,
            self._wakeup_values(
                agent,
                {
                    "source": invocation_source,
                    "triggerDetail": trigger_detail,
                    "reason": f"{recovery_trigger}_retry",
                    "payload": None,
                    "idempotencyKey": retry_idempotency_key,
                },
                actor_type=actor_type,
                actor_id=actor_id,
                status="queued",
            ),
        )
        if not created and wakeup.run_id:
            existing = await get_run(self._session, wakeup.run_id)
            return self._to_run(existing) if existing is not None else None
        context_snapshot = await self._enrich_issue_context_snapshot(context_snapshot)
        run = await create_run(
            self._session,
            {
                "org_id": agent.org_id,
                "agent_id": agent.id,
                "invocation_source": invocation_source,
                "run_purpose": original.run_purpose,
                "trigger_detail": trigger_detail,
                "status": "queued",
                "wakeup_request_id": wakeup.id,
                "retry_of_run_id": original.id,
                "process_loss_retry_count": (
                    original.process_loss_retry_count + 1
                    if recovery_trigger == "automatic"
                    else original.process_loss_retry_count
                ),
                "context_snapshot": context_snapshot,
            },
        )
        run = await self._initialize_run_log(run)
        await update_wakeup_request(self._session, wakeup.id, {"run_id": run.id})
        if not execute_immediately:
            return self._to_run(run)
        return self._to_run(await self._start_if_capacity(agent, run))

    async def recover_orphaned_runs(
        self, *, require_process_loss: bool = False
    ) -> list[HeartbeatRun]:
        return await self.recovery.recover(require_process_loss=require_process_loss)

    async def _recover_orphaned_runs_impl(
        self,
        *,
        require_process_loss: bool = False,
        run_ids: set[str] | None = None,
    ) -> list[HeartbeatRun]:
        recovered: list[HeartbeatRun] = []
        await self._recover_all_settled_parent_continuations()
        for terminal_run in await list_runs_with_pending_terminal_effects(
            self._session
        ):
            if run_ids is not None and terminal_run.id not in run_ids:
                continue
            await self._reconcile_terminal_effects(terminal_run)
        active_ids = (
            set().union(*self._active_run_ids.values())
            if self._active_run_ids
            else set()
        )
        for run in await list_runs_by_status(self._session, "running"):
            if run_ids is not None and run.id not in run_ids:
                continue
            now = datetime.now(UTC)
            lease_expires_at = run.execution_lease_expires_at
            if lease_expires_at is not None:
                if lease_expires_at.tzinfo is None:
                    lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
                if lease_expires_at > now:
                    continue
            is_marked_active = run.id in active_ids
            agent = await get_agent_by_id(self._session, run.agent_id)
            tracks_local_child = (
                agent is not None
                and agent.agent_runtime_type in LOCAL_CHILD_PROCESS_RUNTIMES
                and run.process_pid is not None
            )
            if require_process_loss:
                if tracks_local_child:
                    assert run.process_pid is not None
                    if _is_process_alive(run.process_pid):
                        continue
                elif lease_expires_at is None:
                    recovery_baseline = (
                        run.started_at or run.updated_at or run.created_at
                    )
                    if recovery_baseline.tzinfo is None:
                        recovery_baseline = recovery_baseline.replace(tzinfo=UTC)
                    if (
                        recovery_baseline
                        + timedelta(seconds=RUN_RECOVERY_GRACE_SECONDS)
                        > now
                    ):
                        continue
            elif is_marked_active:
                continue
            claimed = await claim_expired_run_execution(self._session, run.id, now=now)
            if claimed is None:
                continue
            run = claimed
            if await self._cancel_orphaned_run_if_issue_closed(run):
                continue
            if is_marked_active:
                self._active_run_ids.get(run.agent_id, set()).discard(run.id)
            detached_message: str | None = None
            if tracks_local_child:
                detached_message = (
                    f"Detached child pid {run.process_pid} was not terminated during "
                    "server recovery because process ownership cannot be verified"
                )
            failed = await self.finalizer.transition(
                run.id,
                "failed",
                {
                    "finished_at": datetime.now(UTC),
                    "error": (
                        f"Process lost -- child pid {run.process_pid} is no longer running"
                        if run.process_pid
                        else "Run interrupted before server recovery"
                    ),
                    "error_code": "process_lost",
                    **self._finalize_run_log_fields(run),
                },
                expected_owner_token=run.execution_owner_token,
            )
            if failed is None:
                continue
            await self._append_event(
                failed,
                await self._next_event_sequence(run.id),
                "lifecycle",
                message="run interrupted before server recovery",
                level="error",
                payload=(
                    {
                        "processPid": run.process_pid,
                        "wasMarkedActive": is_marked_active,
                    }
                    if run.process_pid
                    else {"wasMarkedActive": is_marked_active}
                ),
                idempotency_key="recovery:process-lost",
            )
            await WorkspaceService(self._session).mark_run_workspace_interrupted(
                run.id,
                reason="process_lost",
                message="Run interrupted before server recovery",
            )
            failed = await self._reconcile_terminal_effects(failed)
            if detached_message:
                await self._append_event(
                    failed,
                    await self._next_event_sequence(run.id),
                    "lifecycle",
                    message=detached_message,
                    level="warn",
                    payload={"processPid": run.process_pid},
                )
            if run.process_loss_retry_count >= 1:
                continue
            try:
                retry = await self.retry_run(
                    run.id,
                    actor_type="system",
                    actor_id="heartbeat_scheduler",
                    execute_immediately=False,
                    recovery_trigger="automatic",
                )
            except AgentConflictError as exc:
                await self._append_event(
                    failed,
                    await self._next_event_sequence(run.id),
                    "lifecycle",
                    message=f"automatic recovery retry skipped: {exc}",
                    level="warning",
                )
                continue
            if retry is not None:
                recovered.append(retry)
        return recovered

    async def _recover_all_settled_parent_continuations(self) -> None:
        """Repair missing child-settled continuations without heartbeat timers."""

        agents = (await self._session.execute(select(AgentRow))).scalars().all()
        for agent in agents:
            if agent.status in {"terminated", "pending_approval"}:
                continue
            try:
                await self._recover_settled_parent_continuation_for_timer(agent)
            except (AgentConflictError, ValueError):
                logger.warning(
                    "settled parent continuation recovery skipped",
                    extra={"agent_id": agent.id},
                    exc_info=True,
                )

    async def _cancel_orphaned_run_if_issue_closed(self, run: HeartbeatRunRow) -> bool:
        await self._session.refresh(run)
        if run.status != "running":
            return True
        terminal_event_statuses = {
            event.message.removeprefix("run ")
            for event in await list_run_events(
                self._session, run.id, after_seq=-1, limit=10_000
            )
            if event.event_type == "lifecycle"
            and event.message
            in {"run succeeded", "run failed", "run timed_out", "run cancelled"}
        }
        if len(terminal_event_statuses) > 1:
            await self._append_event(
                run,
                await self._next_event_sequence(run.id),
                "recovery.error",
                message="Conflicting terminal evidence; automatic recovery skipped",
                level="error",
                payload={"terminalStatuses": sorted(terminal_event_statuses)},
                idempotency_key="recovery:terminal-evidence-conflict",
            )
            return True
        if terminal_event_statuses:
            recovered_status = cast(HeartbeatRunStatus, terminal_event_statuses.pop())
            recovered = await self.finalizer.transition(
                run.id,
                recovered_status,
                {
                    "finished_at": run.finished_at or datetime.now(UTC),
                    **self._finalize_run_log_fields(run),
                },
                expected_owner_token=run.execution_owner_token,
            )
            if recovered is not None:
                await self._reconcile_terminal_effects(recovered)
            return True
        if run.invocation_source != "assignment":
            return False
        issue_id = _issue_id_from_context(run.context_snapshot)
        issue = await get_issue_by_id(self._session, issue_id) if issue_id else None
        if issue is None or issue.org_id != run.org_id:
            return False
        if issue.status not in {"done", "cancelled"}:
            return False
        message = f"Run stopped during recovery because issue is already {issue.status}"
        cancelled = await self.finalizer.transition(
            run.id,
            "cancelled",
            {
                "finished_at": datetime.now(UTC),
                "error": message,
                "error_code": "issue_already_closed",
                **self._finalize_run_log_fields(run),
            },
            expected_owner_token=run.execution_owner_token,
        )
        if cancelled is None:
            return True
        await self._append_event(
            cancelled,
            await self._next_event_sequence(run.id),
            "lifecycle",
            message=message,
            level="warning",
            payload={"issueId": issue.id, "issueStatus": issue.status},
            idempotency_key="recovery:issue-already-closed",
        )
        await self._reconcile_terminal_effects(cancelled)
        return True

    async def resume_queued_runs(self, agent_id: str) -> list[HeartbeatRun]:
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None:
            return []
        resumed: list[HeartbeatRun] = []
        for run in await list_queued_runs(self._session, agent_id):
            current = await self._start_if_capacity(agent, run)
            resumed.append(self._to_run(current))
            if current.status == "queued":
                break
        return resumed

    async def resume_all_queued_runs(self) -> list[HeartbeatRun]:
        resumed: list[HeartbeatRun] = []
        for agent_id in await list_queued_agent_ids(self._session):
            resumed.extend(await self.resume_queued_runs(agent_id))
        return resumed

    async def materialize_due_scheduled_wakeups(self) -> set[str]:
        now = datetime.now(UTC)
        agent_ids: set[str] = set()
        for wakeup_id in await list_due_wakeup_request_ids(
            self._session, "scheduled", now
        ):
            wakeup = await claim_due_wakeup_request(
                self._session, wakeup_id, "scheduled", now
            )
            if wakeup is None:
                continue
            agent = await get_agent_by_id(self._session, wakeup.agent_id)
            if agent is None or agent.status in {"terminated", "pending_approval"}:
                await update_wakeup_request(
                    self._session,
                    wakeup.id,
                    {
                        "status": "skipped",
                        "finished_at": now,
                        "error": "Agent is not invokable in its current state",
                    },
                )
                continue
            if agent.status == "paused":
                await update_wakeup_request(
                    self._session,
                    wakeup.id,
                    {"status": "scheduled", "claimed_at": None},
                )
                continue
            if wakeup.reason != ISSUE_PASSIVE_FOLLOWUP_REASON:
                await update_wakeup_request(
                    self._session,
                    wakeup.id,
                    {
                        "status": "skipped",
                        "finished_at": now,
                        "error": "Unsupported scheduled wakeup reason",
                    },
                )
                continue
            payload = wakeup.payload if isinstance(wakeup.payload, dict) else {}
            issue_id = payload.get("issueId")
            previous_run_id = payload.get("previousRunId")
            issue = (
                await get_issue_by_id(self._session, issue_id)
                if isinstance(issue_id, str)
                else None
            )
            previous_run = (
                await get_run(self._session, previous_run_id)
                if isinstance(previous_run_id, str)
                else None
            )
            if (
                issue is None
                or issue.org_id != wakeup.org_id
                or issue.assignee_agent_id != agent.id
                or issue.status not in {"todo", "in_progress"}
                or previous_run is None
                or await self._issue_has_user_intervention_after(
                    issue, previous_run.finished_at or previous_run.created_at
                )
                or await self._run_has_issue_closeout_signal(
                    previous_run,
                    issue.id,
                    issue_has_reviewer=bool(
                        issue.reviewer_agent_id or issue.reviewer_user_id
                    ),
                )
            ):
                await update_wakeup_request(
                    self._session,
                    wakeup.id,
                    {"status": "skipped", "finished_at": now},
                )
                continue
            attempt = payload.get("attempt")
            context_snapshot = await self._enrich_issue_context_snapshot(
                {
                    "triggeredBy": "system",
                    "actorId": "heartbeat_closeout_governance",
                    "forceFreshSession": False,
                    "issueId": issue.id,
                    "source": "issue.passive_followup",
                    "wakeSource": ISSUE_PASSIVE_FOLLOWUP_WAKE_SOURCE,
                    "wakeReason": ISSUE_PASSIVE_FOLLOWUP_REASON,
                    "passiveFollowup": {
                        "originRunId": payload.get("originRunId"),
                        "previousRunId": previous_run.id,
                        "attempt": attempt,
                        "maxAttempts": ISSUE_PASSIVE_FOLLOWUP_MAX_ATTEMPTS,
                        "reason": payload.get("reason"),
                        "queuedAt": now.isoformat(),
                    },
                }
            )
            run = await create_run(
                self._session,
                {
                    "org_id": agent.org_id,
                    "agent_id": agent.id,
                    "invocation_source": wakeup.source,
                    "run_purpose": "closeout_followup",
                    "trigger_detail": wakeup.trigger_detail,
                    "status": "queued",
                    "wakeup_request_id": wakeup.id,
                    "context_snapshot": context_snapshot,
                },
            )
            run = await self._initialize_run_log(run)
            await update_wakeup_request(
                self._session,
                wakeup.id,
                {"status": "queued", "run_id": run.id, "error": None},
            )
            await self._append_event(
                run,
                1,
                "lifecycle",
                stream="system",
                message="run queued",
                level="info",
                payload={
                    "status": "queued",
                    "source": wakeup.source,
                    "triggerDetail": wakeup.trigger_detail,
                },
            )
            agent_ids.add(agent.id)
        return agent_ids

    async def claim_queued_for_dispatch(self, agent_id: str) -> list[str]:
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None or agent.status in (
            "paused",
            "terminated",
            "pending_approval",
        ):
            return []
        lock = self._start_locks.setdefault(agent.id, asyncio.Lock())
        async with lock:
            active = self._active_run_ids.setdefault(agent.id, set())
            persisted = await list_running_run_ids(self._session, agent.id)
            available = self._max_concurrent_runs(agent) - len(persisted | active)
            if available <= 0:
                return []
            claimed_ids: list[str] = []
            for queued_run in (await list_queued_runs(self._session, agent.id))[
                :available
            ]:
                claimed = await claim_queued_run(
                    self._session, queued_run.id, datetime.now(UTC)
                )
                if claimed is None:
                    continue
                active.add(claimed.id)
                await self._prepare_execution(agent, claimed)
                claimed_ids.append(claimed.id)
            return claimed_ids

    async def execute_claimed_run(self, run_id: str) -> HeartbeatRun | None:
        run = await get_run(self._session, run_id)
        if run is None or run.status != "running":
            return self._to_run(run) if run is not None else None
        agent = await get_agent_by_id(self._session, run.agent_id)
        if agent is None:
            return None
        try:
            return self._to_run(await self._execute_run(agent, run, prepared=True))
        finally:
            self._active_run_ids.get(agent.id, set()).discard(run.id)

    async def _commit_background_runtime_progress(self) -> None:
        if self._commit_process_metadata:
            await self._session.commit()

    async def resume_deferred_wakeups(
        self, agent_id: str, *, execute_immediately: bool = True
    ) -> list[HeartbeatRun]:
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None or agent.status == "paused":
            return []
        resumed: list[HeartbeatRun] = []
        for wakeup in await list_wakeup_requests_by_status(
            self._session, agent_id, "deferred_agent_paused"
        ):
            payload: WakeAgentPayload = {
                "source": cast(HeartbeatInvocationSource, wakeup.source),
                "triggerDetail": cast(
                    WakeupTriggerDetail, wakeup.trigger_detail or "manual"
                ),
                "reason": wakeup.reason,
                "payload": wakeup.payload,
            }
            await update_wakeup_request(self._session, wakeup.id, {"status": "queued"})
            if wakeup.run_id:
                existing_run = await get_run(self._session, wakeup.run_id)
                if existing_run is not None:
                    resumed.append(
                        self._to_run(
                            await self._start_if_capacity(agent, existing_run)
                            if execute_immediately
                            else existing_run
                        )
                    )
                    continue
            context_snapshot = {
                "resumedFromPaused": True,
                **self._payload_context(wakeup.payload),
            }
            context_snapshot = await self._enrich_issue_context_snapshot(
                context_snapshot
            )
            run = await create_run(
                self._session,
                {
                    "org_id": agent.org_id,
                    "agent_id": agent.id,
                    "invocation_source": payload["source"],
                    "run_purpose": _run_purpose(payload["source"], context_snapshot),
                    "trigger_detail": payload["triggerDetail"],
                    "status": "queued",
                    "wakeup_request_id": wakeup.id,
                    "context_snapshot": context_snapshot,
                },
            )
            run = await self._initialize_run_log(run)
            await update_wakeup_request(self._session, wakeup.id, {"run_id": run.id})
            await self._claim_issue_execution_for_task_run(agent, run, context_snapshot)
            resumed.append(
                self._to_run(
                    await self._start_if_capacity(agent, run)
                    if execute_immediately
                    else run
                )
            )
        return resumed

    async def _create_skipped_wakeup(
        self,
        agent: AgentRow,
        payload: WakeAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
        error: str,
    ) -> None:
        await create_wakeup_request_idempotent(
            self._session,
            {
                **self._wakeup_values(
                    agent,
                    payload,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    status="skipped",
                ),
                "error": error,
                "finished_at": datetime.now(UTC),
            },
        )

    async def tick_timers(
        self, org_id: str, *, now: datetime | None = None
    ) -> list[HeartbeatRun]:
        checked_at = now or datetime.now(UTC)
        triggered: list[HeartbeatRun] = []
        for agent in await list_org_agents(self._session, org_id):
            if agent.status in {"paused", "terminated", "pending_approval"}:
                continue
            policy = self._heartbeat_policy(agent)
            baseline_candidates = [
                value.replace(tzinfo=UTC) if value.tzinfo is None else value
                for value in (
                    agent.last_heartbeat_check_at,
                    agent.last_heartbeat_at,
                    agent.created_at,
                )
                if value is not None
            ]
            baseline = max(baseline_candidates)
            if (
                not policy["enabled"]
                or policy["intervalSec"] <= 0
                or checked_at - baseline < timedelta(seconds=policy["intervalSec"])
            ):
                continue
            if await has_active_timer_run(self._session, agent.id):
                continue
            recovered_parent = (
                await self._recover_settled_parent_continuation_for_timer(agent)
            )
            if recovered_parent is not None:
                await advance_agent_heartbeat_check(self._session, agent.id, checked_at)
                triggered.append(self._to_run(recovered_parent))
                continue
            recovered = await self._recover_pending_wakeup_for_timer(agent, checked_at)
            if recovered is not None:
                await advance_agent_heartbeat_check(self._session, agent.id, checked_at)
                triggered.append(self._to_run(recovered))
                continue
            due_at = baseline + timedelta(seconds=policy["intervalSec"])
            idempotency_key = f"heartbeat:timer:{agent.id}:{due_at.isoformat()}"
            preflight: dict[str, Any] | None = None
            if policy.get("preflightEnabled", True):
                preflight = await self._evaluate_timer_preflight(agent, checked_at)
                if not preflight["shouldRun"]:
                    reason = cast(str, preflight["reason"])
                    await self._create_skipped_wakeup(
                        agent,
                        {
                            "source": "timer",
                            "triggerDetail": "system",
                            "reason": reason,
                            "payload": {"preflight": preflight},
                            "idempotencyKey": idempotency_key,
                            "requestedAt": checked_at,
                        },
                        actor_type="system",
                        actor_id="scheduler",
                        error=reason,
                    )
                    await advance_agent_heartbeat_check(
                        self._session, agent.id, checked_at
                    )
                    continue
            run = await self.wakeup(
                agent.id,
                {
                    "source": "timer",
                    "triggerDetail": "system",
                    "reason": "heartbeat_timer",
                    "payload": (
                        {"preflight": preflight}
                        if preflight is not None
                        else {
                            "preflight": {
                                "enabled": False,
                                "shouldRun": True,
                                "reason": "heartbeat.preflight.disabled",
                            }
                        }
                    ),
                    "contextSnapshot": (
                        {"heartbeatPreflight": preflight}
                        if preflight is not None
                        else {
                            "heartbeatPreflight": {
                                "enabled": False,
                                "shouldRun": True,
                                "reason": "heartbeat.preflight.disabled",
                            }
                        }
                    ),
                    "idempotencyKey": idempotency_key,
                    "requestedAt": checked_at,
                },
                actor_type="system",
                actor_id="scheduler",
                execute_immediately=False,
            )
            if run is not None:
                await advance_agent_heartbeat_check(self._session, agent.id, checked_at)
                triggered.append(run)
        return triggered

    async def _recover_settled_parent_continuation_for_timer(
        self, agent: AgentRow
    ) -> HeartbeatRunRow | None:
        child = aliased(IssueRow)
        active_child = aliased(IssueRow)
        has_children = (
            select(child.id)
            .where(
                child.org_id == IssueRow.org_id,
                child.parent_id == IssueRow.id,
                child.hidden_at.is_(None),
            )
            .correlate(IssueRow)
            .exists()
        )
        has_active_children = (
            select(active_child.id)
            .where(
                active_child.org_id == IssueRow.org_id,
                active_child.parent_id == IssueRow.id,
                active_child.hidden_at.is_(None),
                active_child.status.in_(
                    ("backlog", "todo", "in_progress", "in_review")
                ),
            )
            .correlate(IssueRow)
            .exists()
        )
        parents = (
            (
                await self._session.execute(
                    select(IssueRow)
                    .where(
                        IssueRow.org_id == agent.org_id,
                        IssueRow.assignee_agent_id == agent.id,
                        IssueRow.hidden_at.is_(None),
                        IssueRow.status.in_(("todo", "in_progress")),
                        has_children,
                        ~has_active_children,
                    )
                    .order_by(IssueRow.updated_at, IssueRow.id)
                )
            )
            .scalars()
            .all()
        )
        for parent in parents:
            children = (
                (
                    await self._session.execute(
                        select(IssueRow)
                        .where(
                            IssueRow.org_id == parent.org_id,
                            IssueRow.parent_id == parent.id,
                            IssueRow.hidden_at.is_(None),
                        )
                        .order_by(IssueRow.created_at, IssueRow.id)
                    )
                )
                .scalars()
                .all()
            )
            if not children:
                continue
            batch = await DelegationBatchStore(self._session).for_child(children[-1])
            settlement_cycle_key = await self.parent_continuation.settlement_cycle_key(
                parent.id, batch=batch
            )
            if settlement_cycle_key is None:
                continue
            idempotency_key = (
                f"issue:{parent.id}:children_settled:{settlement_cycle_key}"
            )
            existing = await get_wakeup_by_idempotency_key(
                self._session, agent.id, idempotency_key
            )
            if existing is None:
                await self.queue_parent_continuation_for_settled_child(
                    children[-1].id, expected_org_id=agent.org_id
                )
                existing = await get_wakeup_by_idempotency_key(
                    self._session, agent.id, idempotency_key
                )
            if existing is not None and existing.run_id is not None:
                run = await get_run(self._session, existing.run_id)
                if run is not None and run.status in {"queued", "running"}:
                    return run
        return None

    async def _recover_pending_wakeup_for_timer(
        self, agent: AgentRow, checked_at: datetime
    ) -> HeartbeatRunRow | None:
        pending = await list_pending_runless_wakeup_requests(
            self._session,
            agent.org_id,
            agent.id,
            checked_at,
        )
        actionable_issue_ids: set[str] | None = None
        for wakeup in pending:
            payload = dict(wakeup.payload or {})
            issue_id = _issue_id_from_context(payload)
            issue = (
                await get_issue_by_id(self._session, issue_id)
                if issue_id is not None
                else None
            )
            if issue_id is not None and (
                issue is None
                or issue.org_id != agent.org_id
                or issue.status in {"done", "cancelled"}
            ):
                await update_wakeup_request(
                    self._session,
                    wakeup.id,
                    {
                        "status": "skipped",
                        "finished_at": checked_at,
                        "error": "Pending wake skipped because issue is closed or missing",
                    },
                )
                continue
            if wakeup.source in {"assignment", "review"}:
                if actionable_issue_ids is None:
                    actionable_issue_ids = {
                        candidate.id
                        for candidate in await list_agent_actionable_heartbeat_issues(
                            self._session, agent.org_id, agent.id
                        )
                    }
                relationship_matches = (
                    wakeup.source == "assignment"
                    and issue is not None
                    and issue.assignee_agent_id == agent.id
                ) or (
                    wakeup.source == "review"
                    and issue is not None
                    and issue.reviewer_agent_id == agent.id
                )
                is_current_parent_continuation = False
                if (
                    wakeup.source == "assignment"
                    and wakeup.reason == "issue_children_settled"
                    and issue is not None
                    and issue.assignee_agent_id == agent.id
                ):
                    origin_run_id = payload.get("delegationOriginRunId")
                    batch = (
                        await DelegationBatchStore(self._session).for_parent(
                            issue.id,
                            org_id=issue.org_id,
                            origin_run_id=origin_run_id,
                        )
                        if isinstance(origin_run_id, str) and origin_run_id
                        else None
                    )
                    settlement_cycle_key = (
                        await self.parent_continuation.settlement_cycle_key(
                            issue.id, batch=batch
                        )
                    )
                    is_current_parent_continuation = (
                        settlement_cycle_key is not None
                        and wakeup.idempotency_key
                        == f"issue:{issue.id}:children_settled:{settlement_cycle_key}"
                    )
                if (
                    issue_id is None
                    or issue is None
                    or (
                        issue.id not in actionable_issue_ids
                        and not is_current_parent_continuation
                    )
                    or not relationship_matches
                ):
                    await update_wakeup_request(
                        self._session,
                        wakeup.id,
                        {
                            "status": "skipped",
                            "finished_at": checked_at,
                            "error": (
                                "Pending wake skipped because issue assignment "
                                "or review is stale"
                            ),
                        },
                    )
                    continue
            if (
                wakeup.source == "assignment"
                and issue is not None
                and issue.execution_run_id is not None
            ):
                return None

            claimed = await claim_due_wakeup_request(
                self._session,
                wakeup.id,
                wakeup.status,
                checked_at,
            )
            if claimed is None:
                await self._session.refresh(wakeup)
                if wakeup.run_id is not None:
                    return await get_run(self._session, wakeup.run_id)
                return None

            deferred_context = payload.pop(self._DEFERRED_CONTEXT_KEY, {})
            context_snapshot = {
                "triggeredBy": claimed.requested_by_actor_type or "system",
                "actorId": claimed.requested_by_actor_id or "scheduler",
                "forceFreshSession": False,
                "recoveredPendingWakeup": True,
                **self._payload_context(payload),
                **(deferred_context if isinstance(deferred_context, dict) else {}),
            }
            context_snapshot = await self._enrich_issue_context_snapshot(
                context_snapshot
            )
            run = await create_run(
                self._session,
                {
                    "org_id": agent.org_id,
                    "agent_id": agent.id,
                    "invocation_source": claimed.source,
                    "run_purpose": _run_purpose(claimed.source, context_snapshot),
                    "trigger_detail": claimed.trigger_detail,
                    "status": "queued",
                    "wakeup_request_id": claimed.id,
                    "context_snapshot": context_snapshot,
                },
            )
            run = await self._initialize_run_log(run)
            await update_wakeup_request(
                self._session,
                claimed.id,
                {
                    "status": "queued",
                    "payload": payload,
                    "run_id": run.id,
                    "claimed_at": None,
                    "finished_at": None,
                    "error": None,
                },
            )
            await self._claim_issue_execution_for_task_run(
                agent,
                run,
                context_snapshot,
                issue=issue,
            )
            await self._append_event(
                run,
                1,
                "lifecycle",
                stream="system",
                message="run queued",
                level="info",
                payload={
                    "status": "queued",
                    "source": claimed.source,
                    "triggerDetail": claimed.trigger_detail,
                    "recoveredPendingWakeup": True,
                },
            )
            return run
        return None

    async def _evaluate_timer_preflight(
        self, agent: AgentRow, checked_at: datetime
    ) -> dict[str, Any]:
        pending_wakeups = await list_pending_runless_wakeup_requests(
            self._session,
            agent.org_id,
            agent.id,
            checked_at,
        )
        if pending_wakeups:
            statuses: dict[str, int] = {}
            for wakeup in pending_wakeups:
                statuses[wakeup.status] = statuses.get(wakeup.status, 0) + 1
            return {
                "enabled": True,
                "shouldRun": False,
                "reason": "heartbeat.preflight.pending_wakeup_request",
                "pendingWakeupCount": len(pending_wakeups),
                "pendingWakeupStatuses": statuses,
            }

        if await has_active_agent_run(self._session, agent.id):
            return {
                "enabled": True,
                "shouldRun": False,
                "reason": "heartbeat.preflight.active_run",
            }

        issues = await list_agent_actionable_heartbeat_issues(
            self._session,
            agent.org_id,
            agent.id,
        )
        if not issues:
            return {
                "enabled": True,
                "shouldRun": False,
                "reason": "heartbeat.preflight.no_actionable_work",
                "actionableIssueCount": 0,
            }

        assignee_count = sum(issue.assignee_agent_id == agent.id for issue in issues)
        reviewer_count = sum(issue.reviewer_agent_id == agent.id for issue in issues)
        return {
            "enabled": True,
            "shouldRun": True,
            "reason": (
                "heartbeat.preflight.reviewer_issue"
                if reviewer_count and not assignee_count
                else "heartbeat.preflight.assignee_issue"
            ),
            "actionableIssueCount": len(issues),
            "assigneeIssueCount": assignee_count,
            "reviewerIssueCount": reviewer_count,
            "actionableIssueIds": [issue.id for issue in issues],
        }

    async def _materialize_deferred_wakeup(
        self,
        agent: AgentRow,
        wakeup: AgentWakeupRequestRow,
        payload: dict[str, Any],
    ) -> HeartbeatRunRow:
        deferred_context = payload.pop(self._DEFERRED_CONTEXT_KEY, {})
        retry_of_run_id = payload.pop(self._RETRY_OF_RUN_KEY, None)
        retry_run_purpose = payload.pop(self._RETRY_PURPOSE_KEY, None)
        retry_process_loss_count = payload.pop(self._RETRY_PROCESS_LOSS_COUNT_KEY, 0)
        context_snapshot = {
            "triggeredBy": wakeup.requested_by_actor_type or "system",
            "actorId": wakeup.requested_by_actor_id or "parent_yield",
            "forceFreshSession": False,
            "releasedByParentYield": True,
            **self._payload_context(payload),
            **(deferred_context if isinstance(deferred_context, dict) else {}),
        }
        context_snapshot = await self._enrich_issue_context_snapshot(context_snapshot)
        run = await create_run(
            self._session,
            {
                "org_id": agent.org_id,
                "agent_id": agent.id,
                "invocation_source": wakeup.source,
                "run_purpose": (
                    retry_run_purpose
                    if isinstance(retry_run_purpose, str)
                    else _run_purpose(wakeup.source, context_snapshot)
                ),
                "trigger_detail": wakeup.trigger_detail,
                "status": "queued",
                "wakeup_request_id": wakeup.id,
                "retry_of_run_id": (
                    retry_of_run_id if isinstance(retry_of_run_id, str) else None
                ),
                "process_loss_retry_count": (
                    retry_process_loss_count
                    if isinstance(retry_process_loss_count, int)
                    and not isinstance(retry_process_loss_count, bool)
                    else 0
                ),
                "context_snapshot": context_snapshot,
            },
        )
        run = await self._initialize_run_log(run)
        await update_wakeup_request(
            self._session,
            wakeup.id,
            {
                "status": "queued",
                "payload": payload,
                "run_id": run.id,
                "claimed_at": None,
                "finished_at": None,
                "error": None,
            },
        )
        issue_id = _issue_id_from_context(context_snapshot)
        issue = await get_issue_by_id(self._session, issue_id) if issue_id else None
        await self._claim_issue_execution_for_task_run(
            agent,
            run,
            context_snapshot,
            issue=issue,
        )
        await self._append_event(
            run,
            1,
            "lifecycle",
            stream="system",
            message="run queued after parent yielded execution",
            level="info",
            payload={
                "status": "queued",
                "source": wakeup.source,
                "triggerDetail": wakeup.trigger_detail,
                "releasedByParentYield": True,
            },
        )
        return run

    async def _create_queued_run(
        self,
        agent: AgentRow,
        payload: WakeAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> HeartbeatRunRow | None:
        wakeup, created = await create_wakeup_request_idempotent(
            self._session,
            self._wakeup_values(
                agent,
                payload,
                actor_type=actor_type,
                actor_id=actor_id,
                status="queued",
            ),
        )
        if not created:
            self.last_wakeup_reused = True
            if wakeup.run_id:
                return await get_run(self._session, wakeup.run_id)
            return None
        context_snapshot = {
            "triggeredBy": actor_type,
            "actorId": actor_id,
            "forceFreshSession": payload.get("forceFreshSession", False),
            **self._payload_context(payload.get("payload")),
            **self._payload_context_snapshot(payload.get("contextSnapshot")),
        }
        context_snapshot = await self._enrich_issue_context_snapshot(context_snapshot)
        run = await create_run(
            self._session,
            {
                "org_id": agent.org_id,
                "agent_id": agent.id,
                "invocation_source": payload.get("source", "on_demand"),
                "run_purpose": _run_purpose(
                    payload.get("source", "on_demand"), context_snapshot
                ),
                "trigger_detail": payload.get("triggerDetail", "manual"),
                "status": "queued",
                "wakeup_request_id": wakeup.id,
                "context_snapshot": context_snapshot,
            },
        )
        run = await self._initialize_run_log(run)
        await update_wakeup_request(self._session, wakeup.id, {"run_id": run.id})
        await self._claim_issue_execution_for_task_run(agent, run, context_snapshot)
        await self._append_event(
            run,
            1,
            "lifecycle",
            stream="system",
            message="run queued",
            level="info",
            payload={
                "status": "queued",
                "source": payload.get("source", "on_demand"),
                "triggerDetail": payload.get("triggerDetail", "manual"),
            },
        )
        return run

    async def _start_if_capacity(
        self, agent: AgentRow, queued_run: HeartbeatRunRow
    ) -> HeartbeatRunRow:
        lock = self._start_locks.setdefault(agent.id, asyncio.Lock())
        async with lock:
            active = self._active_run_ids.setdefault(agent.id, set())
            persisted = await list_running_run_ids(self._session, agent.id)
            if len(persisted | active) >= self._max_concurrent_runs(agent):
                return queued_run
            claimed = await claim_queued_run(
                self._session, queued_run.id, datetime.now(UTC)
            )
            if claimed is None:
                current = await get_run(self._session, queued_run.id)
                assert current is not None
                return current
            active.add(claimed.id)
        try:
            await self._prepare_execution(agent, claimed)
            return await self._execute_run(agent, claimed, prepared=True)
        finally:
            active.discard(claimed.id)

    async def _execute_run(
        self, agent: AgentRow, running: HeartbeatRunRow, *, prepared: bool = False
    ) -> HeartbeatRunRow:
        if not prepared:
            sequence = await self._prepare_execution(agent, running)
        else:
            sequence = await self._next_event_sequence(running.id)
        cancellation = asyncio.Event()
        self._cancel_events[running.id] = cancellation

        stdout = ""
        stderr = ""
        adapter_operation: object | None = None
        runtime_callback_lock = asyncio.Lock()
        adapter_started_at = datetime.now(UTC)
        last_runtime_output_at = adapter_started_at
        silence_timeout_seconds = (
            self.RUNTIME_NO_OUTPUT_TIMEOUT_SECONDS
            if agent.agent_runtime_type in STREAMING_LOCAL_RUNTIMES
            else 0.0
        )
        silence_timeout_error: str | None = None

        async def on_log(stream: str, chunk: str) -> None:
            nonlocal sequence, stdout, stderr, last_runtime_output_at
            async with runtime_callback_lock:
                last_runtime_output_at = datetime.now(UTC)
                if stream == "stdout":
                    stdout += chunk
                else:
                    stderr += chunk
                if isinstance(adapter_operation, dict) and isinstance(
                    adapter_operation.get("id"), str
                ):
                    await WorkspaceService(self._session).append_operation_log(
                        adapter_operation["id"],
                        stream=stream,
                        chunk=chunk,
                    )
                await self._append_run_log(running, stream=stream, chunk=chunk)
                await self._append_event(
                    running,
                    sequence,
                    "log",
                    message=chunk,
                    stream=stream,
                    level="info" if stream == "stdout" else "error",
                )
                sequence += 1
                await self._commit_background_runtime_progress()

        async def on_process_started(pid: int, started_at: datetime) -> None:
            nonlocal sequence, running
            async with runtime_callback_lock:
                updated = await update_run(
                    self._session,
                    running.id,
                    {"process_pid": pid, "process_started_at": started_at},
                )
                if updated is not None:
                    running = updated
                    await self._append_event(
                        updated,
                        sequence,
                        "lifecycle",
                        message=f"child process spawned with pid {pid}",
                        level="info",
                        payload={
                            "processPid": pid,
                            "processStartedAt": started_at.isoformat(),
                        },
                    )
                    sequence += 1
                await self._commit_background_runtime_progress()

        async def on_stream_event(event: dict[str, Any]) -> None:
            nonlocal sequence
            if event.get("type") != "runtime_progress":
                return
            message = event.get("message")
            if not isinstance(message, str) or not message.strip():
                return
            async with runtime_callback_lock:
                await self._append_event(
                    running,
                    sequence,
                    "runtime.progress",
                    message=message.strip(),
                    level="info",
                    payload=event,
                )
                sequence += 1
                await self._commit_background_runtime_progress()

        async def on_process_exited(
            pid: int, exit_code: int | None, exited_at: datetime
        ) -> None:
            nonlocal sequence, running
            async with runtime_callback_lock:
                updated = await update_run(
                    self._session,
                    running.id,
                    {"process_exited_at": exited_at},
                )
                if updated is not None:
                    running = updated
                    await self._append_event(
                        updated,
                        sequence,
                        "lifecycle",
                        message=f"child process exited with code {exit_code}",
                        level="info" if exit_code == 0 else "error",
                        payload={
                            "processPid": pid,
                            "processExitCode": exit_code,
                            "processExitedAt": exited_at.isoformat(),
                        },
                    )
                    sequence += 1
                await self._commit_background_runtime_progress()

        async def emit_runtime_progress() -> None:
            nonlocal sequence, running
            async with runtime_callback_lock:
                if running.execution_owner_token:
                    await self._session.refresh(running)
                    renewed = await renew_run_execution_lease(
                        self._session,
                        running.id,
                        running.execution_owner_token,
                    )
                    if not renewed:
                        await self._session.refresh(running)
                        if running.status == "cancelled":
                            cancellation.set()
                            return
                        raise RuntimeError("Run execution lease was lost")
                    refreshed = await get_run(self._session, running.id)
                    if refreshed is not None:
                        running = refreshed
                payload: dict[str, Any] = {
                    "elapsedSeconds": max(
                        0, int((datetime.now(UTC) - adapter_started_at).total_seconds())
                    )
                }
                if running.process_pid is not None:
                    payload["processPid"] = running.process_pid
                if running.process_started_at is not None:
                    payload["processStartedAt"] = running.process_started_at.isoformat()
                await self._append_event(
                    running,
                    sequence,
                    "runtime.progress",
                    message="runtime still running",
                    stream="system",
                    level="info",
                    payload=payload,
                )
                sequence += 1
                await self._commit_background_runtime_progress()

        async def execute_adapter_with_progress(
            context: RuntimeExecutionContext,
        ):
            nonlocal silence_timeout_error
            interval = self.RUNTIME_PROGRESS_INTERVAL_SECONDS
            if interval <= 0:
                return await adapter.execute(context)
            task = asyncio.create_task(adapter.execute(context))
            stop_requested_at: datetime | None = None
            try:
                while True:
                    done, _ = await asyncio.wait({task}, timeout=interval)
                    if task in done:
                        return task.result()
                    if cancellation.is_set():
                        if stop_requested_at is None:
                            stop_requested_at = datetime.now(UTC)
                        if (
                            datetime.now(UTC) - stop_requested_at
                        ).total_seconds() >= self.PARENT_ADAPTER_STOP_GRACE_SECONDS:
                            task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await task
                            return RuntimeExecutionResult(
                                exit_code=None,
                                signal="parent_yield",
                                error_message="Run stopped for child handoff",
                            )
                        continue
                    if (
                        silence_timeout_error is None
                        and silence_timeout_seconds > 0
                        and (datetime.now(UTC) - last_runtime_output_at).total_seconds()
                        >= silence_timeout_seconds
                    ):
                        silence_timeout_error = (
                            "Runtime produced no output for "
                            f"{silence_timeout_seconds:g}s"
                        )
                        cancellation.set()
                        continue
                    await emit_runtime_progress()
            except asyncio.CancelledError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise

        try:
            adapter = get_runtime_adapter(agent.agent_runtime_type)
            try:
                workspace_context = await self._prepare_workspace_for_execution(
                    agent, running
                )
            except Exception as exc:
                raise WorkspacePreparationError(_exception_message(exc)) from exc
            sequence = await self._next_event_sequence(running.id)
            await self._append_event(
                running,
                sequence,
                "adapter.invoke",
                message="adapter invocation",
                level="info",
                payload={"agentRuntimeType": agent.agent_runtime_type},
            )
            sequence += 1
            adapter_operation = await self._begin_adapter_workspace_operation(
                running, workspace_context
            )
            runtime_config = await prepare_agent_runtime_config(
                self._session,
                agent,
                extra_octopus={
                    "agentName": agent.name,
                    "context": running.context_snapshot or {},
                    "sessionIdBefore": running.session_id_before,
                    "desiredSkills": await list_enabled_skill_keys(
                        self._session, agent.id
                    ),
                },
            )
            configured_silence_timeout = runtime_config.get("noOutputTimeoutSec")
            if isinstance(configured_silence_timeout, (int, float)) and not isinstance(
                configured_silence_timeout, bool
            ):
                silence_timeout_seconds = max(0.0, float(configured_silence_timeout))
            workspace_env = None
            workspace_payload = None
            if workspace_context is not None:
                workspace_payload = workspace_context.get("workspace")
                env_payload = (
                    workspace_payload.get("env")
                    if isinstance(workspace_payload, dict)
                    else None
                )
                workspace_env = (
                    cast(dict[str, str], env_payload)
                    if isinstance(env_payload, dict)
                    else None
                )
                workspace_data = (
                    workspace_payload.get("octopusWorkspace")
                    if isinstance(workspace_payload, dict)
                    else None
                )
                if isinstance(workspace_data, dict) and isinstance(
                    workspace_data.get("cwd"), str
                ):
                    runtime_config["cwd"] = workspace_data["cwd"]
            runtime_config = await inject_runtime_provider_config(
                self._session,
                org_id=agent.org_id,
                runtime_type=agent.agent_runtime_type,
                config=runtime_config,
            )
            await self._commit_background_runtime_progress()
            result = await execute_adapter_with_progress(
                RuntimeExecutionContext(
                    run_id=running.id,
                    agent_id=agent.id,
                    org_id=agent.org_id,
                    agent_name=agent.name,
                    config=runtime_config,
                    on_log=on_log,
                    env=workspace_env,
                    workspace=(
                        cast(dict[str, Any], workspace_payload)
                        if isinstance(workspace_payload, dict)
                        else None
                    ),
                    cancel_event=cancellation,
                    on_process_started=on_process_started,
                    on_process_exited=on_process_exited,
                    on_stream_event=on_stream_event,
                )
            )
            await self._finish_adapter_workspace_operation(
                adapter_operation,
                status=(
                    "succeeded"
                    if not result.error_message and silence_timeout_error is None
                    else "failed"
                ),
                exit_code=result.exit_code,
                stdout_excerpt=stdout or None,
                stderr_excerpt=stderr or silence_timeout_error or result.error_message,
                metadata={
                    "adapterExecution": True,
                    "timedOut": result.timed_out or silence_timeout_error is not None,
                },
            )
            await self._session.refresh(running)
            if cancellation.is_set() and silence_timeout_error is None:
                return running
            if running.status == "cancelled":
                return running
            final_status: HeartbeatRunStatus
            if result.timed_out or silence_timeout_error is not None:
                final_status = "timed_out"
            elif result.error_message or (result.exit_code or 0) != 0:
                final_status = "failed"
            else:
                final_status = "succeeded"
            runtime_services = await WorkspaceService(
                self._session
            ).persist_adapter_runtime_services(
                run_id=running.id,
                agent_id=agent.id,
                agent_runtime_type=agent.agent_runtime_type,
                context_snapshot=running.context_snapshot,
                reports=result.runtime_services,
            )
            work_products: list[Any] = []
            try:
                work_products = await WorkspaceService(
                    self._session
                ).persist_run_work_products(
                    run_id=running.id,
                    context_snapshot=running.context_snapshot,
                    products=result.work_products,
                )
                # Capture generated files for any terminal status, not only
                # success: a run that crashed mid-way (e.g. ENOSPC) may have
                # already produced deliverables that must still be registered.
                if final_status in ("succeeded", "failed", "timed_out"):
                    work_products.extend(
                        await WorkspaceService(
                            self._session
                        ).persist_generated_workspace_files(
                            run_id=running.id,
                            context_snapshot=running.context_snapshot,
                            since=running.started_at,
                        )
                    )
                work_products = _dedupe_work_product_payloads(work_products)
            except Exception as wp_exc:  # noqa: BLE001
                # Work-product capture is best-effort and must never override the
                # run's real outcome nor abort finalization. The capture is
                # idempotent, so the next run of this issue backfills any miss.
                work_products = []
                await self._append_run_log(
                    running,
                    stream="stderr",
                    chunk=(
                        "[octopus] work-product capture failed: "
                        f"{_exception_message(wp_exc)}\n"
                    ),
                )
            closeout_error: str | None = None
            if final_status == "succeeded":
                issue_id = _issue_id_from_context(running.context_snapshot or {})
                issue = (
                    await get_issue_by_id(self._session, issue_id)
                    if issue_id is not None
                    else None
                )
                if issue is not None and issue.org_id == running.org_id:
                    parent_closeout = await self.finalizer.validate_parent_closeout(
                        running, issue
                    )
                    if parent_closeout.applicable and not parent_closeout.completed:
                        closeout_error = parent_closeout.error or (
                            "Parent closeout validation failed"
                        )
                        final_status = "failed"
                    elif not parent_closeout.applicable:
                        issue_completion = (
                            await self.finalizer.validate_issue_completion(
                                running, issue
                            )
                        )
                        if (
                            issue_completion.applicable
                            and not issue_completion.completed
                        ):
                            closeout_error = issue_completion.error or (
                                "Issue completion output validation failed"
                            )
                            final_status = "failed"
            final = await self.finalizer.transition(
                running.id,
                final_status,
                {
                    "finished_at": datetime.now(UTC),
                    "error": (
                        closeout_error or silence_timeout_error or result.error_message
                    ),
                    "error_code": (
                        "timeout"
                        if final_status == "timed_out"
                        else "closeout_missing"
                        if closeout_error is not None
                        else "adapter_failed"
                        if final_status == "failed"
                        else None
                    ),
                    "exit_code": result.exit_code,
                    "signal": result.signal,
                    "usage_json": result.usage_json,
                    "session_id_after": result.session_id_after,
                    **self._finalize_run_log_fields(running),
                    "result_json": {
                        **(result.result_json or {}),
                        **(
                            {"runtimeServices": runtime_services}
                            if runtime_services
                            else {}
                        ),
                        **({"workProducts": work_products} if work_products else {}),
                    }
                    if result.result_json or runtime_services or work_products
                    else None,
                    "stdout_excerpt": stdout or None,
                    "stderr_excerpt": stderr or silence_timeout_error or closeout_error,
                },
                expected_owner_token=running.execution_owner_token,
            )
            if final is None:
                current = await get_run(self._session, running.id)
                if current is None:
                    raise RuntimeError("Run disappeared during terminal transition")
                if current.status not in {
                    "succeeded",
                    "failed",
                    "timed_out",
                    "cancelled",
                }:
                    raise RuntimeError("Run execution lease was lost")
                final = current
                final_status = cast(HeartbeatRunStatus, current.status)
            await self._commit_background_runtime_progress()
            return await self._complete_finalized_run(
                agent=agent,
                running=running,
                final=final,
                final_status=final_status,
                result=result,
                sequence=sequence,
            )
        except Exception as exc:
            if cancellation.is_set():
                return running
            message = _exception_message(exc)
            error_code = (
                "workspace_prepare_failed"
                if isinstance(exc, WorkspacePreparationError)
                else "adapter_failed"
            )
            try:
                await self._session.refresh(running)
                if running.status in {
                    "succeeded",
                    "failed",
                    "timed_out",
                    "cancelled",
                }:
                    if running.terminal_effects_pending:
                        return await self._reconcile_terminal_effects(running)
                    return running
                await self._append_run_log(running, stream="stderr", chunk=message)
                await self._finish_adapter_workspace_operation(
                    locals().get("adapter_operation"),
                    status="failed",
                    stderr_excerpt=message,
                    metadata={"error": message},
                )
                failed = await self.finalizer.transition(
                    running.id,
                    "failed",
                    {
                        "finished_at": datetime.now(UTC),
                        "error": message,
                        "error_code": error_code,
                        **self._finalize_run_log_fields(running),
                        "stdout_excerpt": stdout or None,
                        "stderr_excerpt": stderr or None,
                    },
                    expected_owner_token=running.execution_owner_token,
                )
                if failed is None:
                    current = await get_run(self._session, running.id)
                    if current is None:
                        raise RuntimeError(
                            "Run disappeared during failure finalization"
                        )
                    return current
                await self._commit_background_runtime_progress()
                return await self._reconcile_terminal_effects(
                    failed, result=None, sequence=sequence
                )
            except Exception as finalization_exc:
                raise RunExecutionFinalizationError(
                    run_id=running.id,
                    message=message,
                    error_code=error_code,
                ) from finalization_exc
        finally:
            self._cancel_events.pop(running.id, None)

    async def _complete_finalized_run(
        self,
        *,
        agent: AgentRow,
        running: HeartbeatRunRow,
        final: HeartbeatRunRow,
        final_status: HeartbeatRunStatus,
        result: Any,
        sequence: int,
    ) -> HeartbeatRunRow:
        return await self.finalizer.complete(
            agent=agent,
            running=running,
            final=final,
            final_status=final_status,
            result=result,
            sequence=sequence,
        )

    async def _complete_finalized_run_impl(
        self,
        *,
        agent: AgentRow,
        running: HeartbeatRunRow,
        final: HeartbeatRunRow,
        final_status: HeartbeatRunStatus,
        result: Any,
        sequence: int,
    ) -> HeartbeatRunRow:
        if not final.terminal_effects_pending:
            compatibility_final = await update_run(
                self._session,
                final.id,
                {
                    "terminal_effects_pending": True,
                    "terminal_effects_json": {
                        "version": 1,
                        "source": "legacy_complete_finalized_run",
                    },
                    "terminal_effects_next_attempt_at": None,
                    "terminal_effects_claim_token": None,
                    "terminal_effects_claimed_at": None,
                    "terminal_effects_last_error": None,
                },
            )
            if compatibility_final is not None:
                final = compatibility_final
        return await self._reconcile_terminal_effects(
            final, result=result, sequence=sequence
        )

    async def _reconcile_terminal_effects(
        self,
        run: HeartbeatRunRow,
        *,
        result: Any | None = None,
        sequence: int | None = None,
    ) -> HeartbeatRunRow:
        return await self.finalizer.reconcile(
            run,
            result=result,
            sequence=sequence,
        )

    async def _reconcile_terminal_effects_impl(
        self,
        run: HeartbeatRunRow,
        *,
        result: Any | None = None,
        sequence: int | None = None,
    ) -> HeartbeatRunRow:
        claimed = await claim_run_terminal_effects(self._session, run.id)
        if claimed is None:
            current = await get_run(self._session, run.id)
            return current or run
        claim_token = claimed.terminal_effects_claim_token
        assert claim_token is not None
        final = claimed
        try:
            agent = (
                await self._session.execute(
                    select(AgentRow)
                    .where(AgentRow.id == final.agent_id)
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if agent is None:
                raise RuntimeError("Run agent no longer exists")
            if sequence is None:
                sequence = await self._next_event_sequence(final.id)
            final_status = cast(HeartbeatRunStatus, final.status)
            if final_status == "succeeded":
                final = await self._enforce_closeout_governance_success(agent, final)
                final_status = cast(HeartbeatRunStatus, final.status)
            try:
                await CostService(self._session).record_run_cost_if_present(final.id)
            except Exception as exc:
                await self._append_event(
                    final,
                    sequence,
                    "cost.collection_failed",
                    message=f"Cost collection failed: {_exception_message(exc)}",
                    level="warning",
                    payload={
                        "error": _exception_message(exc),
                        "errorType": type(exc).__name__,
                    },
                    idempotency_key="terminal-effect:cost-collection-failed",
                )
                sequence += 1
            if final.wakeup_request_id:
                final_context = (
                    final.context_snapshot
                    if isinstance(final.context_snapshot, dict)
                    else {}
                )
                wakeup_terminal_values: dict[str, Any] = {
                    "status": "completed"
                    if final_status == "succeeded"
                    else final_status,
                    "finished_at": final.finished_at or datetime.now(UTC),
                    "error": final.error or getattr(result, "error_message", None),
                }
                if final_context.get("wakeReason") == "runtime_diagnostic":
                    wakeup_terminal_values["idempotency_key"] = None
                await update_wakeup_request(
                    self._session,
                    final.wakeup_request_id,
                    wakeup_terminal_values,
                )
            await self._update_runtime_state(agent, final)
            if agent.status == "running" and not await list_running_run_ids(
                self._session, agent.id
            ):
                await update_agent(
                    self._session,
                    agent.id,
                    {
                        "status": "idle"
                        if final_status in {"succeeded", "cancelled"}
                        else "error"
                    },
                )
            if final_status == "failed":
                await self._reconcile_failed_done_issue(agent, final)
            await self.finalizer.restore_system_blocked_issue_after_recovery(final)
            await self._release_issue_execution(final)
            context_after_final = (
                final.context_snapshot
                if isinstance(final.context_snapshot, dict)
                else {}
            )
            should_check_followup_after_closeout_failure = (
                final.error_code == "closeout_missing"
                and context_after_final.get("wakeReason")
                not in {ISSUE_PASSIVE_FOLLOWUP_REASON, "issue_review_closeout_missing"}
            )
            if (
                final_status == "succeeded"
                or should_check_followup_after_closeout_failure
            ):
                await self._queue_issue_passive_followup_if_needed(agent, final)
            await self._append_event(
                final,
                sequence,
                "error" if final_status == "failed" and result is None else "lifecycle",
                message=(
                    final.error
                    if final_status == "failed" and result is None and final.error
                    else f"run {final_status}"
                ),
                level=("info" if final_status == "succeeded" else "error"),
                idempotency_key=f"terminal-effect:outcome:{final_status}",
            )
            workspace_service = WorkspaceService(self._session)
            if final_status in {"failed", "timed_out", "cancelled"}:
                await workspace_service.mark_run_workspace_interrupted(
                    final.id,
                    reason=final.error_code or final_status,
                    message=final.error or f"run {final_status}",
                )
            else:
                await workspace_service.release_runtime_services_for_run(final.id)
            completed = await complete_run_terminal_effects(
                self._session,
                final.id,
                claim_token,
                [
                    "wakeup",
                    "runtime_state",
                    "agent_status",
                    "issue_release",
                    "workspace_release",
                    "lifecycle_event",
                ],
            )
            return completed or final
        except Exception as exc:
            message = _exception_message(exc)
            with contextlib.suppress(Exception):
                await self._append_event(
                    final,
                    sequence or await self._next_event_sequence(final.id),
                    "postprocess.warning",
                    message=message,
                    level="warning",
                    payload={
                        "error": message,
                        "errorType": type(exc).__name__,
                        "runStatusPreserved": final.status,
                    },
                    idempotency_key="terminal-effect:postprocess-warning",
                )
            with contextlib.suppress(Exception):
                await fail_run_terminal_effects(
                    self._session, final.id, claim_token, message
                )
            current = await get_run(self._session, final.id)
            return current or final

    async def _prepare_execution(
        self, agent: AgentRow, running: HeartbeatRunRow
    ) -> int:
        now = datetime.now(UTC)
        locked_agent = (
            await self._session.execute(
                select(AgentRow).where(AgentRow.id == agent.id).with_for_update()
            )
        ).scalar_one_or_none()
        if locked_agent is None:
            raise RuntimeError("Run agent no longer exists")
        agent = locked_agent
        restored_issue = await self._restore_system_blocked_issue_for_execution(running)
        if not restored_issue:
            await self.finalizer.restore_system_blocked_issue_after_recovery(running)
        await update_wakeup_request(
            self._session,
            running.wakeup_request_id or "",
            {"status": "claimed", "claimed_at": now},
        )
        await update_agent(
            self._session, agent.id, {"status": "running", "last_heartbeat_at": now}
        )
        sequence = await self._next_event_sequence(running.id)
        await self._append_event(
            running, sequence, "lifecycle", message="run started", level="info"
        )
        return sequence + 1

    async def finalize_unhandled_execution_failure(
        self, failure: RunExecutionFinalizationError
    ) -> HeartbeatRun | None:
        """Finalize a Run using the caller's clean replacement session."""

        running = await get_run(self._session, failure.run_id)
        if running is None:
            return None
        if running.status in {
            "succeeded",
            "failed",
            "timed_out",
            "cancelled",
        }:
            if running.terminal_effects_pending:
                reconciled = await self._reconcile_terminal_effects(running)
                await self._session.commit()
                return self._to_run(reconciled)
            return self._to_run(running)

        message = str(failure)
        await self._append_run_log(running, stream="stderr", chunk=message)
        failed = await self.finalizer.transition(
            running.id,
            "failed",
            {
                "finished_at": datetime.now(UTC),
                "error": message,
                "error_code": failure.error_code,
                **self._finalize_run_log_fields(running),
                "stderr_excerpt": message,
            },
            expected_owner_token=running.execution_owner_token,
        )
        if failed is None:
            current = await get_run(self._session, running.id)
            return self._to_run(current) if current is not None else None

        # The authoritative terminal state must commit before recoverable,
        # idempotent terminal effects run in their own transaction.
        await self._session.commit()
        reconciled = await self._reconcile_terminal_effects(failed)
        await self._session.commit()
        return self._to_run(reconciled)

    async def _prepare_workspace_context(
        self, agent: AgentRow, running: HeartbeatRunRow
    ) -> dict[str, Any] | None:
        workspace_context = await WorkspaceService(
            self._session
        ).prepare_runtime_context_for_heartbeat(
            running.id,
            running.context_snapshot,
            org_id=agent.org_id,
            agent_workspace_key=(agent.workspace_key or f"agent--{str(agent.id)[:8]}"),
        )
        next_snapshot = dict(running.context_snapshot or {})
        next_snapshot.update(workspace_context)
        updated = await update_run(
            self._session,
            running.id,
            {"context_snapshot": next_snapshot},
        )
        if updated is not None:
            running.context_snapshot = updated.context_snapshot
        workspace_payload = workspace_context.get("workspace")
        workspace_id = workspace_context.get("executionWorkspaceId")
        operation = await WorkspaceService(self._session).begin_operation(
            org_id=running.org_id,
            run_id=running.id,
            execution_workspace_id=(
                workspace_id if isinstance(workspace_id, str) else None
            ),
            phase="workspace_provision",
            cwd=(
                workspace_payload.get("octopusWorkspace", {}).get("cwd")
                if isinstance(workspace_payload, dict)
                and isinstance(workspace_payload.get("octopusWorkspace"), dict)
                else None
            ),
            metadata={
                "projectWorkspaceId": workspace_context.get("projectWorkspaceId"),
                "preflight": True,
            },
        )
        await WorkspaceService(self._session).finish_operation(
            operation["id"],
            status="succeeded",
            metadata={
                "projectWorkspaceId": workspace_context.get("projectWorkspaceId"),
                "preflight": True,
            },
        )
        await self._append_event(
            running,
            await self._next_event_sequence(running.id),
            "workspace.preflight",
            message="workspace context prepared",
            level="info",
            payload={
                "executionWorkspaceId": workspace_id,
                "projectWorkspaceId": workspace_context.get("projectWorkspaceId"),
            },
        )
        return workspace_context if isinstance(workspace_payload, dict) else None

    async def _prepare_workspace_for_execution(
        self, agent: AgentRow, running: HeartbeatRunRow
    ) -> dict[str, Any] | None:
        if self._session_factory is None:
            return await self._prepare_workspace_context(agent, running)
        agent_id = agent.id
        run_id = running.id
        org_id = agent.org_id
        # The planning reads above must not keep an old SQLite snapshot while a
        # separate short Workspace transaction commits. End that read segment,
        # then make every following execution segment reserve its writer slot
        # before reading current Run state.
        await self._session.commit()
        workspace_context = await WorkspacePreparationCoordinator(
            self._session_factory
        ).prepare(agent_id=agent_id, run_id=run_id, org_id=org_id)
        enable_write_transactions(self._session)
        await self._session.refresh(running)
        if running.status != "running":
            raise RuntimeError(
                f"Run left running state during workspace preparation: {running.status}"
            )
        return workspace_context

    async def _begin_adapter_workspace_operation(
        self, running: HeartbeatRunRow, workspace_context: dict[str, Any] | None
    ) -> object | None:
        if workspace_context is None:
            return None
        workspace_payload = workspace_context.get("workspace")
        workspace = (
            workspace_payload.get("octopusWorkspace")
            if isinstance(workspace_payload, dict)
            else None
        )
        return await WorkspaceService(self._session).begin_operation(
            org_id=running.org_id,
            run_id=running.id,
            execution_workspace_id=cast(
                str | None, workspace_context.get("executionWorkspaceId")
            ),
            phase="workspace_provision",
            command="runtime_adapter.execute",
            cwd=workspace.get("cwd") if isinstance(workspace, dict) else None,
            metadata={
                "adapterExecution": True,
            },
        )

    async def _finish_adapter_workspace_operation(
        self,
        operation: object,
        *,
        status: str,
        exit_code: int | None = None,
        stdout_excerpt: str | None = None,
        stderr_excerpt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not isinstance(operation, dict) or not isinstance(operation.get("id"), str):
            return
        await WorkspaceService(self._session).finish_operation(
            operation["id"],
            status=status,
            exit_code=exit_code,
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
            metadata=metadata,
        )

    async def _queue_issue_passive_followup_if_needed(
        self, agent: AgentRow, final: HeartbeatRunRow
    ) -> None:
        context = (
            final.context_snapshot if isinstance(final.context_snapshot, dict) else {}
        )
        if context.get("wakeReason") == "issue_review_closeout_missing":
            issue_id = _issue_id_from_context(context)
            if issue_id is not None:
                issue = await get_issue_by_id(self._session, issue_id)
                if issue is not None and issue.org_id == final.org_id:
                    await self._record_issue_review_closeout_missing(
                        final, issue, context
                    )
            return
        issue_id = _issue_id_from_context(context)
        if issue_id is None:
            return
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None or issue.org_id != final.org_id:
            return
        if self._is_reviewer_issue_run(agent, final, issue, context):
            await self._queue_issue_review_closeout_if_needed(agent, final, issue)
            return
        if issue.assignee_agent_id != agent.id or issue.status not in {
            "todo",
            "in_progress",
        }:
            return
        if await self._issue_has_active_children(issue.id):
            return

        issue_has_reviewer = bool(issue.reviewer_agent_id or issue.reviewer_user_id)
        if await self._run_has_issue_closeout_signal(
            final, issue.id, issue_has_reviewer=issue_has_reviewer
        ):
            return
        if await self._issue_has_user_intervention_after(
            issue, final.finished_at or final.created_at
        ):
            return
        passive_followup = _passive_followup_context(context)
        raw_attempt = passive_followup.get("attempt")
        current_attempt = (
            raw_attempt
            if isinstance(raw_attempt, int) and not isinstance(raw_attempt, bool)
            else 0
        )
        raw_origin_run_id = passive_followup.get("originRunId")
        origin_run_id = (
            raw_origin_run_id if isinstance(raw_origin_run_id, str) else final.id
        )
        if current_attempt >= ISSUE_PASSIVE_FOLLOWUP_MAX_ATTEMPTS:
            await self._record_issue_closure_convergence_needed(
                final,
                issue,
                origin_run_id=origin_run_id,
                attempts=current_attempt,
            )
            return
        next_attempt = current_attempt + 1
        idempotency_key = f"{ISSUE_PASSIVE_FOLLOWUP_REASON}:{final.id}"
        existing = await get_wakeup_by_idempotency_key(
            self._session, agent.id, idempotency_key
        )
        if existing is not None:
            return
        await create_wakeup_request_idempotent(
            self._session,
            self._wakeup_values(
                agent,
                {
                    "source": "automation",
                    "triggerDetail": "system",
                    "reason": ISSUE_PASSIVE_FOLLOWUP_REASON,
                    "idempotencyKey": idempotency_key,
                    "requestedAt": datetime.now(UTC) + _issue_passive_followup_delay(),
                    "payload": {
                        "issueId": issue.id,
                        "originRunId": origin_run_id,
                        "previousRunId": final.id,
                        "attempt": next_attempt,
                        "reason": ISSUE_PASSIVE_FOLLOWUP_FAILURE_REASON,
                    },
                },
                actor_type="system",
                actor_id="heartbeat_closeout_governance",
                status="scheduled",
            ),
        )

    async def _enforce_closeout_governance_success(
        self, agent: AgentRow, final: HeartbeatRunRow
    ) -> HeartbeatRunRow:
        context = (
            final.context_snapshot if isinstance(final.context_snapshot, dict) else {}
        )
        wake_reason = context.get("wakeReason")
        issue_id = _issue_id_from_context(context)
        if issue_id is None:
            return final
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None or issue.org_id != final.org_id:
            return final
        parent_closeout = await self.finalizer.finalize_parent_closeout(final, issue)
        if parent_closeout.applicable:
            if parent_closeout.completed:
                return final
            # A recovered legacy terminal Run is immutable. New Runs validate
            # this evidence before their terminal CAS; Recovery only reports
            # missing effects and never rewrites an authoritative terminal state.
            return final
        issue_completion = await self.finalizer.finalize_issue_completion(final, issue)
        if issue_completion.applicable:
            return final
        if issue.assignee_agent_id == agent.id and issue.status == "done":
            has_unresolved_blocked_child = (
                await self.parent_closeout.record_blocked_child_if_needed(final, issue)
            )
            if has_unresolved_blocked_child:
                return await self._mark_closeout_governance_failed(
                    final,
                    "Parent issue was marked done while child issues are blocked or cancelled.",
                )
            missing_expected = (
                await self._record_done_missing_expected_work_product_if_needed(
                    final, issue
                )
            )
            if missing_expected:
                return await self._mark_closeout_governance_failed(
                    final,
                    "Issue was marked done without the required work product.",
                )
            return final
        if self._is_reviewer_issue_run(agent, final, issue, context):
            if await self._run_has_issue_activity(
                final, issue.id, ("issue.review_decision_recorded",)
            ):
                return final
            await self._record_issue_review_closeout_missing(final, issue, context)
            return await self._mark_closeout_governance_failed(
                final,
                "Reviewer issue run exited without `octopus issue review`.",
            )
        if wake_reason == "issue_review_closeout_missing":
            if await self._run_has_issue_activity(
                final, issue.id, ("issue.review_decision_recorded",)
            ):
                return final
            await self._record_issue_review_closeout_missing(final, issue, context)
            return await self._mark_closeout_governance_failed(
                final,
                "Reviewer close-out run exited without `octopus issue review`.",
            )
        if issue.assignee_agent_id != agent.id or issue.status not in {
            "todo",
            "in_progress",
        }:
            return final
        if await self._issue_has_active_children(issue.id):
            await insert_activity_log(
                self._session,
                org_id=issue.org_id,
                actor_type="system",
                actor_id="heartbeat_child_coordination",
                action="issue.children_running",
                entity_type="issue",
                entity_id=issue.id,
                agent_id=final.agent_id,
                run_id=final.id,
                details={"runId": final.id},
            )
            return final
        if (
            wake_reason == "issue_children_settled"
            and await self.parent_closeout.block_for_unresolved_children(final, issue)
        ):
            return final
        issue_has_reviewer = bool(issue.reviewer_agent_id or issue.reviewer_user_id)
        if await self._run_has_issue_closeout_signal(
            final, issue.id, issue_has_reviewer=issue_has_reviewer
        ):
            return final
        passive_followup = _passive_followup_context(context)
        raw_attempt = passive_followup.get("attempt")
        attempts = (
            raw_attempt
            if isinstance(raw_attempt, int) and not isinstance(raw_attempt, bool)
            else 1
        )
        raw_origin_run_id = passive_followup.get("originRunId")
        origin_run_id = (
            raw_origin_run_id if isinstance(raw_origin_run_id, str) else final.id
        )
        if wake_reason == ISSUE_PASSIVE_FOLLOWUP_REASON:
            if attempts >= ISSUE_PASSIVE_FOLLOWUP_MAX_ATTEMPTS:
                await self._record_issue_closure_convergence_needed(
                    final,
                    issue,
                    origin_run_id=origin_run_id,
                    attempts=attempts,
                )
            return await self._mark_closeout_governance_failed(
                final,
                (
                    "Issue close-out follow-up exited without "
                    "`octopus issue done`, `octopus issue block`, "
                    "or `octopus issue comment`."
                ),
            )
        if attempts >= ISSUE_PASSIVE_FOLLOWUP_MAX_ATTEMPTS:
            await self._record_issue_closure_convergence_needed(
                final,
                issue,
                origin_run_id=origin_run_id,
                attempts=attempts,
            )
        return await self._mark_closeout_governance_failed(
            final,
            (
                "Issue run exited without `octopus issue done`, "
                "`octopus issue block`, or `octopus issue comment`."
            ),
        )

    async def _mark_closeout_governance_failed(
        self, final: HeartbeatRunRow, message: str
    ) -> HeartbeatRunRow:
        updated = await update_run(
            self._session,
            final.id,
            {
                "status": "failed",
                "error": message,
                "error_code": "closeout_missing",
            },
        )
        assert updated is not None
        return updated

    async def _record_issue_closure_convergence_needed(
        self,
        final: HeartbeatRunRow,
        issue: IssueRow,
        *,
        origin_run_id: str,
        attempts: int,
    ) -> None:
        action = (
            "issue.convergence_review_requested"
            if issue.reviewer_agent_id or issue.reviewer_user_id
            else "issue.closure_needs_operator_review"
        )
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type="system",
            actor_id="issue_closure_governance",
            action=action,
            entity_type="issue",
            entity_id=issue.id,
            agent_id=final.agent_id,
            run_id=final.id,
            details={
                "issueId": issue.id,
                "issueTitle": issue.title,
                "reviewerAgentId": issue.reviewer_agent_id,
                "reviewerUserId": issue.reviewer_user_id,
                "originRunId": origin_run_id,
                "previousRunId": final.id,
                "attempts": attempts,
                "maxAttempts": ISSUE_PASSIVE_FOLLOWUP_MAX_ATTEMPTS,
                "reason": ISSUE_PASSIVE_FOLLOWUP_FAILURE_REASON,
            },
        )
        if not issue.reviewer_agent_id:
            return
        await self.wakeup(
            issue.reviewer_agent_id,
            {
                "source": "review",
                "triggerDetail": "system",
                "reason": "issue_convergence_review_requested",
                "idempotencyKey": f"issue_convergence_review_requested:{origin_run_id}",
                "payload": {
                    "issueId": issue.id,
                    "mutation": "passive_followup_exhausted",
                },
                "contextSnapshot": {
                    "issueId": issue.id,
                    "source": "issue.passive_followup_exhausted",
                    "wakeSource": "review",
                    "wakeReason": "issue_convergence_review_requested",
                    "role": "reviewer",
                    "convergenceReview": {
                        "originRunId": origin_run_id,
                        "previousRunId": final.id,
                        "attempts": attempts,
                        "maxAttempts": ISSUE_PASSIVE_FOLLOWUP_MAX_ATTEMPTS,
                        "reason": ISSUE_PASSIVE_FOLLOWUP_FAILURE_REASON,
                    },
                    "issue": {
                        "id": issue.id,
                        "title": issue.title,
                        "description": issue.description,
                        "status": issue.status,
                        "priority": issue.priority,
                    },
                    "reviewInstructions": (
                        "The assignee did not converge this issue after passive "
                        "follow-up. Review the thread and decide the next step: "
                        "request changes, mark blocked, escalate or reassign, or "
                        "mark done only if the evidence is sufficient."
                    ),
                },
            },
            actor_type="system",
            actor_id="issue_closure_governance",
            execute_immediately=False,
        )

    def _is_reviewer_issue_run(
        self,
        agent: AgentRow,
        final: HeartbeatRunRow,
        issue: IssueRow,
        context: dict[str, Any],
    ) -> bool:
        return (
            issue.status in {"in_review", "blocked"}
            and issue.reviewer_agent_id == agent.id
            and (
                final.invocation_source == "review"
                or context.get("role") == "reviewer"
                or context.get("wakeSource") == "review"
            )
        )

    async def _queue_issue_review_closeout_if_needed(
        self, agent: AgentRow, final: HeartbeatRunRow, issue: IssueRow
    ) -> None:
        if await self._run_has_issue_activity(
            final, issue.id, ("issue.review_decision_recorded",)
        ):
            return
        await self.wakeup(
            agent.id,
            {
                "source": "review",
                "triggerDetail": "system",
                "reason": "issue_review_closeout_missing",
                "idempotencyKey": f"issue:{issue.id}:review-closeout:{final.id}",
                "payload": {
                    "issueId": issue.id,
                    "originRunId": final.id,
                    "previousRunId": final.id,
                    "attempt": 1,
                    "reason": "review_outcome_missing",
                },
                "contextSnapshot": {
                    "issueId": issue.id,
                    "source": "issue.review_closeout_missing",
                    "wakeSource": "review",
                    "wakeReason": "issue_review_closeout_missing",
                    "role": "reviewer",
                    "reviewCloseout": {
                        "originRunId": final.id,
                        "previousRunId": final.id,
                        "attempt": 1,
                        "maxAttempts": 1,
                    },
                    "issue": {
                        "id": issue.id,
                        "title": issue.title,
                        "description": issue.description,
                        "status": issue.status,
                        "priority": issue.priority,
                    },
                    "reviewInstructions": (
                        "Your previous reviewer run ended without a structured "
                        "decision. Inspect the current issue state and record "
                        "exactly one outcome with `octopus issue review "
                        "--decision approve|request_changes|needs_followup|blocked "
                        "--comment ...`."
                    ),
                },
            },
            actor_type="system",
            actor_id="issue_review_closeout_governance",
            execute_immediately=False,
        )

    async def _record_issue_review_closeout_missing(
        self, final: HeartbeatRunRow, issue: IssueRow, context: dict[str, Any]
    ) -> None:
        if await self._run_has_issue_activity(
            final, issue.id, ("issue.review_decision_recorded",)
        ):
            return
        review_closeout = context.get("reviewCloseout")
        review_closeout = review_closeout if isinstance(review_closeout, dict) else {}
        raw_attempt = review_closeout.get("attempt")
        raw_max_attempts = review_closeout.get("maxAttempts")
        attempts = (
            raw_attempt
            if isinstance(raw_attempt, int) and not isinstance(raw_attempt, bool)
            else 1
        )
        max_attempts = (
            raw_max_attempts
            if isinstance(raw_max_attempts, int)
            and not isinstance(raw_max_attempts, bool)
            else 1
        )
        origin_run_id = review_closeout.get("originRunId")
        previous_run_id = review_closeout.get("previousRunId")
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type="system",
            actor_id="issue_review_closeout_governance",
            action="issue.review_closeout_missing",
            entity_type="issue",
            entity_id=issue.id,
            agent_id=final.agent_id,
            run_id=final.id,
            details={
                "issueId": issue.id,
                "issueTitle": issue.title,
                "reviewerAgentId": issue.reviewer_agent_id,
                "reviewerUserId": issue.reviewer_user_id,
                "originRunId": origin_run_id
                if isinstance(origin_run_id, str)
                else final.id,
                "previousRunId": previous_run_id
                if isinstance(previous_run_id, str)
                else final.id,
                "attempts": attempts,
                "maxAttempts": max_attempts,
                "reason": "review_outcome_missing",
            },
        )

    async def _reconcile_failed_done_issue(
        self, agent: AgentRow, final: HeartbeatRunRow
    ) -> None:
        context = (
            final.context_snapshot if isinstance(final.context_snapshot, dict) else {}
        )
        issue_id = _issue_id_from_context(context)
        if issue_id is None:
            return
        issue = await get_issue_by_id(self._session, issue_id)
        if (
            issue is None
            or issue.org_id != final.org_id
            or issue.assignee_agent_id != agent.id
        ):
            return
        if await self.finalizer.block_failed_issue_completion(final, issue):
            return
        if issue.status != "done":
            return
        missing_expected = (
            await self._record_done_missing_expected_work_product_if_needed(
                final, issue
            )
        )
        if not missing_expected:
            return
        await update_issue(
            self._session,
            issue.id,
            {
                "status": "blocked",
                "completed_at": None,
            },
        )

    async def _record_done_missing_expected_work_product_if_needed(
        self, final: HeartbeatRunRow, issue: IssueRow
    ) -> bool:
        expected_paths = _expected_work_product_paths(issue)
        if not expected_paths:
            return False
        result = await self._session.execute(
            select(IssueWorkProduct).where(
                and_(
                    IssueWorkProduct.org_id == issue.org_id,
                    IssueWorkProduct.issue_id == issue.id,
                    IssueWorkProduct.is_primary.is_(True),
                )
            )
        )
        for product in result.scalars().all():
            metadata = (
                product.metadata_json if isinstance(product.metadata_json, dict) else {}
            )
            workspace_path = metadata.get("workspacePath")
            candidates = {product.title}
            if isinstance(workspace_path, str):
                candidates.add(workspace_path)
            if any(candidate in expected_paths for candidate in candidates):
                return False
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type="system",
            actor_id="work_product_governance",
            action="issue.done_missing_work_product",
            entity_type="issue",
            entity_id=issue.id,
            agent_id=final.agent_id,
            run_id=final.id,
            details={
                "issueId": issue.id,
                "runId": final.id,
                "reason": "done_without_expected_work_product",
                "expectedPaths": sorted(expected_paths),
            },
        )
        return True

    async def _run_has_issue_closeout_signal(
        self,
        final: HeartbeatRunRow,
        issue_id: str,
        *,
        issue_has_reviewer: bool,
    ) -> bool:
        actions = ("issue.review_decision_recorded",)
        if not issue_has_reviewer:
            actions = ("issue.comment_added", "issue.review_decision_recorded")
        if await self._run_has_issue_activity(final, issue_id, actions):
            return True
        return await self._run_has_issue_status_closeout(final, issue_id)

    async def _run_has_issue_activity(
        self, final: HeartbeatRunRow, issue_id: str, actions: tuple[str, ...]
    ) -> bool:
        result = await self._session.execute(
            select(ActivityLog.id)
            .where(
                and_(
                    ActivityLog.org_id == final.org_id,
                    ActivityLog.run_id == final.id,
                    ActivityLog.entity_type == "issue",
                    ActivityLog.entity_id == issue_id,
                    ActivityLog.action.in_(actions),
                )
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _run_has_issue_status_closeout(
        self, final: HeartbeatRunRow, issue_id: str
    ) -> bool:
        result = await self._session.execute(
            select(ActivityLog.details)
            .where(
                and_(
                    ActivityLog.org_id == final.org_id,
                    ActivityLog.run_id == final.id,
                    ActivityLog.entity_type == "issue",
                    ActivityLog.entity_id == issue_id,
                    ActivityLog.action == "issue.updated",
                )
            )
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if not isinstance(row, dict):
            return False
        return row.get("status") in {"done", "blocked", "in_review"}

    async def _issue_has_user_intervention_after(
        self, issue: IssueRow, after: datetime | None
    ) -> bool:
        if after is None:
            return False
        result = await self._session.execute(
            select(ActivityLog.action, ActivityLog.details)
            .where(
                and_(
                    ActivityLog.org_id == issue.org_id,
                    ActivityLog.actor_type.in_(HUMAN_INTERVENTION_ACTOR_TYPES),
                    ActivityLog.entity_type == "issue",
                    ActivityLog.entity_id == issue.id,
                    ActivityLog.created_at > after,
                    ActivityLog.action.in_(("issue.comment_added", "issue.updated")),
                )
            )
            .order_by(ActivityLog.created_at.desc())
        )
        for action, details in result.all():
            if action == "issue.comment_added":
                return True
            if (
                action == "issue.updated"
                and isinstance(details, dict)
                and details.get("status") in {"done", "blocked", "in_review"}
            ):
                return True
        return False

    async def _restore_system_blocked_issue_after_recovery(
        self, final: HeartbeatRunRow
    ) -> bool:
        if final.status not in {"running", "succeeded"}:
            return False
        recovery = (
            final.context_snapshot.get("recovery")
            if isinstance(final.context_snapshot, dict)
            else None
        )
        if not isinstance(recovery, dict):
            return False
        original_run_id = recovery.get("originalRunId") or final.retry_of_run_id
        if not isinstance(original_run_id, str) or not original_run_id:
            return False
        original = await get_run(self._session, original_run_id)
        if (
            original is None
            or original.org_id != final.org_id
            or original.error_code != "process_lost"
            or original.invocation_source != "assignment"
        ):
            return False
        issue = await self._lock_run_issue_hierarchy(final)
        if issue is None or issue.status != "blocked":
            return False
        await IssueHierarchyPolicy(self._session).assert_open_ancestors(issue)
        latest_status_change = await self._latest_issue_status_change(issue)
        if latest_status_change is None:
            return False
        latest_status_activity, latest_status = latest_status_change
        details = latest_status_activity.details
        assert isinstance(details, dict)
        restore_status = details.get("fromStatus")
        if (
            latest_status_activity.action != "issue.updated"
            or latest_status_activity.run_id != original.id
            or latest_status != "blocked"
            or details.get("reason") != "run_failed"
            or details.get("runId") != original.id
            or restore_status not in {"todo", "in_progress"}
        ):
            return False
        issue.status = cast(str, restore_status)
        issue.updated_at = datetime.now(UTC)
        await self._session.flush()
        recovery_reason = (
            "process_loss_retry_started"
            if final.status == "running"
            else "process_loss_recovered"
        )
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type="system",
            actor_id="run_finalizer",
            action="issue.updated",
            entity_type="issue",
            entity_id=issue.id,
            run_id=final.id,
            details={
                "status": restore_status,
                "fromStatus": "blocked",
                "reason": recovery_reason,
                "runId": final.id,
                "originalRunId": original.id,
            },
        )
        return True

    async def _restore_system_blocked_issue_for_execution(
        self, running: HeartbeatRunRow
    ) -> bool:
        if running.status != "running" or running.invocation_source != "assignment":
            return False
        issue = await self._lock_run_issue_hierarchy(running)
        if (
            issue is None
            or issue.status != "blocked"
            or issue.assignee_agent_id != running.agent_id
        ):
            return False
        await IssueHierarchyPolicy(self._session).assert_open_ancestors(issue)
        latest_status_change = await self._latest_issue_status_change(issue)
        if latest_status_change is None:
            return False
        blocked_activity, blocked_status = latest_status_change
        details = (
            blocked_activity.details
            if isinstance(blocked_activity.details, dict)
            else {}
        )
        failed_run_id = blocked_activity.run_id
        if (
            blocked_activity.action != "issue.updated"
            or blocked_status != "blocked"
            or details.get("reason") not in {"run_failed", "declared_outputs_missing"}
            or not isinstance(failed_run_id, str)
            or details.get("runId") != failed_run_id
        ):
            return False
        failed_run = await get_run(self._session, failed_run_id)
        if (
            failed_run is None
            or failed_run.org_id != running.org_id
            or failed_run.agent_id != running.agent_id
            or failed_run.invocation_source != "assignment"
            or failed_run.status not in {"failed", "timed_out"}
            or _issue_id_from_context(failed_run.context_snapshot) != issue.id
        ):
            return False
        now = datetime.now(UTC)
        issue.status = "in_progress"
        issue.started_at = issue.started_at or now
        issue.updated_at = now
        await self._session.flush()
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type="system",
            actor_id="run_execution",
            action="issue.updated",
            entity_type="issue",
            entity_id=issue.id,
            run_id=running.id,
            details={
                "status": "in_progress",
                "fromStatus": "blocked",
                "reason": "system_failure_retry_started",
                "runId": running.id,
                "originalRunId": failed_run.id,
                "originalErrorCode": failed_run.error_code,
            },
        )
        return True

    async def _lock_run_issue(self, run: HeartbeatRunRow) -> IssueRow | None:
        issue_id = _issue_id_from_context(run.context_snapshot)
        resolved_issue = (
            await get_issue_by_id(self._session, issue_id) if issue_id else None
        )
        if resolved_issue is None or resolved_issue.org_id != run.org_id:
            return None
        return (
            await self._session.execute(
                select(IssueRow)
                .where(
                    IssueRow.id == resolved_issue.id,
                    IssueRow.org_id == run.org_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

    async def _lock_run_issue_hierarchy(self, run: HeartbeatRunRow) -> IssueRow | None:
        issue_id = _issue_id_from_context(run.context_snapshot)
        resolved_issue = (
            await get_issue_by_id(self._session, issue_id) if issue_id else None
        )
        if resolved_issue is None or resolved_issue.org_id != run.org_id:
            return None
        return await IssueHierarchyPolicy(self._session).lock_root(
            resolved_issue.id, resolved_issue.org_id
        )

    async def _latest_issue_status_change(
        self, issue: IssueRow
    ) -> tuple[ActivityLog, str] | None:
        activities = (
            (
                await self._session.execute(
                    select(ActivityLog)
                    .where(
                        ActivityLog.org_id == issue.org_id,
                        ActivityLog.entity_type == "issue",
                        ActivityLog.entity_id == issue.id,
                        ActivityLog.action.in_(
                            ("issue.updated", "issue.review_decision_recorded")
                        ),
                    )
                    .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
                )
            )
            .scalars()
            .all()
        )
        review_statuses = {
            "approve": "done",
            "request_changes": "in_progress",
            "blocked": "blocked",
        }
        for activity in activities:
            details = activity.details if isinstance(activity.details, dict) else {}
            status = details.get("status")
            if activity.action == "issue.review_decision_recorded":
                decision = details.get("decision")
                status = (
                    review_statuses.get(decision) if isinstance(decision, str) else None
                )
            if isinstance(status, str):
                return activity, status
        return None

    async def _release_issue_execution(self, final: HeartbeatRunRow) -> None:
        issue_id = _issue_id_from_context(final.context_snapshot)
        issue = await get_issue_by_id(self._session, issue_id) if issue_id else None
        has_active_children = (
            await self._issue_has_active_children(issue.id)
            if issue is not None
            else False
        )
        should_request_review = (
            final.status == "succeeded"
            and final.invocation_source == "assignment"
            and issue is not None
            and issue.org_id == final.org_id
            and issue.status == "in_progress"
            and bool(issue.reviewer_agent_id)
            and not has_active_children
        )
        should_block_failed_issue = (
            final.status in {"failed", "timed_out"}
            and final.invocation_source == "assignment"
            and final.error_code != "closeout_missing"
            and issue is not None
            and issue.org_id == final.org_id
            and issue.assignee_agent_id == final.agent_id
            and issue.status in {"todo", "in_progress"}
            and not has_active_children
        )
        criteria = [
            IssueRow.execution_run_id == final.id,
            IssueRow.checkout_run_id == final.id,
        ]
        if issue is not None:
            criteria.append(IssueRow.id == issue.id)
        values: dict[str, Any] = {
            "updated_at": datetime.now(UTC),
        }
        if final.status in {
            "failed",
            "timed_out",
            "cancelled",
            "succeeded",
        }:
            values.update(
                {
                    "execution_run_id": None,
                    "checkout_run_id": None,
                    "execution_agent_name_key": None,
                    "execution_locked_at": None,
                }
            )
        await self._session.execute(
            update(IssueRow)
            .where(IssueRow.org_id == final.org_id, or_(*criteria))
            .values(**values)
        )
        if should_request_review and issue is not None:
            issue.status = "in_review"
            issue.updated_at = values["updated_at"]
            await self._session.flush()
            await insert_activity_log(
                self._session,
                org_id=issue.org_id,
                actor_type="agent",
                actor_id=final.agent_id,
                action="issue.updated",
                entity_type="issue",
                entity_id=issue.id,
                run_id=final.id,
                details={
                    "status": "in_review",
                    "fromStatus": "in_progress",
                    "reason": "run_succeeded",
                    "runId": final.id,
                },
            )
            await self._queue_issue_review_wakeup_after_success(final, issue)
        if should_block_failed_issue and issue is not None:
            from_status = issue.status
            issue.status = "blocked"
            issue.updated_at = values["updated_at"]
            await self._session.flush()
            await insert_activity_log(
                self._session,
                org_id=issue.org_id,
                actor_type="agent",
                actor_id=final.agent_id,
                action="issue.updated",
                entity_type="issue",
                entity_id=issue.id,
                run_id=final.id,
                details={
                    "status": "blocked",
                    "fromStatus": from_status,
                    "reason": "run_failed",
                    "runId": final.id,
                    "error": final.error,
                    "errorCode": final.error_code,
                },
            )
        if issue is not None and final.status in {
            "failed",
            "timed_out",
            "cancelled",
            "succeeded",
        }:
            await self._promote_deferred_issue_wakeup(final.org_id, issue.id)
        if issue is not None:
            await self._wake_parent_after_child_settled(final, issue)

    async def _issue_has_active_children(self, issue_id: str) -> bool:
        result = await self._session.execute(
            select(IssueRow.id)
            .where(
                IssueRow.parent_id == issue_id,
                IssueRow.hidden_at.is_(None),
                IssueRow.status.in_(("backlog", "todo", "in_progress", "in_review")),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _wake_parent_after_child_settled(
        self, final: HeartbeatRunRow, issue: IssueRow
    ) -> None:
        await self.parent_continuation.queue_for_settled_child(
            issue.id,
            expected_org_id=final.org_id,
        )

    async def queue_parent_continuation_for_settled_child(
        self, child_issue_id: str, *, expected_org_id: str | None = None
    ) -> str | None:
        return await self.parent_continuation.queue_for_settled_child(
            child_issue_id,
            expected_org_id=expected_org_id,
        )

    async def _queue_issue_review_wakeup_after_success(
        self, final: HeartbeatRunRow, issue: IssueRow
    ) -> None:
        if not issue.reviewer_agent_id or issue.reviewer_agent_id == final.agent_id:
            return
        await self.wakeup(
            issue.reviewer_agent_id,
            {
                "source": "review",
                "triggerDetail": "system",
                "reason": "issue_review_requested",
                "idempotencyKey": (f"issue:{issue.id}:review:run_succeeded:{final.id}"),
                "payload": {
                    "issueId": issue.id,
                    "mutation": "run_succeeded",
                    "originRunId": final.id,
                },
                "contextSnapshot": {
                    "issueId": issue.id,
                    "source": "issue.run_succeeded",
                    "wakeSource": "review",
                    "wakeReason": "issue_review_requested",
                    "role": "reviewer",
                    "issue": {
                        "id": issue.id,
                        "identifier": issue.identifier,
                        "title": issue.title,
                        "description": issue.description,
                        "status": issue.status,
                        "priority": issue.priority,
                    },
                    "reviewInstructions": (
                        "The assigned run succeeded and the issue is ready for "
                        "review. Record one structured reviewer decision before "
                        "exiting: approve, request_changes, needs_followup, or "
                        "blocked. Use `octopus issue review`."
                    ),
                },
            },
            actor_type="agent",
            actor_id=final.agent_id,
            execute_immediately=False,
        )

    async def _promote_deferred_issue_wakeup(self, org_id: str, issue_id: str) -> None:
        issue = await self._session.get(IssueRow, issue_id)
        if issue is None or issue.org_id != org_id:
            return

        while True:
            result = await self._session.execute(
                select(AgentWakeupRequestRow)
                .where(
                    AgentWakeupRequestRow.org_id == org_id,
                    AgentWakeupRequestRow.status == "deferred_issue_execution",
                )
                .order_by(
                    AgentWakeupRequestRow.requested_at,
                    AgentWakeupRequestRow.id,
                )
            )
            deferred = next(
                (
                    row
                    for row in result.scalars().all()
                    if _issue_id_from_context(row.payload) == issue_id
                ),
                None,
            )
            if deferred is None:
                return

            if issue.status in {"done", "cancelled"}:
                await update_wakeup_request(
                    self._session,
                    deferred.id,
                    {
                        "status": "skipped",
                        "reason": "issue_execution_closed",
                        "run_id": None,
                        "claimed_at": None,
                        "finished_at": datetime.now(UTC),
                        "error": "Deferred wake skipped because issue is already closed",
                    },
                )
                continue

            agent = await get_agent_by_id(self._session, deferred.agent_id)
            if (
                agent is None
                or agent.org_id != org_id
                or agent.status
                in {
                    "paused",
                    "terminated",
                    "pending_approval",
                }
            ):
                await update_wakeup_request(
                    self._session,
                    deferred.id,
                    {
                        "status": "failed",
                        "finished_at": datetime.now(UTC),
                        "error": (
                            "Deferred wake could not be promoted: agent is not "
                            "invokable"
                        ),
                    },
                )
                continue

            payload = dict(deferred.payload or {})
            deferred_context = payload.pop(self._DEFERRED_CONTEXT_KEY, {})
            context_snapshot = {
                "triggeredBy": deferred.requested_by_actor_type or "system",
                "actorId": deferred.requested_by_actor_id or "system",
                "forceFreshSession": False,
                **self._payload_context(payload),
                **(deferred_context if isinstance(deferred_context, dict) else {}),
            }
            run = await create_run(
                self._session,
                {
                    "org_id": org_id,
                    "agent_id": agent.id,
                    "invocation_source": deferred.source,
                    "run_purpose": _run_purpose(deferred.source, context_snapshot),
                    "trigger_detail": deferred.trigger_detail,
                    "status": "queued",
                    "wakeup_request_id": deferred.id,
                    "context_snapshot": context_snapshot,
                },
            )
            run = await self._initialize_run_log(run)
            await update_wakeup_request(
                self._session,
                deferred.id,
                {
                    "status": "queued",
                    "reason": "issue_execution_promoted",
                    "payload": payload,
                    "run_id": run.id,
                    "claimed_at": None,
                    "finished_at": None,
                    "error": None,
                },
            )
            await self._claim_issue_execution_for_task_run(
                agent,
                run,
                context_snapshot,
                issue=issue,
            )
            await self._append_event(
                run,
                1,
                "lifecycle",
                stream="system",
                message="run queued",
                level="info",
                payload={
                    "status": "queued",
                    "source": deferred.source,
                    "triggerDetail": deferred.trigger_detail,
                    "promotedFromDeferredIssueExecution": True,
                },
            )
            await self._session.flush()
            return

    async def _claim_issue_execution_for_task_run(
        self,
        agent: AgentRow,
        run: HeartbeatRunRow,
        context_snapshot: dict[str, Any],
        *,
        issue: IssueRow | None = None,
    ) -> None:
        if run.run_purpose != "task_execution":
            return
        issue_id = _issue_id_from_context(context_snapshot)
        if issue_id is None:
            return
        issue = issue or await get_issue_by_id(self._session, issue_id)
        if (
            issue is None
            or issue.org_id != run.org_id
            or issue.assignee_agent_id != agent.id
            or issue.status in {"done", "cancelled"}
        ):
            return
        now = datetime.now(UTC)
        issue.checkout_run_id = run.id
        issue.execution_run_id = run.id
        issue.execution_agent_name_key = _agent_name_key(agent.name)
        issue.execution_locked_at = now
        if issue.status in {"backlog", "todo"}:
            issue.status = "in_progress"
            if issue.started_at is None:
                issue.started_at = now
        issue.updated_at = now

    async def _next_event_sequence(self, run_id: str) -> int:
        events = await list_run_events(self._session, run_id, limit=1000)
        return (events[-1].seq if events else 0) + 1

    def _heartbeat_policy(self, agent: AgentRow) -> dict[str, float | bool]:
        heartbeat = agent.runtime_config.get("heartbeat", {})
        config = heartbeat if isinstance(heartbeat, dict) else {}
        enabled = config.get("enabled", True)
        interval = config.get("intervalSec", 0)
        interval_sec = (
            max(0.0, float(interval))
            if isinstance(interval, (int, float)) and not isinstance(interval, bool)
            else 0.0
        )
        wake_on_demand = (
            config.get("wakeOnDemand")
            if "wakeOnDemand" in config
            else config.get("wakeOnAssignment")
            if "wakeOnAssignment" in config
            else config.get("wakeOnOnDemand")
            if "wakeOnOnDemand" in config
            else config.get("wakeOnAutomation", True)
        )
        run_diagnostics_on_timer = config.get("runDiagnosticsOnTimer")
        if "preflightEnabled" in config:
            preflight_enabled = config.get("preflightEnabled")
        elif "timerPreflightEnabled" in config:
            preflight_enabled = config.get("timerPreflightEnabled")
        else:
            preflight_enabled = run_diagnostics_on_timer is not True
        return {
            "enabled": enabled if isinstance(enabled, bool) else True,
            "intervalSec": interval_sec
            if interval_sec > 0
            else float(HEARTBEAT_INTERVAL_DEFAULT_SEC),
            "wakeOnDemand": (
                wake_on_demand if isinstance(wake_on_demand, bool) else True
            ),
            "runDiagnosticsOnTimer": run_diagnostics_on_timer
            if isinstance(run_diagnostics_on_timer, bool)
            else False,
            "preflightEnabled": preflight_enabled
            if isinstance(preflight_enabled, bool)
            else True,
        }

    def _max_concurrent_runs(self, agent: AgentRow) -> int:
        heartbeat = agent.runtime_config.get("heartbeat", {})
        config = heartbeat if isinstance(heartbeat, dict) else {}
        configured = config.get("maxConcurrentRuns", AGENT_RUN_CONCURRENCY_DEFAULT)
        if not isinstance(configured, int) or isinstance(configured, bool):
            configured = AGENT_RUN_CONCURRENCY_DEFAULT
        return min(
            AGENT_RUN_CONCURRENCY_MAX,
            max(AGENT_RUN_CONCURRENCY_MIN, configured),
        )

    async def _update_runtime_state(
        self, agent: AgentRow, run: HeartbeatRunRow
    ) -> None:
        state = await get_runtime_state(self._session, agent.id)
        if state is None:
            await create_runtime_state(
                self._session,
                {
                    "agent_id": agent.id,
                    "org_id": agent.org_id,
                    "agent_runtime_type": agent.agent_runtime_type,
                    "state_json": {},
                    "last_run_id": run.id,
                    "last_run_status": run.status,
                    "session_id": run.session_id_after,
                    "total_input_tokens": self._usage_count(run, "inputTokens"),
                    "total_output_tokens": self._usage_count(run, "outputTokens"),
                    "total_cached_input_tokens": self._usage_count(
                        run, "cachedInputTokens"
                    ),
                    "last_error": run.error,
                },
            )
            return
        if state.last_run_id == run.id and state.last_run_status == run.status:
            return
        await update_runtime_state(
            self._session,
            agent.id,
            {
                "agent_runtime_type": agent.agent_runtime_type,
                "last_run_id": run.id,
                "last_run_status": run.status,
                "session_id": run.session_id_after or state.session_id,
                "total_input_tokens": state.total_input_tokens
                + self._usage_count(run, "inputTokens"),
                "total_output_tokens": state.total_output_tokens
                + self._usage_count(run, "outputTokens"),
                "total_cached_input_tokens": state.total_cached_input_tokens
                + self._usage_count(run, "cachedInputTokens"),
                "last_error": run.error,
            },
        )

    def _usage_count(self, run: HeartbeatRunRow, key: str) -> int:
        value = (run.usage_json or {}).get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    async def _append_event(
        self,
        run: HeartbeatRunRow,
        sequence: int,
        event_type: str,
        *,
        message: str,
        level: str,
        stream: str | None = "system",
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        await append_run_event(
            self._session,
            {
                "org_id": run.org_id,
                "run_id": run.id,
                "agent_id": run.agent_id,
                "seq": sequence,
                "event_type": event_type,
                "stream": stream,
                "level": level,
                "message": message,
                "payload": payload,
                "idempotency_key": idempotency_key,
            },
        )

    def _wakeup_values(
        self,
        agent: AgentRow,
        payload: WakeAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
        status: str,
    ) -> dict[str, Any]:
        values = {
            "org_id": agent.org_id,
            "agent_id": agent.id,
            "source": payload.get("source", "on_demand"),
            "trigger_detail": payload.get("triggerDetail", "manual"),
            "reason": payload.get("reason"),
            "payload": payload.get("payload"),
            "status": status,
            "requested_by_actor_type": "agent" if actor_type == "agent" else "user",
            "requested_by_actor_id": actor_id,
            "idempotency_key": payload.get("idempotencyKey"),
        }
        requested_at = payload.get("requestedAt")
        if isinstance(requested_at, datetime):
            values["requested_at"] = requested_at
        elif isinstance(requested_at, str):
            parsed = datetime.fromisoformat(requested_at)
            values["requested_at"] = (
                parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
            )
        return values

    def _payload_context(self, payload: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        context: dict[str, Any] = {}
        for source_key, target_key in (
            ("issueId", "issueId"),
            ("primaryIssueId", "primaryIssueId"),
            ("projectId", "projectId"),
            ("delegationOriginRunId", "delegationOriginRunId"),
        ):
            value = payload.get(source_key)
            if isinstance(value, str) and value:
                context[target_key] = value
        closeout_policy = payload.get("closeoutPolicy")
        if isinstance(closeout_policy, dict):
            context["closeoutPolicy"] = dict(closeout_policy)
        return context

    def _payload_context_snapshot(
        self, context_snapshot: dict[str, Any] | None
    ) -> dict[str, Any]:
        return dict(context_snapshot) if isinstance(context_snapshot, dict) else {}

    async def _enrich_issue_context_snapshot(
        self, context_snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        issue_id = _issue_id_from_context(context_snapshot)
        if issue_id is None:
            return context_snapshot
        from .issues import IssueService

        raw_delegation_origin_run_id = context_snapshot.get("delegationOriginRunId")
        delegation_origin_run_id = (
            raw_delegation_origin_run_id
            if isinstance(raw_delegation_origin_run_id, str)
            and raw_delegation_origin_run_id
            else None
        )
        heartbeat_context = await IssueService(self._session).get_heartbeat_context(
            issue_id,
            delegation_origin_run_id=delegation_origin_run_id,
        )
        if heartbeat_context is None:
            return context_snapshot
        return {
            **heartbeat_context,
            **context_snapshot,
            "issue": context_snapshot.get("issue") or heartbeat_context.get("issue"),
        }

    def _to_run(self, row: HeartbeatRunRow) -> HeartbeatRun:
        return heartbeat_run_to_data(row)

    async def _to_run_with_issue_context(self, row: HeartbeatRunRow) -> HeartbeatRun:
        data = heartbeat_run_to_data(row)
        issue_id = _issue_id_from_context(row.context_snapshot)
        if issue_id is None:
            return data
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None or issue.org_id != row.org_id:
            data["issueId"] = issue_id
            data["issueIdentifier"] = None
            data["issueTitle"] = None
            data["projectId"] = None
            data["goalId"] = None
            return data
        data["issueId"] = issue.id
        data["issueIdentifier"] = issue.identifier
        data["issueTitle"] = issue.title
        data["projectId"] = issue.project_id
        data["goalId"] = issue.goal_id
        return data

    def _to_issue_run_summary(
        self, row: HeartbeatRunRow, issue: IssueRow
    ) -> dict[str, Any]:
        return {
            "id": row.id,
            "runId": row.id,
            "orgId": row.org_id,
            "status": row.status,
            "agentId": row.agent_id,
            "invocationSource": row.invocation_source,
            "runPurpose": row.run_purpose,
            "triggerDetail": row.trigger_detail,
            "retryOfRunId": row.retry_of_run_id,
            "processLossRetryCount": row.process_loss_retry_count,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
            "startedAt": row.started_at.isoformat() if row.started_at else None,
            "finishedAt": row.finished_at.isoformat() if row.finished_at else None,
            "error": row.error,
            "summary": _run_summary(row.result_json),
            "usageJson": row.usage_json,
            "resultJson": row.result_json,
            "issueId": issue.id,
            "issueIdentifier": issue.identifier,
            "issueTitle": issue.title,
            "projectId": issue.project_id,
            "goalId": issue.goal_id,
        }

    def _to_event(self, row: HeartbeatRunEventRow) -> HeartbeatRunEvent:
        return heartbeat_event_to_data(row)


def heartbeat_run_to_data(row: HeartbeatRunRow) -> HeartbeatRun:
    trigger_detail = (
        row.trigger_detail
        if row.trigger_detail in WAKEUP_TRIGGER_DETAIL_VALUES
        else None
    )
    return {
        "id": row.id,
        "orgId": row.org_id,
        "agentId": row.agent_id,
        "invocationSource": cast(HeartbeatInvocationSource, row.invocation_source),
        "runPurpose": cast(HeartbeatRunPurpose, row.run_purpose),
        "triggerDetail": cast(WakeupTriggerDetail | None, trigger_detail),
        "status": cast(HeartbeatRunStatus, row.status),
        "startedAt": row.started_at.isoformat() if row.started_at else None,
        "finishedAt": row.finished_at.isoformat() if row.finished_at else None,
        "error": row.error,
        "wakeupRequestId": row.wakeup_request_id,
        "exitCode": row.exit_code,
        "signal": row.signal,
        "usageJson": row.usage_json,
        "resultJson": row.result_json,
        "sessionIdBefore": row.session_id_before,
        "sessionIdAfter": row.session_id_after,
        "logStore": row.log_store,
        "logRef": row.log_ref,
        "logBytes": row.log_bytes,
        "logSha256": row.log_sha256,
        "logCompressed": row.log_compressed,
        "stdoutExcerpt": row.stdout_excerpt,
        "stderrExcerpt": row.stderr_excerpt,
        "errorCode": row.error_code,
        "externalRunId": row.external_run_id,
        "processPid": row.process_pid,
        "processStartedAt": (
            row.process_started_at.isoformat() if row.process_started_at else None
        ),
        "processExitedAt": (
            row.process_exited_at.isoformat() if row.process_exited_at else None
        ),
        "executionLeaseExpiresAt": (
            row.execution_lease_expires_at.isoformat()
            if row.execution_lease_expires_at
            else None
        ),
        "terminalEffectsPending": row.terminal_effects_pending,
        "terminalEffectsCompletedJson": row.terminal_effects_completed_json,
        "terminalEffectsAttemptCount": row.terminal_effects_attempt_count,
        "terminalEffectsNextAttemptAt": (
            row.terminal_effects_next_attempt_at.isoformat()
            if row.terminal_effects_next_attempt_at
            else None
        ),
        "terminalEffectsLastError": row.terminal_effects_last_error,
        "retryOfRunId": row.retry_of_run_id,
        "processLossRetryCount": row.process_loss_retry_count,
        "contextSnapshot": row.context_snapshot,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }


def _issue_id_from_context(context_snapshot: dict[str, Any] | None) -> str | None:
    snapshot = context_snapshot if isinstance(context_snapshot, dict) else {}
    value = snapshot.get("issueId") or snapshot.get("primaryIssueId")
    return value if isinstance(value, str) and value else None


def _passive_followup_context(context_snapshot: dict[str, Any]) -> dict[str, int | str]:
    raw = context_snapshot.get("passiveFollowup")
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int | str] = {}
    attempt = raw.get("attempt")
    if isinstance(attempt, int) and not isinstance(attempt, bool) and attempt >= 0:
        result["attempt"] = attempt
    origin_run_id = raw.get("originRunId")
    if isinstance(origin_run_id, str) and origin_run_id:
        result["originRunId"] = origin_run_id
    return result


def _agent_name_key(name: str) -> str:
    key = "-".join(name.strip().lower().split())
    return key or "agent"


def _run_summary(result_json: dict[str, Any] | None) -> str | None:
    if not isinstance(result_json, dict):
        return None
    for key in ("summary", "result", "message"):
        value = result_json.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _activity_details_text(details: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("body", "comment", "note", "summary", "message", "status"):
        value = details.get(key)
        if isinstance(value, str) and value.strip():
            values.append(value)
    return "\n".join(values)


def _dedupe_work_product_payloads(products: list[Any]) -> list[Any]:
    deduped: list[Any] = []
    seen_ids: set[str] = set()
    for product in products:
        product_id = product.get("id") if isinstance(product, dict) else None
        if isinstance(product_id, str) and product_id:
            if product_id in seen_ids:
                continue
            seen_ids.add(product_id)
        deduped.append(product)
    return deduped


def _is_sqlite_database_locked_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    while current is not None:
        if "database is locked" in str(current).lower():
            return True
        current = current.__cause__ or current.__context__
    return False


class WorkspacePreparationCoordinator:
    """Prepare Workspace state in a short transaction before Adapter execution."""

    MAX_SQLITE_ATTEMPTS = 3
    _locks: ClassVar[dict[str, asyncio.Lock]] = {}

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def prepare(
        self, *, agent_id: str, run_id: str, org_id: str
    ) -> dict[str, Any] | None:
        plan_session = self._session_factory()
        try:
            running = await get_run(plan_session, run_id)
            plan = await WorkspaceService(plan_session).preparation_plan(
                context_snapshot=(
                    running.context_snapshot if running is not None else None
                ),
                org_id=org_id,
                agent_id=agent_id,
            )
        finally:
            await _shielded_session_close(plan_session)
        strategy = workspace_access_strategy(plan)
        # The lock covers only the short Workspace transaction. It is released
        # before Adapter startup, so safe execution work can still run in parallel.
        lock = self._locks.setdefault(strategy.lock_key(plan), asyncio.Lock())
        async with lock:
            for attempt in range(1, self.MAX_SQLITE_ATTEMPTS + 1):
                session = self._session_factory()
                enable_write_transactions(session)
                try:
                    await WorkspaceService(session).lock_preparation_plan(plan)
                    agent = await get_agent_by_id(session, agent_id)
                    running = await get_run(session, run_id)
                    if agent is None or running is None or running.status != "running":
                        return None
                    service = HeartbeatService(session)
                    workspace_context = await service._prepare_workspace_context(
                        agent, running
                    )
                    await session.commit()
                    return workspace_context
                except Exception as exc:
                    await _shielded_session_rollback(session)
                    if (
                        not _is_sqlite_database_locked_error(exc)
                        or attempt >= self.MAX_SQLITE_ATTEMPTS
                    ):
                        raise
                    await asyncio.sleep(0.05 * (2 ** (attempt - 1)))
                finally:
                    await _shielded_session_close(session)
        return None


def track_dispatch_task(tasks: set[asyncio.Task[Any]], task: asyncio.Task[Any]) -> None:
    """Keep a dispatch task alive and always observe its terminal exception."""

    tasks.add(task)

    def _observe(completed: asyncio.Task[Any]) -> None:
        tasks.discard(completed)
        if completed.cancelled():
            return
        try:
            completed.result()
        except BaseException:
            logger.exception("heartbeat dispatch task failed")

    task.add_done_callback(_observe)


def heartbeat_event_to_data(row: HeartbeatRunEventRow) -> HeartbeatRunEvent:
    return {
        "id": row.id,
        "orgId": row.org_id,
        "runId": row.run_id,
        "agentId": row.agent_id,
        "seq": row.seq,
        "eventType": row.event_type,
        "stream": row.stream,
        "level": row.level,
        "color": row.color,
        "message": row.message,
        "payload": row.payload,
        "idempotencyKey": row.idempotency_key,
        "createdAt": row.created_at.isoformat(),
    }
