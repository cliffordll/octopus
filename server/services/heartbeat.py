from __future__ import annotations

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
import os
from pathlib import Path
from typing import Any, ClassVar, cast

import psutil
from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import (
    get_agent_by_id,
    list_org_agents,
    update_agent,
)
from packages.database.queries.agent_state import (
    create_runtime_state,
    get_runtime_state,
    update_runtime_state,
)
from packages.database.queries.agent_skills import list_enabled_skill_keys
from packages.database.queries.heartbeat import (
    append_run_event,
    claim_due_wakeup_request,
    claim_queued_run,
    create_run,
    create_wakeup_request,
    get_run,
    get_wakeup_by_idempotency_key,
    has_active_timer_run,
    list_queued_agent_ids,
    list_queued_runs,
    list_due_wakeup_request_ids,
    list_run_events,
    list_running_run_ids,
    list_runs,
    list_runs_by_status,
    list_wakeup_requests_by_status,
    update_run,
    update_wakeup_request,
)
from packages.database.schema import (
    AgentWakeupRequest as AgentWakeupRequestRow,
    Agent as AgentRow,
    HeartbeatRun as HeartbeatRunRow,
    HeartbeatRunEvent as HeartbeatRunEventRow,
    Issue as IssueRow,
    ActivityLog,
)
from packages.runtimes import RuntimeExecutionContext, get_runtime_adapter
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

from .agents import AgentConflictError, prepare_agent_runtime_config
from .costs import CostService
from .logs import (
    LogReadResult,
    append_local_file_log,
    finalize_local_file_log,
    read_local_file_log,
)
from .runtime_providers import inject_runtime_provider_config
from .workspace_paths import ensure_octopus_run_log_dir
from .workspaces import WorkspaceService

LOCAL_CHILD_PROCESS_RUNTIMES = {
    "process",
    "claude_local",
    "codex_local",
    "gemini_local",
    "opencode_local",
    "pi_local",
    "hermes_local",
}

ISSUE_PASSIVE_FOLLOWUP_REASON = "issue_passive_followup"
ISSUE_PASSIVE_FOLLOWUP_WAKE_SOURCE = "passive_issue_followup"
ISSUE_PASSIVE_FOLLOWUP_FAILURE_REASON = "missing_closure"
ISSUE_PASSIVE_FOLLOWUP_MAX_ATTEMPTS = 2
ISSUE_PASSIVE_FOLLOWUP_DELAY_ENV = "OCTOPUS_ISSUE_PASSIVE_FOLLOWUP_DELAY_SECONDS"
ISSUE_PASSIVE_FOLLOWUP_DELAY_DEFAULT_SECONDS = 30 * 60
HUMAN_INTERVENTION_ACTOR_TYPES = {"board", "user"}
WAKEUP_TRIGGER_DETAIL_VALUES = {"manual", "ping", "callback", "system"}


class ProcessLostError(RuntimeError):
    def __init__(self, pid: int) -> None:
        super().__init__(f"Process lost -- child pid {pid} is no longer running")
        self.pid = pid


def _is_process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.ZombieProcess, ValueError):
        return False


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
    if invocation_source == "timer":
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


