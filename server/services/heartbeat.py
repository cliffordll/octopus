from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import get_agent_by_id, update_agent
from packages.database.queries.agent_state import (
    create_runtime_state,
    get_runtime_state,
    update_runtime_state,
)
from packages.database.queries.heartbeat import (
    append_run_event,
    create_run,
    create_wakeup_request,
    get_run,
    list_run_events,
    list_runs,
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
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def wakeup(
        self,
        agent_id: str,
        payload: WakeAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> HeartbeatRun | None:
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None:
            return None
        if agent.status in ("terminated", "pending_approval"):
            raise AgentConflictError("Agent is not invokable in its current state")
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
        executed = await self._execute_run(agent, run)
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

    async def list_for_org(
        self, org_id: str, agent_id: str | None = None
    ) -> list[HeartbeatRun]:
        rows = await list_runs(self._session, org_id, agent_id)
        return [self._to_run(row) for row in rows]

    async def get(self, run_id: str) -> HeartbeatRun | None:
        row = await get_run(self._session, run_id)
        return self._to_run(row) if row is not None else None

    async def list_events(self, run_id: str) -> list[HeartbeatRunEvent]:
        rows = await list_run_events(self._session, run_id)
        return [self._to_event(row) for row in rows]

    async def _execute_run(
        self, agent: AgentRow, queued_run: HeartbeatRunRow
    ) -> HeartbeatRunRow:
        now = datetime.now(UTC)
        running = await update_run(
            self._session, queued_run.id, {"status": "running", "started_at": now}
        )
        assert running is not None
        await update_wakeup_request(
            self._session,
            queued_run.wakeup_request_id or "",
            {"status": "claimed", "claimed_at": now},
        )
        await update_agent(
            self._session, agent.id, {"status": "running", "last_heartbeat_at": now}
        )
        sequence = 1
        await self._append_event(
            running, sequence, "lifecycle", message="run started", level="info"
        )
        sequence += 1
        await self._append_event(
            running,
            sequence,
            "adapter.invoke",
            message="adapter invocation",
            level="info",
            payload={"agentRuntimeType": agent.agent_runtime_type},
        )
        sequence += 1

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
                )
            )
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
                    "result_json": result.result_json,
                    "stdout_excerpt": stdout or None,
                    "stderr_excerpt": stderr or None,
                },
            )
            assert final is not None
            await update_wakeup_request(
                self._session,
                queued_run.wakeup_request_id or "",
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
                queued_run.wakeup_request_id or "",
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
                "last_error": run.error,
            },
        )

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
