from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, cast

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
from packages.database.queries.heartbeat import (
    append_run_event,
    claim_queued_run,
    create_run,
    create_wakeup_request,
    get_run,
    get_wakeup_by_idempotency_key,
    list_queued_agent_ids,
    list_queued_runs,
    list_run_events,
    list_running_run_ids,
    list_runs,
    list_runs_by_status,
    list_wakeup_requests_by_status,
    update_run,
    update_wakeup_request,
)
from packages.database.schema import (
    Agent as AgentRow,
    HeartbeatRun as HeartbeatRunRow,
    HeartbeatRunEvent as HeartbeatRunEventRow,
)
from packages.runtimes import RuntimeExecutionContext, get_runtime_adapter
from packages.shared.constants.heartbeat import (
    AGENT_RUN_CONCURRENCY_DEFAULT,
    AGENT_RUN_CONCURRENCY_MAX,
    AGENT_RUN_CONCURRENCY_MIN,
    HeartbeatInvocationSource,
    HeartbeatRunStatus,
    WakeupTriggerDetail,
)
from packages.shared.types.heartbeat import (
    HeartbeatRun,
    HeartbeatRunEvent,
    WakeAgentPayload,
)

from .agents import AgentConflictError


class HeartbeatService:
    _start_locks: ClassVar[dict[str, asyncio.Lock]] = {}
    _active_run_ids: ClassVar[dict[str, set[str]]] = {}
    _cancel_events: ClassVar[dict[str, asyncio.Event]] = {}

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

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
        idempotency_key = payload.get("idempotencyKey")
        if idempotency_key:
            existing = await get_wakeup_by_idempotency_key(
                self._session, agent.id, idempotency_key
            )
            if existing is not None and existing.run_id:
                existing_run = await get_run(self._session, existing.run_id)
                if existing_run is not None:
                    return self._to_run(existing_run)
            if existing is not None and existing.status == "deferred_agent_paused":
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
        return self._to_run(row) if row is not None else None

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
        invocation_source = (
            "automation" if recovery_trigger == "automatic" else "on_demand"
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
        run = await create_run(
            self._session,
            {
                "org_id": agent.org_id,
                "agent_id": agent.id,
                "invocation_source": invocation_source,
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
        await update_wakeup_request(self._session, wakeup.id, {"run_id": run.id})
        if not execute_immediately:
            return self._to_run(run)
        return self._to_run(await self._start_if_capacity(agent, run))

    async def recover_orphaned_runs(self) -> list[HeartbeatRun]:
        recovered: list[HeartbeatRun] = []
        active_ids = (
            set().union(*self._active_run_ids.values())
            if self._active_run_ids
            else set()
        )
        for run in await list_runs_by_status(self._session, "running"):
            if run.id in active_ids:
                continue
            failed = await update_run(
                self._session,
                run.id,
                {
                    "status": "failed",
                    "finished_at": datetime.now(UTC),
                    "error": "Run interrupted before server recovery",
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
            )
            if run.process_loss_retry_count >= 1:
                continue
            retry = await self.retry_run(
                run.id,
                actor_type="system",
                actor_id="heartbeat_scheduler",
                execute_immediately=False,
                recovery_trigger="automatic",
            )
            if retry is not None:
                recovered.append(retry)
        return recovered

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
            run = await create_run(
                self._session,
                {
                    "org_id": agent.org_id,
                    "agent_id": agent.id,
                    "invocation_source": payload["source"],
                    "trigger_detail": payload["triggerDetail"],
                    "status": "queued",
                    "wakeup_request_id": wakeup.id,
                    "context_snapshot": {"resumedFromPaused": True},
                },
            )
            await update_wakeup_request(self._session, wakeup.id, {"run_id": run.id})
            resumed.append(
                self._to_run(
                    await self._start_if_capacity(agent, run)
                    if execute_immediately
                    else run
                )
            )
        return resumed

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
        run = await create_run(
            self._session,
            {
                "org_id": agent.org_id,
                "agent_id": agent.id,
                "invocation_source": payload.get("source", "on_demand"),
                "trigger_detail": payload.get("triggerDetail", "manual"),
                "status": "queued",
                "wakeup_request_id": wakeup.id,
                "context_snapshot": {
                    "triggeredBy": actor_type,
                    "actorId": actor_id,
                    "forceFreshSession": payload.get("forceFreshSession", False),
                },
            },
        )
        await update_wakeup_request(self._session, wakeup.id, {"run_id": run.id})
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
            await self._prepare_execution(agent, running)
        sequence = 3
        cancellation = asyncio.Event()
        self._cancel_events[running.id] = cancellation

        stdout = ""
        stderr = ""

        async def on_log(stream: str, chunk: str) -> None:
            nonlocal sequence, stdout, stderr
            if stream == "stdout":
                stdout += chunk
            else:
                stderr += chunk
            await self._append_event(
                running,
                sequence,
                "log",
                message=chunk,
                stream=stream,
                level="info" if stream == "stdout" else "error",
            )
            sequence += 1

        try:
            adapter = get_runtime_adapter(agent.agent_runtime_type)
            result = await adapter.execute(
                RuntimeExecutionContext(
                    run_id=running.id,
                    agent_id=agent.id,
                    org_id=agent.org_id,
                    agent_name=agent.name,
                    config=agent.agent_runtime_config,
                    on_log=on_log,
                    cancel_event=cancellation,
                )
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
                    "result_json": result.result_json,
                    "stdout_excerpt": stdout or None,
                    "stderr_excerpt": stderr or None,
                },
            )
            assert final is not None
            await update_wakeup_request(
                self._session,
                running.wakeup_request_id or "",
                {
                    "status": "completed"
                    if final_status == "succeeded"
                    else final_status,
                    "finished_at": datetime.now(UTC),
                    "error": result.error_message,
                },
            )
            await self._update_runtime_state(agent, final)
            await update_agent(
                self._session,
                agent.id,
                {"status": "idle" if final_status == "succeeded" else "error"},
            )
            await self._append_event(
                final,
                sequence,
                "lifecycle",
                message=f"run {final_status}",
                level="info" if final_status == "succeeded" else "error",
            )
            return final
        except Exception as exc:
            if cancellation.is_set():
                return running
            await self._session.refresh(running)
            if running.status == "cancelled":
                return running
            message = str(exc)
            failed = await update_run(
                self._session,
                running.id,
                {
                    "status": "failed",
                    "finished_at": datetime.now(UTC),
                    "error": message,
                    "error_code": "adapter_failed",
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
            await self._append_event(
                failed, sequence, "error", message=message, level="error"
            )
            return failed
        finally:
            self._cancel_events.pop(running.id, None)

    async def _prepare_execution(
        self, agent: AgentRow, running: HeartbeatRunRow
    ) -> None:
        now = datetime.now(UTC)
        await update_wakeup_request(
            self._session,
            running.wakeup_request_id or "",
            {"status": "claimed", "claimed_at": now},
        )
        await update_agent(
            self._session, agent.id, {"status": "running", "last_heartbeat_at": now}
        )
        await self._append_event(
            running, 1, "lifecycle", message="run started", level="info"
        )
        await self._append_event(
            running,
            2,
            "adapter.invoke",
            message="adapter invocation",
            level="info",
            payload={"agentRuntimeType": agent.agent_runtime_type},
        )

    async def _next_event_sequence(self, run_id: str) -> int:
        events = await list_run_events(self._session, run_id, limit=1000)
        return (events[-1].seq if events else 0) + 1

    def _heartbeat_policy(self, agent: AgentRow) -> dict[str, float | bool]:
        heartbeat = agent.runtime_config.get("heartbeat", {})
        config = heartbeat if isinstance(heartbeat, dict) else {}
        enabled = config.get("enabled", True)
        interval = config.get("intervalSec", 0)
        return {
            "enabled": enabled if isinstance(enabled, bool) else True,
            "intervalSec": (
                max(0.0, float(interval))
                if isinstance(interval, (int, float)) and not isinstance(interval, bool)
                else 0.0
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
        return {
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

    def _to_run(self, row: HeartbeatRunRow) -> HeartbeatRun:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "agentId": row.agent_id,
            "invocationSource": cast(HeartbeatInvocationSource, row.invocation_source),
            "triggerDetail": cast(WakeupTriggerDetail | None, row.trigger_detail),
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

    def _to_event(self, row: HeartbeatRunEventRow) -> HeartbeatRunEvent:
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

    async def execute(run_id: str) -> None:
        async with session_factory() as session:
            async with session.begin():
                await HeartbeatService(session).execute_claimed_run(run_id)

    await asyncio.gather(*(execute(run_id) for run_id in run_ids))


async def dispatch_all_queued_runs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        async with session.begin():
            agent_ids = await list_queued_agent_ids(session)
    await asyncio.gather(
        *(dispatch_queued_agent(session_factory, agent_id) for agent_id in agent_ids)
    )