class HeartbeatService:
    _DEFERRED_CONTEXT_KEY = "__deferredContextSnapshot"
    RUNTIME_PROGRESS_INTERVAL_SECONDS = 15.0
    _start_locks: ClassVar[dict[str, asyncio.Lock]] = {}
    _active_run_ids: ClassVar[dict[str, set[str]]] = {}
    _cancel_events: ClassVar[dict[str, asyncio.Event]] = {}

    def __init__(
        self, session: AsyncSession, *, commit_process_metadata: bool = False
    ) -> None:
        self._session = session
        self._commit_process_metadata = commit_process_metadata

    async def wakeup(
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
        idempotency_key = payload.get("idempotencyKey")
        if idempotency_key:
            existing = await get_wakeup_by_idempotency_key(
                self._session, agent.id, idempotency_key
            )
            if existing is not None and existing.run_id:
                existing_run = await get_run(self._session, existing.run_id)
                if existing_run is not None and existing_run.status not in {
                    "failed",
                    "timed_out",
                    "cancelled",
                }:
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
            await create_wakeup_request(
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
        if not execute_immediately:
            return self._to_run(run)
        executed = await self._start_if_capacity(agent, run)
        return self._to_run(executed)

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
        if (
            payload.get("reason") == "issue_comment_mentioned"
            or context.get("wakeReason") == "issue_comment_mentioned"
        ):
            return False
        issue = await self._session.get(IssueRow, issue_id)
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
        await create_wakeup_request(
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
        issue = await self._session.get(IssueRow, issue_id)
        if issue is None:
            return None
        rows = await list_runs(self._session, issue.org_id)
        return [
            self._to_issue_run_summary(row, issue)
            for row in rows
            if _issue_id_from_context(row.context_snapshot) == issue.id
        ]

    async def get_active_for_issue(self, issue_id: str) -> HeartbeatRun | None:
        issue = await self._session.get(IssueRow, issue_id)
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
        issue = await self._session.get(IssueRow, issue_id)
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
        wakeup = await create_wakeup_request(
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
        issue = await self._session.get(IssueRow, issue_id)
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
        issue = await self._session.get(IssueRow, issue_id)
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
        cancelled = await update_run(
            self._session,
            run.id,
            {
                "status": "cancelled",
                "finished_at": now,
                "error": "run cancelled",
                "error_code": "cancelled",
            },
        )
        assert cancelled is not None
        if run.wakeup_request_id:
            await update_wakeup_request(
                self._session,
                run.wakeup_request_id,
                {
                    "status": "cancelled",
                    "finished_at": now,
                    "error": "run cancelled",
                },
            )
        await self._append_event(
            cancelled,
            await self._next_event_sequence(run.id),
            "lifecycle",
            message="run cancelled",
            level="warning",
        )
        await WorkspaceService(self._session).mark_run_workspace_interrupted(
            run.id, reason="cancelled", message="run cancelled"
        )
        await self._release_issue_execution(cancelled)
        agent = await get_agent_by_id(self._session, run.agent_id)
        if agent is not None and agent.status == "running":
            await update_agent(self._session, agent.id, {"status": "idle"})
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
        wakeup = await create_wakeup_request(
            self._session,
            self._wakeup_values(
                agent,
                {
                    "source": invocation_source,
                    "triggerDetail": trigger_detail,
                    "reason": f"{recovery_trigger}_retry",
                },
                actor_type=actor_type,
                actor_id=actor_id,
                status="queued",
            ),
        )
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
        recovered: list[HeartbeatRun] = []
        active_ids = (
            set().union(*self._active_run_ids.values())
            if self._active_run_ids
            else set()
        )
        for run in await list_runs_by_status(self._session, "running"):
            if run.id in active_ids:
                continue
            if await self._cancel_orphaned_run_if_issue_closed(run):
                continue
            agent = await get_agent_by_id(self._session, run.agent_id)
            tracks_local_child = (
                agent is not None
                and agent.agent_runtime_type in LOCAL_CHILD_PROCESS_RUNTIMES
                and run.process_pid is not None
            )
            if require_process_loss:
                if not tracks_local_child:
                    continue
                assert run.process_pid is not None
                if _is_process_alive(run.process_pid):
                    continue
            detached_message: str | None = None
            if tracks_local_child:
                detached_message = (
                    f"Detached child pid {run.process_pid} was not terminated during "
                    "server recovery because process ownership cannot be verified"
                )
            failed = await update_run(
                self._session,
                run.id,
                {
                    "status": "failed",
                    "finished_at": datetime.now(UTC),
                    "error": (
                        f"Process lost -- child pid {run.process_pid} is no longer running"
                        if run.process_pid
                        else "Run interrupted before server recovery"
                    ),
                    "error_code": "process_lost",
                },
            )
            assert failed is not None
            if run.wakeup_request_id:
                await update_wakeup_request(
                    self._session,
                    run.wakeup_request_id,
                    {
                        "status": "failed",
                        "finished_at": datetime.now(UTC),
                        "error": "Run interrupted before server recovery",
                    },
                )
            await self._append_event(
                failed,
                await self._next_event_sequence(run.id),
                "lifecycle",
                message="run interrupted before server recovery",
                level="error",
                payload={"processPid": run.process_pid} if run.process_pid else None,
            )
            await WorkspaceService(self._session).mark_run_workspace_interrupted(
                run.id,
                reason="process_lost",
                message="Run interrupted before server recovery",
            )
            await self._release_issue_execution(failed)
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

    async def _cancel_orphaned_run_if_issue_closed(self, run: HeartbeatRunRow) -> bool:
        if run.invocation_source != "assignment":
            return False
        issue_id = _issue_id_from_context(run.context_snapshot)
        issue = await self._session.get(IssueRow, issue_id) if issue_id else None
        if issue is None or issue.org_id != run.org_id:
            return False
        if issue.status not in {"done", "cancelled"}:
            return False
        message = f"Run stopped during recovery because issue is already {issue.status}"
        cancelled = await update_run(
            self._session,
            run.id,
            {
                "status": "cancelled",
                "finished_at": datetime.now(UTC),
                "error": message,
                "error_code": "issue_already_closed",
                **self._finalize_run_log_fields(run),
            },
        )
        if cancelled is None:
            return True
        if run.wakeup_request_id:
            await update_wakeup_request(
                self._session,
                run.wakeup_request_id,
                {
                    "status": "cancelled",
                    "finished_at": datetime.now(UTC),
                    "error": message,
                },
            )
        await self._append_event(
            cancelled,
            await self._next_event_sequence(run.id),
            "lifecycle",
            message=message,
            level="warning",
            payload={"issueId": issue.id, "issueStatus": issue.status},
        )
        await self._release_issue_execution(cancelled)
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
                await self._session.get(IssueRow, issue_id)
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
        await create_wakeup_request(
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
            policy = self._heartbeat_policy(agent)
            baseline = agent.last_heartbeat_at or agent.created_at
            if baseline.tzinfo is None:
                baseline = baseline.replace(tzinfo=UTC)
            if (
                not policy["enabled"]
                or policy["intervalSec"] <= 0
                or checked_at - baseline < timedelta(seconds=policy["intervalSec"])
            ):
                continue
            if await has_active_timer_run(self._session, agent.id):
                continue
            run = await self.wakeup(
                agent.id,
                {
                    "source": "timer",
                    "triggerDetail": "system",
                    "reason": "heartbeat_timer",
                },
                actor_type="system",
                actor_id="scheduler",
                execute_immediately=False,
            )
            if run is not None:
                triggered.append(run)
        return triggered

    async def _create_queued_run(
        self,
        agent: AgentRow,
        payload: WakeAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> HeartbeatRunRow:
        wakeup = await create_wakeup_request(
            self._session,
            self._wakeup_values(
                agent,
                payload,
                actor_type=actor_type,
                actor_id=actor_id,
                status="queued",
            ),
        )
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
        await self._claim_issue_execution_for_assignment_run(
            agent, run, context_snapshot
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

        async def on_log(stream: str, chunk: str) -> None:
            nonlocal sequence, stdout, stderr
            async with runtime_callback_lock:
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

        async def emit_runtime_progress() -> None:
            nonlocal sequence
            async with runtime_callback_lock:
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
            interval = self.RUNTIME_PROGRESS_INTERVAL_SECONDS
            if interval <= 0:
                return await adapter.execute(context)
            task = asyncio.create_task(adapter.execute(context))
            try:
                while True:
                    done, _ = await asyncio.wait({task}, timeout=interval)
                    if task in done:
                        return task.result()
                    if cancellation.is_set():
                        continue
                    if (
                        agent.agent_runtime_type in LOCAL_CHILD_PROCESS_RUNTIMES
                        and running.process_pid is not None
                        and not _is_process_alive(running.process_pid)
                    ):
                        task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await task
                        raise ProcessLostError(running.process_pid)
                    await emit_runtime_progress()
            except asyncio.CancelledError:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                raise

        try:
            adapter = get_runtime_adapter(agent.agent_runtime_type)
            workspace_context = await self._prepare_workspace_context(agent, running)
            sequence = await self._next_event_sequence(running.id)
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
                )
            )
            await self._finish_adapter_workspace_operation(
                adapter_operation,
                status="succeeded" if not result.error_message else "failed",
                exit_code=result.exit_code,
                stdout_excerpt=stdout or None,
                stderr_excerpt=stderr or result.error_message,
                metadata={"adapterExecution": True, "timedOut": result.timed_out},
            )
            if cancellation.is_set():
                return running
            await self._session.refresh(running)
            if running.status == "cancelled":
                return running
            final_status: HeartbeatRunStatus
            if result.timed_out:
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
            final = await update_run(
                self._session,
                running.id,
                {
                    "status": final_status,
                    "finished_at": datetime.now(UTC),
                    "error": result.error_message,
                    "error_code": (
                        "timeout"
                        if final_status == "timed_out"
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
                    "stderr_excerpt": stderr or None,
                },
            )
            assert final is not None
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
            await self._session.refresh(running)
            if running.status == "cancelled":
                return running
            message = _exception_message(exc)
            await self._append_run_log(running, stream="stderr", chunk=message)
            await self._finish_adapter_workspace_operation(
                locals().get("adapter_operation"),
                status="failed",
                stderr_excerpt=message,
                metadata={"error": message},
            )
            error_code = (
                "process_lost"
                if isinstance(exc, ProcessLostError)
                else "adapter_failed"
            )
            failed = await update_run(
                self._session,
                running.id,
                {
                    "status": "failed",
                    "finished_at": datetime.now(UTC),
                    "error": message,
                    "error_code": error_code,
                    **self._finalize_run_log_fields(running),
                    "stdout_excerpt": stdout or None,
                    "stderr_excerpt": stderr or None,
                },
            )
            assert failed is not None
            await update_wakeup_request(
                self._session,
                running.wakeup_request_id or "",
                {
                    "status": "failed",
                    "finished_at": datetime.now(UTC),
                    "error": message,
                },
            )
            await self._update_runtime_state(agent, failed)
            await update_agent(self._session, agent.id, {"status": "error"})
            with contextlib.suppress(Exception):
                await self._release_issue_execution(failed)
            await self._append_event(
                failed, sequence, "error", message=message, level="error"
            )
            await WorkspaceService(self._session).release_runtime_services_for_run(
                failed.id
            )
            return failed
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
        try:
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
                )
                sequence += 1
            await update_wakeup_request(
                self._session,
                running.wakeup_request_id or "",
                {
                    "status": "completed"
                    if final_status in {"succeeded", "waiting_for_children"}
                    else final_status,
                    "finished_at": datetime.now(UTC),
                    "error": final.error or result.error_message,
                },
            )
            await self._update_runtime_state(agent, final)
            await update_agent(
                self._session,
                agent.id,
                {
                    "status": "idle"
                    if final_status in {"succeeded", "waiting_for_children"}
                    else "error"
                },
            )
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
                "lifecycle",
                message=f"run {final_status}",
                level=(
                    "info"
                    if final_status in {"succeeded", "waiting_for_children"}
                    else "error"
                ),
            )
            await WorkspaceService(self._session).release_runtime_services_for_run(
                final.id
            )
            return final
        except Exception as exc:
            if final.status != "succeeded":
                raise
            message = _exception_message(exc)
            with contextlib.suppress(Exception):
                await self._append_event(
                    final,
                    sequence,
                    "postprocess.warning",
                    message=message,
                    level="warning",
                    payload={
                        "error": message,
                        "errorType": type(exc).__name__,
                        "runStatusPreserved": final.status,
                    },
                )
            with contextlib.suppress(Exception):
                await update_wakeup_request(
                    self._session,
                    running.wakeup_request_id or "",
                    {
                        "status": "completed",
                        "finished_at": datetime.now(UTC),
                        "error": None,
                    },
                )
            with contextlib.suppress(Exception):
                await update_agent(self._session, agent.id, {"status": "idle"})
            with contextlib.suppress(Exception):
                await WorkspaceService(self._session).release_runtime_services_for_run(
                    final.id
                )
            return final

    async def _prepare_execution(
        self, agent: AgentRow, running: HeartbeatRunRow
    ) -> int:
        now = datetime.now(UTC)
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
        await self._append_event(
            running,
            sequence + 1,
            "adapter.invoke",
            message="adapter invocation",
            level="info",
            payload={"agentRuntimeType": agent.agent_runtime_type},
        )
        return sequence + 2

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
                issue = await self._session.get(IssueRow, issue_id)
                if issue is not None and issue.org_id == final.org_id:
                    await self._record_issue_review_closeout_missing(
                        final, issue, context
                    )
            return
        issue_id = _issue_id_from_context(context)
        if issue_id is None:
            return
        issue = await self._session.get(IssueRow, issue_id)
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
        if existing is not None and existing.status not in {
            "failed",
            "cancelled",
            "skipped",
        }:
            return
        await create_wakeup_request(
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
        issue = await self._session.get(IssueRow, issue_id)
        if issue is None or issue.org_id != final.org_id:
            return final
        if self._is_reviewer_issue_run(agent, final, issue, context):
            if await self._run_has_issue_activity(
                final, issue.id, ("issue.review_decision_recorded",)
            ):
                return final
            await self._record_issue_review_closeout_missing(final, issue, context)
            return await self._mark_closeout_governance_failed(
                final,
                "Reviewer issue run exited without `control-plane issue review`.",
            )
        if wake_reason == "issue_review_closeout_missing":
            if await self._run_has_issue_activity(
                final, issue.id, ("issue.review_decision_recorded",)
            ):
                return final
            await self._record_issue_review_closeout_missing(final, issue, context)
            return await self._mark_closeout_governance_failed(
                final,
                "Reviewer close-out run exited without `control-plane issue review`.",
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
                action="issue.waiting_for_children",
                entity_type="issue",
                entity_id=issue.id,
                agent_id=final.agent_id,
                run_id=final.id,
                details={"runId": final.id},
            )
            waiting = await update_run(
                self._session,
                final.id,
                {
                    "status": "waiting_for_children",
                    "error": None,
                    "error_code": None,
                },
            )
            assert waiting is not None
            return waiting
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
        await self._record_issue_closure_convergence_needed(
            final,
            issue,
            origin_run_id=origin_run_id,
            attempts=attempts,
        )
        return await self._mark_closeout_governance_failed(
            final,
            (
                "Issue run exited without `control-plane issue done`, "
                "`control-plane issue block`, or `control-plane issue comment`."
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
                        "exactly one outcome with `control-plane issue review "
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

    async def _release_issue_execution(self, final: HeartbeatRunRow) -> None:
        issue_id = _issue_id_from_context(final.context_snapshot)
        issue = await self._session.get(IssueRow, issue_id) if issue_id else None
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
        )
        criteria = [
            IssueRow.execution_run_id == final.id,
            IssueRow.checkout_run_id == final.id,
        ]
        if issue_id is not None:
            criteria.append(IssueRow.id == issue_id)
        values: dict[str, Any] = {
            "updated_at": datetime.now(UTC),
        }
        if final.status in {
            "failed",
            "timed_out",
            "cancelled",
            "succeeded",
            "waiting_for_children",
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
        if issue_id is not None and final.status in {
            "failed",
            "timed_out",
            "cancelled",
            "succeeded",
            "waiting_for_children",
        }:
            await self._promote_deferred_issue_wakeup(final.org_id, issue_id)
        if issue is not None:
            await self._wake_parent_after_child_settled(final, issue)

    async def _issue_has_active_children(self, issue_id: str) -> bool:
        result = await self._session.execute(
            select(IssueRow.id)
            .where(
                IssueRow.parent_id == issue_id,
                IssueRow.status.in_(("backlog", "todo", "in_progress", "in_review")),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    async def _wake_parent_after_child_settled(
        self, final: HeartbeatRunRow, issue: IssueRow
    ) -> None:
        await self.queue_parent_continuation_for_settled_child(
            issue.id, expected_org_id=final.org_id
        )

    async def queue_parent_continuation_for_settled_child(
        self, child_issue_id: str, *, expected_org_id: str | None = None
    ) -> str | None:
        issue = await self._session.get(IssueRow, child_issue_id)
        if issue is None or (
            expected_org_id is not None and issue.org_id != expected_org_id
        ):
            return None
        if issue.parent_id is None or issue.status not in {
            "done",
            "cancelled",
            "blocked",
        }:
            return None
        if await self._issue_has_active_children(issue.parent_id):
            return None
        parent = await self._session.get(IssueRow, issue.parent_id)
        if (
            parent is None
            or parent.org_id != issue.org_id
            or parent.status not in {"todo", "in_progress"}
            or not parent.assignee_agent_id
        ):
            return None
        await self.wakeup(
            parent.assignee_agent_id,
            {
                "source": "assignment",
                "triggerDetail": "system",
                "reason": "issue_children_settled",
                "idempotencyKey": f"issue:{parent.id}:children_settled:{issue.id}",
                "payload": {
                    "issueId": parent.id,
                    "mutation": "children_settled",
                    "completedChildIssueId": issue.id,
                },
                "contextSnapshot": {
                    "issueId": parent.id,
                    "source": "issue.children_settled",
                    "wakeSource": "assignment",
                    "wakeReason": "issue_children_settled",
                    "completedChildIssueId": issue.id,
                    "issue": {
                        "id": parent.id,
                        "identifier": parent.identifier,
                        "title": parent.title,
                        "description": parent.description,
                        "status": parent.status,
                        "priority": parent.priority,
                    },
                },
            },
            actor_type="system",
            actor_id="heartbeat_child_coordination",
            execute_immediately=False,
        )
        return parent.assignee_agent_id

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
                        "blocked. Use `control-plane issue review`."
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
            await self._claim_issue_execution_for_assignment_run(
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

    async def _claim_issue_execution_for_assignment_run(
        self,
        agent: AgentRow,
        run: HeartbeatRunRow,
        context_snapshot: dict[str, Any],
        *,
        issue: IssueRow | None = None,
    ) -> None:
        if run.invocation_source != "assignment":
            return
        issue_id = _issue_id_from_context(context_snapshot)
        if issue_id is None:
            return
        issue = issue or await self._session.get(IssueRow, issue_id)
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
        return {
            "enabled": enabled if isinstance(enabled, bool) else True,
            "intervalSec": interval_sec
            if interval_sec > 0
            else float(HEARTBEAT_INTERVAL_DEFAULT_SEC),
            "wakeOnDemand": (
                wake_on_demand if isinstance(wake_on_demand, bool) else True
            ),
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
        ):
            value = payload.get(source_key)
            if isinstance(value, str) and value:
                context[target_key] = value
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

        heartbeat_context = await IssueService(self._session).get_heartbeat_context(
            issue_id
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
        issue = await self._session.get(IssueRow, issue_id)
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
        "createdAt": row.created_at.isoformat(),
    }


async def dispatch_queued_agent(
    session_factory: async_sessionmaker[AsyncSession], agent_id: str
) -> None:
    async with session_factory() as session:
        async with session.begin():
            run_ids = await HeartbeatService(session).claim_queued_for_dispatch(
                agent_id
            )
    if not run_ids:
        return

    async def execute(run_id: str) -> str | None:
        async with session_factory() as session:
            service = HeartbeatService(session, commit_process_metadata=True)
            try:
                final = await service.execute_claimed_run(run_id)
                reviewer_agent_id: str | None = None
                if (
                    final is not None
                    and final["status"] == "succeeded"
                    and final["invocationSource"] == "assignment"
                ):
                    issue_id = _issue_id_from_context(final.get("contextSnapshot"))
                    issue = await session.get(IssueRow, issue_id) if issue_id else None
                    if (
                        issue is not None
                        and issue.status == "in_review"
                        and issue.reviewer_agent_id
                        and issue.reviewer_agent_id != agent_id
                    ):
                        reviewer_agent_id = issue.reviewer_agent_id
                await session.commit()
                return reviewer_agent_id
            except Exception:
                await session.rollback()
                raise

    next_agent_ids = {
        reviewer_agent_id
        for reviewer_agent_id in await asyncio.gather(
            *(execute(run_id) for run_id in run_ids)
        )
        if reviewer_agent_id is not None
    }
    next_agent_ids.add(agent_id)
    await asyncio.gather(
        *(
            dispatch_queued_agent(session_factory, next_agent_id)
            for next_agent_id in next_agent_ids
        )
    )


async def dispatch_all_queued_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            heartbeat = HeartbeatService(session)
            scheduled_agent_ids = await heartbeat.materialize_due_scheduled_wakeups()
            agent_ids = scheduled_agent_ids | await list_queued_agent_ids(session)
    await asyncio.gather(
        *(dispatch_queued_agent(session_factory, agent_id) for agent_id in agent_ids)
    )
