from __future__ import annotations

import sys
import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from packages.database.clients import (
    async_transaction,
    create_database_engine,
    create_session_factory,
)
from packages.database.queries.agents import advance_agent_heartbeat_check
from packages.database.schema import (
    ActivityLog,
    Agent as AgentRow,
    AgentWakeupRequest,
    Base,
    HeartbeatRun,
    HeartbeatRunEvent,
    Issue,
    Organization,
)
from packages.runtimes.types import RuntimeExecutionContext, RuntimeExecutionResult
from packages.shared.constants.agent import AgentRuntimeType
from packages.shared.types.agent import Agent
from packages.shared.types.heartbeat import WakeAgentPayload
from server.services.agents import AgentService
from server.services.heartbeat import (
    HeartbeatService,
    WorkspacePreparationCoordinator,
    dispatch_queued_agent,
)
from server.services.run_lifecycle import RunFinalizationService
from server.services.projects import ProjectService
from server.services.run_repair import IssueRunRepairService
from server.services.workspaces import WorkspaceService


async def _closeout_signal_exists(*args: object, **kwargs: object) -> bool:
    return True


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    async with factory() as active_session:
        yield active_session
    await engine.dispose()


async def _seed_agent(
    session: AsyncSession,
    *,
    name: str,
    runtime_type: AgentRuntimeType = "process",
    runtime_config: dict | None = None,
) -> Agent:
    org = Organization(url_key=name.lower(), name=name, issue_prefix="RUN")
    agent_service = AgentService(session)
    async with async_transaction(session):
        session.add(org)
        await session.flush()
        agent_runtime_config = (
            {"model": "openai/gpt-5"}
            if runtime_type == "opencode_local"
            else {
                "command": sys.executable,
                "args": ["-c", "print('run-ok')"],
            }
        )
        agent = await agent_service.create_agent(
            org.id,
            {
                "name": name,
                "agentRuntimeType": runtime_type,
                "runtimeConfig": runtime_config or {},
                "agentRuntimeConfig": agent_runtime_config,
            },
            actor_type="board",
            actor_id="local-board",
        )
    return agent


async def test_wakeup_idempotency_reuses_existing_run(session: AsyncSession) -> None:
    agent = await _seed_agent(session, name="Idempotent")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        first = await heartbeat.wakeup(
            agent["id"],
            {"idempotencyKey": "request-1"},
            actor_type="board",
            actor_id="local-board",
        )
        second = await heartbeat.wakeup(
            agent["id"],
            {"idempotencyKey": "request-1"},
            actor_type="board",
            actor_id="local-board",
        )

    assert first is not None and second is not None
    assert second["id"] == first["id"]
    assert len((await session.execute(select(HeartbeatRun))).scalars().all()) == 1


async def test_claim_queued_run_refreshes_loaded_sqlite_identity(
    session: AsyncSession,
) -> None:
    from packages.database.queries.heartbeat import claim_queued_run

    agent = await _seed_agent(session, name="ClaimRefresh")
    async with async_transaction(session):
        queued = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            run_purpose="task_execution",
            trigger_detail="manual",
            status="queued",
        )
        session.add(queued)
        await session.flush()
        loaded = await session.get(HeartbeatRun, queued.id)
        assert loaded is queued
        claimed = await claim_queued_run(session, queued.id, datetime.now(UTC))

    assert claimed is not None
    assert claimed.status == "running"
    assert claimed.execution_owner_token is not None
    assert claimed.execution_lease_expires_at is not None


async def test_runtime_diagnostic_reuses_active_diagnostic_run(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="DiagnosticSingleFlight")
    heartbeat = HeartbeatService(session)
    payload: WakeAgentPayload = {
        "source": "on_demand",
        "triggerDetail": "manual",
        "reason": "runtime_diagnostic",
        "idempotencyKey": f"runtime-diagnostic:{agent['id']}",
    }

    first = await heartbeat.wakeup(
        agent["id"],
        payload,
        actor_type="board",
        actor_id="local-board",
        execute_immediately=False,
    )
    second = await heartbeat.wakeup(
        agent["id"],
        payload,
        actor_type="board",
        actor_id="local-board",
        execute_immediately=False,
    )

    assert first is not None and second is not None
    assert second["id"] == first["id"]
    first_context = first["contextSnapshot"]
    assert first_context is not None
    assert first_context["wakeReason"] == "runtime_diagnostic"
    assert len((await session.execute(select(HeartbeatRun))).scalars().all()) == 1


async def test_manual_wakeup_preflights_actionable_work(session: AsyncSession) -> None:
    agent = await _seed_agent(session, name="ManualPreflight")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        skipped = await heartbeat.wakeup_if_actionable(
            agent["id"],
            {},
            actor_type="board",
            actor_id="local-board",
            execute_immediately=False,
        )
    assert skipped is None
    assert (await session.execute(select(HeartbeatRun))).scalars().all() == []
    await session.rollback()

    async with async_transaction(session):
        session.add(
            Issue(
                org_id=agent["orgId"],
                title="Actionable manual wakeup",
                status="todo",
                priority="medium",
                assignee_agent_id=agent["id"],
            )
        )
        await session.flush()
        run = await heartbeat.wakeup_if_actionable(
            agent["id"],
            {},
            actor_type="board",
            actor_id="local-board",
            execute_immediately=False,
        )

    assert run is not None
    assert run["status"] == "queued"
    run_context = run["contextSnapshot"]
    assert run_context is not None
    assert run_context["wakeReason"] == "manual_wakeup"


async def test_manual_wakeup_does_not_recover_pending_work_while_paused(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="PausedManualPreflight")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        agent_row = await session.get(AgentRow, agent["id"])
        assert agent_row is not None
        agent_row.status = "paused"
        issue = Issue(
            org_id=agent["orgId"],
            title="Paused pending work",
            status="todo",
            priority="medium",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        pending = AgentWakeupRequest(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            source="assignment",
            trigger_detail="system",
            reason="issue_assigned",
            payload={"issueId": issue.id},
            status="queued",
        )
        session.add(pending)
        await session.flush()
        result = await heartbeat.wakeup_if_actionable(
            agent["id"],
            {},
            actor_type="board",
            actor_id="local-board",
            execute_immediately=False,
        )

    assert result is None
    assert (await session.execute(select(HeartbeatRun))).scalars().all() == []
    await session.refresh(pending)
    assert pending.status == "queued"


async def test_queued_run_resumes_after_concurrency_slot_is_available(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="Queued",
        runtime_config={"heartbeat": {"maxConcurrentRuns": 1}},
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        blocking = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="running",
        )
        session.add(blocking)
        await session.flush()
        queued = await heartbeat.wakeup(
            agent["id"], {}, actor_type="board", actor_id="local-board"
        )
    assert queued is not None and queued["status"] == "queued"

    async with async_transaction(session):
        blocking.status = "succeeded"
        blocking.finished_at = datetime.now(UTC)
        resumed = await heartbeat.resume_queued_runs(agent["id"])
    assert resumed[0]["id"] == queued["id"]
    assert resumed[0]["status"] == "succeeded"


async def test_dispatch_claims_queued_runs_when_concurrency_slots_remain(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="ConcurrentQueued",
        runtime_config={"heartbeat": {"maxConcurrentRuns": 3}},
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        blocking = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="timer",
            trigger_detail="system",
            status="running",
        )
        session.add(blocking)
        await session.flush()
        first = await heartbeat.wakeup(
            agent["id"],
            {"source": "assignment", "triggerDetail": "system"},
            actor_type="board",
            actor_id="local-board",
            execute_immediately=False,
        )
        second = await heartbeat.wakeup(
            agent["id"],
            {"source": "assignment", "triggerDetail": "system"},
            actor_type="board",
            actor_id="local-board",
            execute_immediately=False,
        )

    assert first is not None and first["status"] == "queued"
    assert second is not None and second["status"] == "queued"

    async with async_transaction(session):
        claimed_ids = await heartbeat.claim_queued_for_dispatch(agent["id"])

    assert set(claimed_ids) == {first["id"], second["id"]}
    rows = (
        (
            await session.execute(
                select(HeartbeatRun).where(
                    HeartbeatRun.id.in_([first["id"], second["id"]])
                )
            )
        )
        .scalars()
        .all()
    )
    assert {row.status for row in rows} == {"running"}


async def test_assignment_success_moves_issue_to_review_and_wakes_reviewer(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        HeartbeatService,
        "_run_has_issue_closeout_signal",
        _closeout_signal_exists,
    )
    assignee = await _seed_agent(session, name="Assignee")
    agent_service = AgentService(session)
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        reviewer = await agent_service.create_agent(
            assignee["orgId"],
            {
                "name": "Reviewer",
                "agentRuntimeConfig": {
                    "command": sys.executable,
                    "args": ["-c", "print('review-ready')"],
                },
            },
            actor_type="board",
            actor_id="local-board",
        )
        issue = Issue(
            org_id=assignee["orgId"],
            title="Review after run",
            status="todo",
            priority="medium",
            identifier="RUN-1",
            assignee_agent_id=assignee["id"],
            reviewer_agent_id=reviewer["id"],
        )
        session.add(issue)
        await session.flush()
        run = await heartbeat.wakeup(
            assignee["id"],
            {
                "source": "assignment",
                "triggerDetail": "manual",
                "payload": {"issueId": issue.id},
                "contextSnapshot": {
                    "issueId": issue.id,
                    "wakeReason": "issue_execute",
                },
            },
            actor_type="board",
            actor_id="local-board",
        )

    assert run is not None and run["status"] == "succeeded"
    persisted_issue = (await session.execute(select(Issue))).scalar_one()
    assert persisted_issue.status == "in_review"
    assert persisted_issue.execution_run_id is None
    reviewer_wakeup = (
        await session.execute(
            select(AgentWakeupRequest).where(
                AgentWakeupRequest.agent_id == reviewer["id"]
            )
        )
    ).scalar_one()
    assert reviewer_wakeup.source == "review"
    assert reviewer_wakeup.status == "queued"
    assert isinstance(reviewer_wakeup.payload, dict)
    assert reviewer_wakeup.payload["issueId"] == persisted_issue.id
    activity = (
        await session.execute(
            select(ActivityLog).where(ActivityLog.entity_id == persisted_issue.id)
        )
    ).scalar_one()
    assert activity.action == "issue.updated"
    assert activity.run_id == run["id"]
    assert isinstance(activity.details, dict)
    assert activity.details["reason"] == "run_succeeded"


async def test_failed_assignment_run_blocks_issue(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    class FailingAdapter:
        type = "process"

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            return RuntimeExecutionResult(
                exit_code=1,
                error_message="runtime permission rejected",
            )

    assignee = await _seed_agent(session, name="FailingAssignee")
    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda _runtime_type: FailingAdapter(),
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        issue = Issue(
            org_id=assignee["orgId"],
            title="Failing child task",
            status="in_progress",
            priority="medium",
            identifier="RUN-FAIL",
            assignee_agent_id=assignee["id"],
        )
        session.add(issue)
        await session.flush()
        run = await heartbeat.wakeup(
            assignee["id"],
            {
                "source": "assignment",
                "triggerDetail": "system",
                "payload": {"issueId": issue.id},
                "contextSnapshot": {
                    "issueId": issue.id,
                    "wakeReason": "issue_execute",
                },
            },
            actor_type="board",
            actor_id="local-board",
        )

    assert run is not None
    assert run["status"] == "failed"
    assert run["errorCode"] == "adapter_failed"
    persisted_issue = (
        await session.execute(select(Issue).where(Issue.identifier == "RUN-FAIL"))
    ).scalar_one()
    assert persisted_issue.status == "blocked"
    assert persisted_issue.execution_run_id is None
    assert persisted_issue.checkout_run_id is None
    activity = (
        await session.execute(
            select(ActivityLog).where(ActivityLog.entity_id == persisted_issue.id)
        )
    ).scalar_one()
    assert activity.action == "issue.updated"
    assert activity.actor_type == "agent"
    assert activity.run_id == run["id"]
    assert isinstance(activity.details, dict)
    assert activity.details["status"] == "blocked"
    assert activity.details["fromStatus"] == "in_progress"
    assert activity.details["reason"] == "run_failed"
    assert activity.details["error"] == "runtime permission rejected"


async def test_each_assignment_success_creates_a_new_reviewer_wakeup(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        HeartbeatService,
        "_run_has_issue_closeout_signal",
        _closeout_signal_exists,
    )
    assignee = await _seed_agent(session, name="RepeatAssignee")
    agent_service = AgentService(session)
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        reviewer = await agent_service.create_agent(
            assignee["orgId"],
            {
                "name": "RepeatReviewer",
                "agentRuntimeConfig": {
                    "command": sys.executable,
                    "args": ["-c", "print('review-ready')"],
                },
            },
            actor_type="board",
            actor_id="local-board",
        )
        issue = Issue(
            org_id=assignee["orgId"],
            title="Repeat review after changes",
            status="in_progress",
            priority="medium",
            identifier="RUN-REPEAT",
            assignee_agent_id=assignee["id"],
            reviewer_agent_id=reviewer["id"],
        )
        session.add(issue)
        await session.flush()
        first = await heartbeat.wakeup(
            assignee["id"],
            {
                "source": "assignment",
                "triggerDetail": "system",
                "payload": {"issueId": issue.id},
                "contextSnapshot": {
                    "issueId": issue.id,
                    "wakeReason": "issue_execute",
                },
            },
            actor_type="board",
            actor_id="local-board",
        )
        await session.refresh(issue)
        first_reviewer_wakeups = (
            (
                await session.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == reviewer["id"],
                        AgentWakeupRequest.reason == "issue_review_requested",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(first_reviewer_wakeups) == 1
        issue.status = "in_progress"
        second = await heartbeat.wakeup(
            assignee["id"],
            {
                "source": "assignment",
                "triggerDetail": "system",
                "payload": {"issueId": issue.id},
                "contextSnapshot": {
                    "issueId": issue.id,
                    "wakeReason": "issue_changes_requested",
                },
            },
            actor_type="board",
            actor_id="local-board",
        )
        reviewer_wakeups = (
            (
                await session.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == reviewer["id"],
                        AgentWakeupRequest.reason == "issue_review_requested",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(reviewer_wakeups) == 2
        origin_run_ids: set[str] = set()
        for wakeup in reviewer_wakeups:
            assert wakeup.payload is not None
            origin_run_ids.add(wakeup.payload["originRunId"])

    assert first is not None and first["status"] == "succeeded"
    assert second is not None and second["status"] == "succeeded"
    assert origin_run_ids == {
        first["id"],
        second["id"],
    }


async def test_assignment_dispatch_immediately_dispatches_reviewer_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        HeartbeatService,
        "_run_has_issue_closeout_signal",
        _closeout_signal_exists,
    )
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    try:
        async with factory() as session:
            assignee = await _seed_agent(session, name="DispatchAssignee")
            agent_service = AgentService(session)
            heartbeat = HeartbeatService(session)
            async with async_transaction(session):
                reviewer = await agent_service.create_agent(
                    assignee["orgId"],
                    {
                        "name": "DispatchReviewer",
                        "agentRuntimeConfig": {
                            "command": sys.executable,
                            "args": ["-c", "print('review-ready')"],
                        },
                    },
                    actor_type="board",
                    actor_id="local-board",
                )
                issue = Issue(
                    org_id=assignee["orgId"],
                    title="Dispatch review after run",
                    status="todo",
                    priority="medium",
                    identifier="RUN-DISPATCH",
                    assignee_agent_id=assignee["id"],
                    reviewer_agent_id=reviewer["id"],
                )
                session.add(issue)
                await session.flush()
                run = await heartbeat.wakeup(
                    assignee["id"],
                    {
                        "source": "assignment",
                        "triggerDetail": "system",
                        "reason": "issue_execute",
                        "payload": {"issueId": issue.id},
                        "contextSnapshot": {
                            "issueId": issue.id,
                            "wakeReason": "issue_execute",
                        },
                    },
                    actor_type="board",
                    actor_id="local-board",
                    execute_immediately=False,
                )

        assert run is not None and run["status"] == "queued"
        await dispatch_queued_agent(factory, assignee["id"])

        async with factory() as verify:
            reviewer_run = (
                await verify.execute(
                    select(HeartbeatRun).where(
                        HeartbeatRun.agent_id == reviewer["id"],
                        HeartbeatRun.run_purpose == "review",
                        HeartbeatRun.invocation_source == "review",
                        HeartbeatRun.context_snapshot["wakeReason"].as_string()
                        == "issue_review_requested",
                    )
                )
            ).scalar_one()
            wakeup = await verify.get(AgentWakeupRequest, reviewer_run.wakeup_request_id)
            reviewer_row = await verify.get(AgentRow, reviewer["id"])
            assert reviewer_run.status == "failed", {
                "wakeupStatus": wakeup.status if wakeup else None,
                "agentStatus": reviewer_row.status if reviewer_row else None,
                "executionLease": reviewer_run.execution_lease_expires_at,
            }
            assert reviewer_run.error_code == "closeout_missing"
            assert reviewer_run.started_at is not None
            assert reviewer_run.finished_at is not None
            queued_reviewer_runs = (
                await verify.execute(
                    select(HeartbeatRun).where(
                        HeartbeatRun.agent_id == reviewer["id"],
                        HeartbeatRun.status == "queued",
                    )
                )
            ).scalars()
            assert list(queued_reviewer_runs) == []
    finally:
        await engine.dispose()


async def test_dispatch_workspace_prepare_failure_uses_clean_finalization_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    original_transition = RunFinalizationService.transition
    transition_attempts = 0

    async def fail_workspace_prepare(*args: object, **kwargs: object) -> object:
        raise RuntimeError("database is locked")

    async def fail_first_terminal_transition(
        self: RunFinalizationService,
        run_id: str,
        status: str,
        values: dict,
        **kwargs: object,
    ) -> object:
        nonlocal transition_attempts
        transition_attempts += 1
        if transition_attempts == 1:
            raise RuntimeError("transaction is no longer usable")
        return await original_transition(
            self,
            run_id,
            status,  # type: ignore[arg-type]
            values,
            **kwargs,
        )

    monkeypatch.setattr(
        WorkspaceService,
        "prepare_runtime_context_for_heartbeat",
        fail_workspace_prepare,
    )
    monkeypatch.setattr(
        RunFinalizationService, "transition", fail_first_terminal_transition
    )
    try:
        async with factory() as session:
            agent = await _seed_agent(session, name="WorkspacePrepareFailure")
            heartbeat = HeartbeatService(session)
            async with async_transaction(session):
                run = await heartbeat.wakeup(
                    agent["id"],
                    {"source": "assignment", "triggerDetail": "system"},
                    actor_type="board",
                    actor_id="local-board",
                    execute_immediately=False,
                )

        assert run is not None
        await dispatch_queued_agent(factory, agent["id"])

        async with factory() as verify:
            stored = await verify.get(HeartbeatRun, run["id"])
            assert stored is not None
            assert stored.status == "failed"
            assert stored.error_code == "workspace_prepare_failed"
            assert stored.finished_at is not None
            assert stored.terminal_effects_pending is False
            events = (
                await verify.execute(
                    select(HeartbeatRunEvent).where(
                        HeartbeatRunEvent.run_id == stored.id
                    )
                )
            ).scalars()
            event_types = [event.event_type for event in events]
            assert "adapter.invoke" not in event_types
            assert "workspace.preflight" not in event_types
        assert transition_attempts == 2
    finally:
        await engine.dispose()


async def test_four_runs_serialize_workspace_prepare_then_execute_in_parallel(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from server.services import heartbeat as heartbeat_module

    database_path = tmp_path / "workspace-concurrency.sqlite3"
    engine: AsyncEngine = create_database_engine(
        f"sqlite+aiosqlite:///{database_path.as_posix()}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    original_prepare = WorkspaceService.prepare_runtime_context_for_heartbeat
    active_prepares = 0
    max_active_prepares = 0
    active_adapters = 0
    max_active_adapters = 0
    all_adapters_started = asyncio.Event()

    async def observed_prepare(
        self: WorkspaceService, *args: object, **kwargs: object
    ) -> dict:
        nonlocal active_prepares, max_active_prepares
        active_prepares += 1
        max_active_prepares = max(max_active_prepares, active_prepares)
        try:
            await asyncio.sleep(0.02)
            return await original_prepare(self, *args, **kwargs)  # type: ignore[arg-type]
        finally:
            active_prepares -= 1

    class ParallelAdapter:
        type = "process"

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            nonlocal active_adapters, max_active_adapters
            active_adapters += 1
            max_active_adapters = max(max_active_adapters, active_adapters)
            if active_adapters == 4:
                all_adapters_started.set()
            try:
                await asyncio.wait_for(all_adapters_started.wait(), timeout=2)
                return RuntimeExecutionResult(exit_code=0)
            finally:
                active_adapters -= 1

    monkeypatch.setattr(
        WorkspaceService,
        "prepare_runtime_context_for_heartbeat",
        observed_prepare,
    )
    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda _runtime_type: ParallelAdapter(),
    )
    try:
        async with factory() as session:
            org = Organization(
                url_key="workspace-concurrency",
                name="Workspace Concurrency",
                issue_prefix="WSC",
            )
            session.add(org)
            await session.flush()
            project_cwd = tmp_path / "shared-project"
            project_cwd.mkdir()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Shared Workspace Project"},
                actor_type="board",
                actor_id="local-board",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": str(project_cwd)},
                actor_type="board",
                actor_id="local-board",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Parallel shared workspace work",
            )
            session.add(issue)
            await session.flush()
            agent = await AgentService(session).create_agent(
                org.id,
                {
                    "name": "Workspace Agent",
                    "agentRuntimeType": "process",
                    "runtimeConfig": {"heartbeat": {"maxConcurrentRuns": 4}},
                    "agentRuntimeConfig": {
                        "command": sys.executable,
                        "args": ["-c", "print('ok')"],
                    },
                },
                actor_type="board",
                actor_id="local-board",
            )
            await session.commit()
            run_ids = []
            async with async_transaction(session):
                for _ in range(4):
                    queued = HeartbeatRun(
                        org_id=org.id,
                        agent_id=agent["id"],
                        invocation_source="on_demand",
                        trigger_detail="manual",
                        status="queued",
                        context_snapshot={"issueId": issue.id},
                    )
                    session.add(queued)
                    await session.flush()
                    run_ids.append(queued.id)

        await dispatch_queued_agent(factory, agent["id"])

        async with factory() as verify:
            runs = (
                await verify.execute(
                    select(HeartbeatRun).where(HeartbeatRun.id.in_(run_ids))
                )
            ).scalars()
            assert {run.status for run in runs} == {"succeeded"}
        assert max_active_prepares == 1
        assert max_active_adapters == 4
    finally:
        await engine.dispose()


async def test_workspace_prepare_retries_transient_sqlite_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    original_prepare = WorkspaceService.prepare_runtime_context_for_heartbeat
    attempts = 0

    async def transient_lock(
        self: WorkspaceService, *args: object, **kwargs: object
    ) -> dict:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("database is locked")
        return await original_prepare(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        WorkspaceService,
        "prepare_runtime_context_for_heartbeat",
        transient_lock,
    )
    try:
        async with factory() as session:
            agent = await _seed_agent(session, name="WorkspaceRetry")
            heartbeat = HeartbeatService(session)
            async with async_transaction(session):
                run = await heartbeat.wakeup(
                    agent["id"],
                    {"source": "on_demand", "triggerDetail": "manual"},
                    actor_type="board",
                    actor_id="local-board",
                    execute_immediately=False,
                )

        assert run is not None
        await dispatch_queued_agent(factory, agent["id"])

        async with factory() as verify:
            stored = await verify.get(HeartbeatRun, run["id"])
            assert stored is not None and stored.status == "succeeded"
        assert attempts == 3
    finally:
        await engine.dispose()


async def test_run_cancelled_during_workspace_prepare_never_invokes_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import heartbeat as heartbeat_module

    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    adapter_invoked = False

    async def cancel_during_prepare(
        self: WorkspacePreparationCoordinator,
        *,
        agent_id: str,
        run_id: str,
        org_id: str,
    ) -> None:
        del agent_id, org_id
        async with factory() as cancel_session:
            await HeartbeatService(cancel_session).cancel_run(run_id)
            await cancel_session.commit()

    class UnexpectedAdapter:
        type = "process"

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            nonlocal adapter_invoked
            adapter_invoked = True
            return RuntimeExecutionResult(exit_code=0)

    monkeypatch.setattr(
        WorkspacePreparationCoordinator,
        "prepare",
        cancel_during_prepare,
    )
    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda _runtime_type: UnexpectedAdapter(),
    )
    try:
        async with factory() as session:
            agent = await _seed_agent(session, name="CancelDuringWorkspacePrepare")
            heartbeat = HeartbeatService(session)
            async with async_transaction(session):
                run = await heartbeat.wakeup(
                    agent["id"],
                    {"source": "on_demand", "triggerDetail": "manual"},
                    actor_type="board",
                    actor_id="local-board",
                    execute_immediately=False,
                )

        assert run is not None
        await dispatch_queued_agent(factory, agent["id"])

        async with factory() as verify:
            stored = await verify.get(HeartbeatRun, run["id"])
            assert stored is not None and stored.status == "cancelled"
            invoked_events = (
                await verify.execute(
                    select(HeartbeatRunEvent).where(
                        HeartbeatRunEvent.run_id == run["id"],
                        HeartbeatRunEvent.event_type == "adapter.invoke",
                    )
                )
            ).scalars()
            assert list(invoked_events) == []
        assert adapter_invoked is False
    finally:
        await engine.dispose()


async def test_wake_on_demand_false_skips_non_timer_wakeup(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="DemandOff",
        runtime_config={
            "heartbeat": {
                "enabled": True,
                "intervalSec": 1,
                "runDiagnosticsOnTimer": True,
                "wakeOnDemand": False,
            }
        },
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = await heartbeat.wakeup(
            agent["id"],
            {"source": "on_demand", "triggerDetail": "manual"},
            actor_type="board",
            actor_id="local-board",
        )

    wakeup = (await session.execute(select(AgentWakeupRequest))).scalar_one()
    runs = (await session.execute(select(HeartbeatRun))).scalars().all()
    assert run is None
    assert wakeup.source == "on_demand"
    assert wakeup.status == "skipped"
    assert wakeup.error == "heartbeat.wakeOnDemand.disabled"
    assert runs == []


async def test_wake_on_demand_false_does_not_block_timer_wakeup(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerStillRuns",
        runtime_config={
            "heartbeat": {
                "enabled": True,
                "intervalSec": 1,
                "runDiagnosticsOnTimer": True,
                "preflightEnabled": False,
                "wakeOnDemand": False,
            }
        },
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        timed = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=2)
        )

    wakeup = (await session.execute(select(AgentWakeupRequest))).scalar_one()
    run = (await session.execute(select(HeartbeatRun))).scalar_one()
    assert timed[0]["id"] == run.id
    assert wakeup.source == "timer"
    assert wakeup.status == "queued"
    assert run.invocation_source == "timer"


async def test_timer_preflight_skips_when_agent_has_no_actionable_work(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerNoWork",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
    )
    heartbeat = HeartbeatService(session)
    checked_at = datetime.now(UTC) + timedelta(seconds=2)

    async with async_transaction(session):
        timed = await heartbeat.tick_timers(agent["orgId"], now=checked_at)

    assert timed == []
    assert (await session.execute(select(HeartbeatRun))).scalars().all() == []
    wakeup = (await session.execute(select(AgentWakeupRequest))).scalar_one()
    assert wakeup.source == "timer"
    assert wakeup.status == "skipped"
    assert wakeup.reason == "heartbeat.preflight.no_actionable_work"
    assert wakeup.error == "heartbeat.preflight.no_actionable_work"
    assert wakeup.payload is not None
    assert wakeup.payload["preflight"]["actionableIssueCount"] == 0
    refreshed_agent = await session.get(AgentRow, agent["id"])
    assert refreshed_agent is not None
    assert refreshed_agent.last_heartbeat_at is None
    recorded_at = refreshed_agent.last_heartbeat_check_at
    assert recorded_at is not None
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=UTC)
    assert recorded_at == checked_at

    advanced = await advance_agent_heartbeat_check(
        session, agent["id"], checked_at - timedelta(seconds=1)
    )
    await session.commit()
    assert advanced is False
    await session.refresh(refreshed_agent)
    recorded_at = refreshed_agent.last_heartbeat_check_at
    assert recorded_at is not None
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=UTC)
    assert recorded_at == checked_at


async def test_timer_preflight_creates_one_run_for_actionable_issue(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerActionable",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
    )
    heartbeat = HeartbeatService(session)
    checked_at = datetime.now(UTC) + timedelta(seconds=2)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Actionable timer work",
            status="todo",
            priority="high",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        first = await heartbeat.tick_timers(agent["orgId"], now=checked_at)
        second = await heartbeat.tick_timers(agent["orgId"], now=checked_at)
        first_row = await session.get(HeartbeatRun, first[0]["id"])
        assert first_row is not None
        first_row.status = "succeeded"
        first_row.finished_at = checked_at
        before_next_interval = await heartbeat.tick_timers(
            agent["orgId"], now=checked_at + timedelta(milliseconds=500)
        )

    assert len(first) == 1
    assert second == []
    assert before_next_interval == []
    runs = (await session.execute(select(HeartbeatRun))).scalars().all()
    assert len(runs) == 1
    assert runs[0].invocation_source == "timer"
    assert runs[0].context_snapshot is not None
    preflight = runs[0].context_snapshot["heartbeatPreflight"]
    assert preflight["reason"] == "heartbeat.preflight.assignee_issue"
    assert preflight["actionableIssueIds"] == [issue.id]


async def test_timer_preflight_does_not_run_parent_while_child_is_active(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerWaitingParent",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
    )
    async with async_transaction(session):
        parent = Issue(
            org_id=agent["orgId"],
            title="Parent waiting for children",
            status="in_progress",
            assignee_agent_id=agent["id"],
        )
        session.add(parent)
        await session.flush()
        session.add(
            Issue(
                org_id=agent["orgId"],
                parent_id=parent.id,
                title="Active child",
                status="in_progress",
            )
        )

    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        triggered = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=2)
        )

    assert triggered == []
    assert (await session.execute(select(HeartbeatRun))).scalars().all() == []
    skipped = (await session.execute(select(AgentWakeupRequest))).scalar_one()
    assert skipped.reason == "heartbeat.preflight.no_actionable_work"


async def test_timer_recovers_missing_parent_continuation_after_children_settle(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerParentRecovery",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
    )
    settled_at = datetime.now(UTC)
    async with async_transaction(session):
        parent = Issue(
            org_id=agent["orgId"],
            title="Parent missing continuation",
            status="in_progress",
            assignee_agent_id=agent["id"],
        )
        session.add(parent)
        await session.flush()
        session.add_all(
            [
                Issue(
                    org_id=agent["orgId"],
                    parent_id=parent.id,
                    title="Settled child one",
                    status="done",
                    completed_at=settled_at,
                ),
                Issue(
                    org_id=agent["orgId"],
                    parent_id=parent.id,
                    title="Settled child two",
                    status="done",
                    completed_at=settled_at + timedelta(microseconds=1),
                ),
            ]
        )

    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        triggered = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=2)
        )

    assert len(triggered) == 1
    run = (await session.execute(select(HeartbeatRun))).scalar_one()
    assert run.invocation_source == "assignment"
    assert run.context_snapshot is not None
    assert run.context_snapshot["issueId"] == parent.id
    assert run.context_snapshot["wakeReason"] == "issue_children_settled"
    wakeup = (await session.execute(select(AgentWakeupRequest))).scalar_one()
    assert wakeup.reason == "issue_children_settled"


async def test_run_recovery_repairs_missing_parent_continuation_without_timer(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="RecoveryParentContinuation",
        runtime_config={"heartbeat": {"enabled": False}},
    )
    settled_at = datetime.now(UTC)
    async with async_transaction(session):
        parent = Issue(
            org_id=agent["orgId"],
            title="Parent recovered without heartbeat",
            status="in_progress",
            assignee_agent_id=agent["id"],
        )
        session.add(parent)
        await session.flush()
        session.add(
            Issue(
                org_id=agent["orgId"],
                parent_id=parent.id,
                title="Already settled child",
                status="done",
                completed_at=settled_at,
            )
        )

    async with async_transaction(session):
        await HeartbeatService(session).recover_orphaned_runs()

    run = (await session.execute(select(HeartbeatRun))).scalar_one()
    assert run.status == "queued"
    assert run.context_snapshot is not None
    assert run.context_snapshot["issueId"] == parent.id
    assert run.context_snapshot["wakeReason"] == "issue_children_settled"

@pytest.mark.parametrize("pending_status", ["queued", "deferred_issue_execution"])
async def test_timer_materializes_runless_parent_continuation(
    session: AsyncSession,
    pending_status: str,
) -> None:
    agent = await _seed_agent(
        session,
        name=f"RunlessParent{pending_status}",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
    )
    checked_at = datetime.now(UTC) + timedelta(seconds=2)
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        parent = Issue(
            org_id=agent["orgId"],
            title="Parent with runless continuation",
            status="in_progress",
            assignee_agent_id=agent["id"],
        )
        session.add(parent)
        await session.flush()
        child = Issue(
            org_id=agent["orgId"],
            parent_id=parent.id,
            title="Settled child",
            status="done",
            completed_at=checked_at - timedelta(seconds=1),
        )
        session.add(child)
        await session.flush()
        cycle = await heartbeat._parent_settlement_cycle_key(parent.id)
        assert cycle is not None
        pending = AgentWakeupRequest(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            source="assignment",
            trigger_detail="system",
            reason="issue_children_settled",
            idempotency_key=f"issue:{parent.id}:children_settled:{cycle}",
            payload={"issueId": parent.id, "mutation": "children_settled"},
            status=pending_status,
            requested_at=checked_at - timedelta(seconds=1),
        )
        session.add(pending)
        await session.flush()

        triggered = await heartbeat.tick_timers(agent["orgId"], now=checked_at)

    assert len(triggered) == 1
    run = (await session.execute(select(HeartbeatRun))).scalar_one()
    assert run.wakeup_request_id == pending.id
    assert run.context_snapshot is not None
    assert run.context_snapshot["issueId"] == parent.id
    assert run.context_snapshot["recoveredPendingWakeup"] is True
    await session.refresh(pending)
    assert pending.status == "queued"
    assert pending.run_id == run.id


async def test_timer_recovery_ignores_hidden_active_legacy_child(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerHiddenChildRecovery",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
    )
    settled_at = datetime.now(UTC)
    async with async_transaction(session):
        parent = Issue(
            org_id=agent["orgId"],
            title="Parent with superseded child",
            status="in_progress",
            assignee_agent_id=agent["id"],
        )
        session.add(parent)
        await session.flush()
        session.add_all(
            [
                Issue(
                    org_id=agent["orgId"],
                    parent_id=parent.id,
                    title="Superseded active child",
                    status="in_progress",
                    hidden_at=settled_at,
                ),
                Issue(
                    org_id=agent["orgId"],
                    parent_id=parent.id,
                    title="Visible settled child",
                    status="done",
                    completed_at=settled_at,
                ),
            ]
        )

    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        triggered = await heartbeat.tick_timers(
            agent["orgId"], now=settled_at + timedelta(seconds=2)
        )

    assert len(triggered) == 1
    run = (await session.execute(select(HeartbeatRun))).scalar_one()
    assert run.context_snapshot is not None
    assert run.context_snapshot["issueId"] == parent.id
    assert run.context_snapshot["wakeReason"] == "issue_children_settled"
    assert await heartbeat._issue_has_active_children(parent.id) is False
    assert [child.title for child in await heartbeat._direct_children(parent)] == [
        "Visible settled child"
    ]


async def test_timer_preflight_treats_review_assignment_as_actionable(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerReview",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
    )
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Review timer work",
            status="in_review",
            priority="medium",
            reviewer_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        timed = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=2)
        )

    assert len(timed) == 1
    run = (await session.execute(select(HeartbeatRun))).scalar_one()
    assert run.context_snapshot is not None
    preflight = run.context_snapshot["heartbeatPreflight"]
    assert preflight["reason"] == "heartbeat.preflight.reviewer_issue"
    assert preflight["actionableIssueIds"] == [issue.id]


async def test_timer_preflight_skips_completed_blocked_review_decision(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerBlockedReview",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
    )
    heartbeat = HeartbeatService(session)
    decision_at = datetime.now(UTC)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Already reviewed as blocked",
            status="blocked",
            priority="medium",
            reviewer_agent_id=agent["id"],
            updated_at=decision_at,
        )
        session.add(issue)
        await session.flush()
        session.add(
            ActivityLog(
                org_id=agent["orgId"],
                actor_type="agent",
                actor_id=agent["id"],
                action="issue.review_decision_recorded",
                entity_type="issue",
                entity_id=issue.id,
                agent_id=agent["id"],
                created_at=decision_at + timedelta(microseconds=1),
            )
        )
        await session.flush()
        timed = await heartbeat.tick_timers(
            agent["orgId"], now=decision_at + timedelta(seconds=2)
        )

    assert timed == []
    assert (await session.execute(select(HeartbeatRun))).scalars().all() == []
    skipped = (await session.execute(select(AgentWakeupRequest))).scalar_one()
    assert skipped.reason == "heartbeat.preflight.no_actionable_work"


@pytest.mark.parametrize("pending_status", ["queued", "deferred_issue_execution"])
async def test_timer_preflight_recovers_pending_runless_wakeup(
    session: AsyncSession, pending_status: str
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerPendingWakeup",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
    )
    heartbeat = HeartbeatService(session)
    checked_at = datetime.now(UTC) + timedelta(seconds=2)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Pending wakeup work",
            status="todo",
            priority="medium",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        session.add(
            AgentWakeupRequest(
                org_id=agent["orgId"],
                agent_id=agent["id"],
                source="assignment",
                trigger_detail="system",
                reason="issue_assigned",
                payload={"issueId": issue.id},
                status=pending_status,
                requested_at=checked_at - timedelta(seconds=1),
            )
        )
        await session.flush()
        timed = await heartbeat.tick_timers(agent["orgId"], now=checked_at)

    assert len(timed) == 1
    run = (await session.execute(select(HeartbeatRun))).scalar_one()
    assert run.invocation_source == "assignment"
    assert run.context_snapshot is not None
    assert run.context_snapshot["recoveredPendingWakeup"] is True
    wakeup = (await session.execute(select(AgentWakeupRequest))).scalar_one()
    assert wakeup.status == "queued"
    assert wakeup.run_id == run.id


async def test_timer_preflight_skips_stale_assignment_wakeup(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerStaleAssignment",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
    )
    heartbeat = HeartbeatService(session)
    checked_at = datetime.now(UTC) + timedelta(seconds=2)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="No longer assigned",
            status="todo",
            priority="medium",
            assignee_agent_id=None,
        )
        session.add(issue)
        await session.flush()
        stale = AgentWakeupRequest(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            source="assignment",
            trigger_detail="system",
            reason="issue_assigned",
            payload={"issueId": issue.id},
            status="queued",
            requested_at=checked_at - timedelta(seconds=1),
        )
        session.add(stale)
        await session.flush()
        timed = await heartbeat.tick_timers(agent["orgId"], now=checked_at)

    assert timed == []
    assert (await session.execute(select(HeartbeatRun))).scalars().all() == []
    await session.refresh(stale)
    assert stale.status == "skipped"
    assert stale.error is not None and "stale" in stale.error


async def test_timer_preflight_can_be_explicitly_disabled_for_diagnostics(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerDiagnostics",
        runtime_config={
            "heartbeat": {
                "enabled": True,
                "intervalSec": 1,
                "preflightEnabled": False,
            }
        },
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        timed = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=2)
        )

    assert len(timed) == 1
    run = (await session.execute(select(HeartbeatRun))).scalar_one()
    assert run.context_snapshot is not None
    assert run.context_snapshot["heartbeatPreflight"] == {
        "enabled": False,
        "shouldRun": True,
        "reason": "heartbeat.preflight.disabled",
    }


async def test_timer_preflight_new_field_wins_over_legacy_diagnostics_flag(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerExplicitPreflight",
        runtime_config={
            "heartbeat": {
                "enabled": True,
                "intervalSec": 1,
                "preflightEnabled": True,
                "runDiagnosticsOnTimer": True,
            }
        },
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        timed = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=2)
        )

    assert timed == []
    assert (await session.execute(select(HeartbeatRun))).scalars().all() == []


async def test_timer_preflight_supports_legacy_only_diagnostics_config(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="TimerLegacyDiagnostics")
    async with async_transaction(session):
        row = await session.get(AgentRow, agent["id"])
        assert row is not None
        row.runtime_config = {
            "heartbeat": {
                "enabled": True,
                "intervalSec": 1,
                "runDiagnosticsOnTimer": True,
            }
        }

    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        timed = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=2)
        )

    assert len(timed) == 1
    run = (await session.execute(select(HeartbeatRun))).scalar_one()
    assert run.context_snapshot is not None
    assert run.context_snapshot["heartbeatPreflight"]["enabled"] is False


async def test_timer_wakeup_does_not_stack_when_timer_run_is_active(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerCoalesces",
        runtime_config={
            "heartbeat": {
                "enabled": True,
                "intervalSec": 1,
                "runDiagnosticsOnTimer": True,
                "preflightEnabled": False,
            }
        },
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        first_tick = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=2)
        )
        second_tick = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=4)
        )

    assert len(first_tick) == 1
    assert second_tick == []

    async with async_transaction(session):
        run = await session.get(HeartbeatRun, first_tick[0]["id"])
        assert run is not None
        assert run.invocation_source == "timer"
        assert run.status == "queued"
        run.status = "running"
        running_tick = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=6)
        )

    runs = (await session.execute(select(HeartbeatRun))).scalars().all()
    assert running_tick == []
    assert len(runs) == 1


async def test_paused_wakeup_coalesces_and_replays_on_resume(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="Paused")
    agents = AgentService(session)
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        await agents.pause_agent(
            agent["id"], actor_type="board", actor_id="local-board"
        )
        assert (
            await heartbeat.wakeup(
                agent["id"],
                {"idempotencyKey": "paused-1"},
                actor_type="board",
                actor_id="local-board",
            )
            is None
        )
        assert (
            await heartbeat.wakeup(
                agent["id"],
                {"idempotencyKey": "paused-1"},
                actor_type="board",
                actor_id="local-board",
            )
            is None
        )
        await agents.resume_agent(
            agent["id"], actor_type="board", actor_id="local-board"
        )
        resumed = await heartbeat.resume_deferred_wakeups(agent["id"])

    wakeup = (await session.execute(select(AgentWakeupRequest))).scalar_one()
    assert wakeup.coalesced_count == 1
    assert resumed[0]["status"] == "succeeded"


async def test_resumed_paused_wakeup_preserves_issue_link(
    session: AsyncSession,
) -> None:
    """A wakeup deferred while the agent is paused must keep its issue context
    when resumed, so the resulting run stays reverse-lookupable by issue.

    Regression: the resume path hard-coded ``context_snapshot`` to
    ``{"resumedFromPaused": True}`` and dropped the ``issueId``, so resumed runs
    showed in the org run list but never under the issue.
    """

    agent = await _seed_agent(session, name="ResumedIssue")
    org_id = agent["orgId"]
    issue_id = str(uuid.uuid4())
    agents = AgentService(session)
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Tracked work",
                status="todo",
                priority="high",
                identifier="RUN-1",
            )
        )
        await session.flush()
        await agents.pause_agent(
            agent["id"], actor_type="board", actor_id="local-board"
        )
        assert (
            await heartbeat.wakeup(
                agent["id"],
                {"idempotencyKey": "issue-1", "payload": {"issueId": issue_id}},
                actor_type="board",
                actor_id="local-board",
            )
            is None
        )
        await agents.resume_agent(
            agent["id"], actor_type="board", actor_id="local-board"
        )
        resumed = await heartbeat.resume_deferred_wakeups(
            agent["id"], execute_immediately=False
        )

    assert len(resumed) == 1
    run = (await session.execute(select(HeartbeatRun))).scalar_one()
    assert run.context_snapshot is not None
    assert run.context_snapshot.get("issueId") == issue_id

    runs_for_issue = await heartbeat.list_for_issue(issue_id)
    assert runs_for_issue is not None
    assert any(item["runId"] == run.id for item in runs_for_issue)


async def test_cancel_retry_and_timer_preserve_recovery_context(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="Recover",
        runtime_config={
            "heartbeat": {
                "enabled": True,
                "intervalSec": 1,
                "runDiagnosticsOnTimer": True,
                "preflightEnabled": False,
            }
        },
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        queued = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="queued",
        )
        session.add(queued)
        await session.flush()
        cancelled = await heartbeat.cancel_run(queued.id)
        assert cancelled is not None
        retried = await heartbeat.retry_run(
            queued.id, actor_type="board", actor_id="local-board"
        )
        timed = await heartbeat.tick_timers(
            agent["orgId"], now=datetime.now(UTC) + timedelta(seconds=2)
        )

    assert cancelled is not None and cancelled["status"] == "cancelled"
    assert retried is not None and retried["retryOfRunId"] == queued.id
    assert retried["contextSnapshot"] is not None
    assert retried["contextSnapshot"]["recovery"]["recoveryTrigger"] == "manual"
    assert timed[0]["invocationSource"] == "timer"


async def test_cancel_assignment_run_releases_issue_execution_lock(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="CancelLock")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Locked issue",
            status="in_progress",
            priority="medium",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="queued",
            context_snapshot={
                "issueId": issue.id,
                "wakeSource": "assignment",
                "wakeReason": "issue_execute",
            },
        )
        session.add(run)
        await session.flush()
        issue.checkout_run_id = run.id
        issue.execution_run_id = run.id
        issue.execution_locked_at = datetime.now(UTC)

        cancelled = await heartbeat.cancel_run(run.id)

    assert cancelled is not None and cancelled["status"] == "cancelled"
    persisted_issue = await session.get(Issue, issue.id)
    assert persisted_issue is not None
    assert persisted_issue.checkout_run_id is None
    assert persisted_issue.execution_run_id is None
    assert persisted_issue.execution_locked_at is None


async def test_closed_issue_deferred_wakeup_is_skipped_instead_of_promoted(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ClosedDeferred")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Close while comment wake is deferred",
            status="in_progress",
            priority="medium",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        active_run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            context_snapshot={
                "issueId": issue.id,
                "wakeSource": "assignment",
                "wakeReason": "issue_assigned",
            },
        )
        session.add(active_run)
        await session.flush()
        issue.checkout_run_id = active_run.id
        issue.execution_run_id = active_run.id
        issue.execution_locked_at = datetime.now(UTC)

        deferred = await heartbeat.wakeup(
            agent["id"],
            {
                "source": "assignment",
                "triggerDetail": "system",
                "reason": "issue_comment_added",
                "payload": {"issueId": issue.id, "commentId": "comment-1"},
                "contextSnapshot": {
                    "issueId": issue.id,
                    "commentId": "comment-1",
                    "wakeSource": "assignment",
                    "wakeReason": "issue_comment_added",
                },
            },
            actor_type="board",
            actor_id="local-board",
            execute_immediately=False,
        )
        assert deferred is None
        issue.status = "done"
        active_run.status = "succeeded"
        active_run.finished_at = datetime.now(UTC)

        await heartbeat._release_issue_execution(active_run)

    persisted_wakeups = (
        (
            await session.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == agent["id"]
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(persisted_wakeups) == 1
    assert persisted_wakeups[0].status == "skipped"
    assert persisted_wakeups[0].run_id is None
    runs = (
        (
            await session.execute(
                select(HeartbeatRun).where(HeartbeatRun.agent_id == agent["id"])
            )
        )
        .scalars()
        .all()
    )
    assert [run.id for run in runs] == [active_run.id]


async def test_terminal_effects_resolve_legacy_issue_identifier_and_wake_parent(
    session: AsyncSession,
) -> None:
    parent_agent = await _seed_agent(session, name="IdentifierParent")
    child_agent_id = str(uuid.uuid4())
    settled_at = datetime.now(UTC)
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        session.add(
            AgentRow(
                id=child_agent_id,
                org_id=parent_agent["orgId"],
                name="Identifier Child",
                role="engineer",
                status="running",
            )
        )
        parent = Issue(
            org_id=parent_agent["orgId"],
            identifier="PAR-LEGACY",
            title="Parent",
            status="in_progress",
            assignee_agent_id=parent_agent["id"],
        )
        session.add(parent)
        await session.flush()
        child = Issue(
            org_id=parent_agent["orgId"],
            identifier="CHD-LEGACY",
            parent_id=parent.id,
            title="Child",
            status="done",
            completed_at=settled_at,
            assignee_agent_id=child_agent_id,
        )
        session.add(child)
        await session.flush()
        final = HeartbeatRun(
            org_id=parent_agent["orgId"],
            agent_id=child_agent_id,
            invocation_source="assignment",
            trigger_detail="system",
            status="succeeded",
            finished_at=settled_at,
            context_snapshot={
                "issueId": child.identifier,
                "wakeSource": "assignment",
                "wakeReason": "issue_assigned",
            },
        )
        session.add(final)
        await session.flush()
        child.checkout_run_id = final.id
        child.execution_run_id = final.id
        child.execution_locked_at = settled_at

        await heartbeat._release_issue_execution(final)

    await session.refresh(child)
    assert child.checkout_run_id is None
    assert child.execution_run_id is None
    parent_wakeup = (
        await session.execute(
            select(AgentWakeupRequest).where(
                AgentWakeupRequest.agent_id == parent_agent["id"],
                AgentWakeupRequest.reason == "issue_children_settled",
            )
        )
    ).scalar_one()
    assert parent_wakeup.payload is not None
    assert parent_wakeup.payload["issueId"] == parent.id


async def test_failed_parent_run_with_active_child_does_not_block_parent(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ParentFailureWithActiveChild")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        parent = Issue(
            org_id=agent["orgId"],
            title="Parent",
            status="in_progress",
            assignee_agent_id=agent["id"],
        )
        session.add(parent)
        await session.flush()
        child = Issue(
            org_id=agent["orgId"],
            parent_id=parent.id,
            title="Child",
            status="in_progress",
            assignee_agent_id=agent["id"],
        )
        session.add(child)
        failed = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="failed",
            error="process disappeared",
            error_code="process_lost",
            context_snapshot={"issueId": parent.id},
        )
        session.add(failed)
        await session.flush()
        parent.execution_run_id = failed.id

        await heartbeat._release_issue_execution(failed)

    await session.refresh(parent)
    assert parent.status == "in_progress"
    assert parent.execution_run_id is None
    blocked_events = (
        (
            await session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == parent.id,
                    ActivityLog.action == "issue.updated",
                )
            )
        )
        .scalars()
        .all()
    )
    assert not any(
        isinstance(event.details, dict) and event.details.get("status") == "blocked"
        for event in blocked_events
    )


async def test_successful_recovery_restores_only_matching_system_block(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="SystemBlockRecovery")
    heartbeat = HeartbeatService(session)
    blocked_at = datetime.now(UTC) - timedelta(minutes=1)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Recover parent",
            status="blocked",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        original = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="failed",
            error_code="process_lost",
            context_snapshot={"issueId": issue.id},
        )
        session.add(original)
        await session.flush()
        session.add(
            ActivityLog(
                org_id=issue.org_id,
                actor_type="agent",
                actor_id=agent["id"],
                action="issue.updated",
                entity_type="issue",
                entity_id=issue.id,
                run_id=original.id,
                details={
                    "status": "blocked",
                    "fromStatus": "in_progress",
                    "reason": "run_failed",
                    "runId": original.id,
                },
                created_at=blocked_at,
            )
        )
        recovery = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="automation",
            trigger_detail="system",
            status="succeeded",
            retry_of_run_id=original.id,
            context_snapshot={
                "issueId": issue.id,
                "recovery": {"originalRunId": original.id},
            },
        )
        session.add(recovery)
        await session.flush()

        await heartbeat._restore_system_blocked_issue_after_recovery(recovery)

    await session.refresh(issue)
    assert issue.status == "in_progress"


async def test_recovery_claim_restores_system_block_before_adapter_execution(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ClaimSystemBlockRecovery")
    heartbeat = HeartbeatService(session)
    blocked_at = datetime.now(UTC) - timedelta(minutes=1)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Restore when retry starts",
            status="blocked",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        original = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="failed",
            error_code="process_lost",
            context_snapshot={"issueId": issue.id},
        )
        session.add(original)
        await session.flush()
        session.add(
            ActivityLog(
                org_id=issue.org_id,
                actor_type="agent",
                actor_id=agent["id"],
                action="issue.updated",
                entity_type="issue",
                entity_id=issue.id,
                run_id=original.id,
                details={
                    "status": "blocked",
                    "fromStatus": "in_progress",
                    "reason": "run_failed",
                    "runId": original.id,
                },
                created_at=blocked_at,
            )
        )
        retry = await heartbeat.retry_run(
            original.id,
            actor_type="system",
            actor_id="run_recovery",
            execute_immediately=False,
            recovery_trigger="automatic",
        )

    assert retry is not None and retry["status"] == "queued"
    async with async_transaction(session):
        claimed_ids = await heartbeat.claim_queued_for_dispatch(agent["id"])

    await session.refresh(issue)
    claimed = await session.get(HeartbeatRun, retry["id"])
    assert claimed_ids == [retry["id"]]
    assert claimed is not None and claimed.status == "running"
    assert issue.status == "in_progress"
    restored = (
        (
            await session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == issue.id,
                    ActivityLog.run_id == retry["id"],
                    ActivityLog.action == "issue.updated",
                )
            )
        )
        .scalars()
        .one()
    )
    assert isinstance(restored.details, dict)
    assert restored.details["reason"] == "process_loss_retry_started"


async def test_comment_assignment_claim_restores_adapter_failure_block(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="CommentAssignmentRecovery")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Resume from comment",
            status="blocked",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        failed = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="failed",
            error_code="adapter_failed",
            context_snapshot={"issueId": issue.id},
        )
        session.add(failed)
        await session.flush()
        session.add(
            ActivityLog(
                org_id=issue.org_id,
                actor_type="agent",
                actor_id=agent["id"],
                action="issue.updated",
                entity_type="issue",
                entity_id=issue.id,
                run_id=failed.id,
                details={
                    "status": "blocked",
                    "fromStatus": "in_progress",
                    "reason": "run_failed",
                    "runId": failed.id,
                },
            )
        )
        resumed = await heartbeat.wakeup(
            agent["id"],
            {
                "source": "assignment",
                "triggerDetail": "system",
                "reason": "issue_comment_added",
                "contextSnapshot": {
                    "issueId": issue.id,
                    "wakeReason": "issue_comment_added",
                },
            },
            actor_type="user",
            actor_id="local-board",
            execute_immediately=False,
        )

    assert resumed is not None and resumed["status"] == "queued"
    async with async_transaction(session):
        claimed_ids = await heartbeat.claim_queued_for_dispatch(agent["id"])

    await session.refresh(issue)
    assert claimed_ids == [resumed["id"]]
    assert issue.status == "in_progress"
    restored = (
        (
            await session.execute(
                select(ActivityLog).where(
                    ActivityLog.entity_id == issue.id,
                    ActivityLog.run_id == resumed["id"],
                    ActivityLog.action == "issue.updated",
                )
            )
        )
        .scalars()
        .one()
    )
    assert isinstance(restored.details, dict)
    assert restored.details["reason"] == "system_failure_retry_started"
    assert restored.details["originalErrorCode"] == "adapter_failed"


async def test_assignment_claim_preserves_newer_review_block(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ReviewBlockExecution")
    heartbeat = HeartbeatService(session)
    blocked_at = datetime.now(UTC) - timedelta(minutes=1)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Keep review block",
            status="blocked",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        failed = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="failed",
            error_code="adapter_failed",
            context_snapshot={"issueId": issue.id},
        )
        session.add(failed)
        await session.flush()
        session.add_all(
            [
                ActivityLog(
                    org_id=issue.org_id,
                    actor_type="agent",
                    actor_id=agent["id"],
                    action="issue.updated",
                    entity_type="issue",
                    entity_id=issue.id,
                    run_id=failed.id,
                    details={
                        "status": "blocked",
                        "fromStatus": "in_progress",
                        "reason": "run_failed",
                        "runId": failed.id,
                    },
                    created_at=blocked_at,
                ),
                ActivityLog(
                    org_id=issue.org_id,
                    actor_type="agent",
                    actor_id="reviewer-agent",
                    action="issue.review_decision_recorded",
                    entity_type="issue",
                    entity_id=issue.id,
                    details={"decision": "blocked", "comment": "Needs review"},
                    created_at=blocked_at + timedelta(seconds=1),
                ),
            ]
        )
        running = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            context_snapshot={"issueId": issue.id},
        )
        session.add(running)
        await session.flush()

        restored = await heartbeat._restore_system_blocked_issue_for_execution(running)

    await session.refresh(issue)
    assert restored is False
    assert issue.status == "blocked"


async def test_recovery_claim_preserves_newer_manual_block(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ManualBlockRecovery")
    heartbeat = HeartbeatService(session)
    blocked_at = datetime.now(UTC) - timedelta(minutes=2)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Keep manual block",
            status="blocked",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        original = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="failed",
            error_code="process_lost",
            context_snapshot={"issueId": issue.id},
        )
        session.add(original)
        await session.flush()
        session.add_all(
            [
                ActivityLog(
                    org_id=issue.org_id,
                    actor_type="agent",
                    actor_id=agent["id"],
                    action="issue.updated",
                    entity_type="issue",
                    entity_id=issue.id,
                    run_id=original.id,
                    details={
                        "status": "blocked",
                        "fromStatus": "in_progress",
                        "reason": "run_failed",
                        "runId": original.id,
                    },
                    created_at=blocked_at,
                ),
                ActivityLog(
                    org_id=issue.org_id,
                    actor_type="user",
                    actor_id="local-board",
                    action="issue.updated",
                    entity_type="issue",
                    entity_id=issue.id,
                    details={
                        "status": "blocked",
                        "fromStatus": "in_progress",
                        "reason": "manual",
                    },
                    created_at=blocked_at + timedelta(minutes=1),
                ),
            ]
        )
        retry = await heartbeat.retry_run(
            original.id,
            actor_type="system",
            actor_id="run_recovery",
            execute_immediately=False,
            recovery_trigger="automatic",
        )

    assert retry is not None and retry["status"] == "queued"
    async with async_transaction(session):
        claimed_ids = await heartbeat.claim_queued_for_dispatch(agent["id"])

    await session.refresh(issue)
    assert claimed_ids == [retry["id"]]
    assert issue.status == "blocked"


async def test_recover_orphaned_run_does_not_abort_when_retry_is_unavailable(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="PausedRecover")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        agent_row = await session.get(AgentRow, agent["id"])
        assert agent_row is not None
        agent_row.status = "paused"
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            process_pid=987654,
            process_loss_retry_count=0,
            context_snapshot={"wakeSource": "assignment"},
        )
        session.add(run)
        await session.flush()

        recovered = await heartbeat.recover_orphaned_runs()

    assert recovered == []
    persisted_run = await session.get(HeartbeatRun, run.id)
    assert persisted_run is not None
    assert persisted_run.status == "failed"
    assert persisted_run.error_code == "process_lost"


async def test_manual_retry_preserves_review_invocation_source(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ReviewRetry")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        failed_review = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="review",
            run_purpose="review",
            trigger_detail="system",
            status="failed",
            error="review tool failed",
            context_snapshot={
                "issueId": str(uuid.uuid4()),
                "wakeSource": "review",
                "wakeReason": "issue_review_requested",
                "role": "reviewer",
            },
        )
        session.add(failed_review)
        await session.flush()
        retried = await heartbeat.retry_run(
            failed_review.id,
            actor_type="board",
            actor_id="local-board",
            execute_immediately=False,
        )

    assert retried is not None
    assert retried["invocationSource"] == "review"
    assert retried["runPurpose"] == "review"
    assert retried["retryOfRunId"] == failed_review.id
    assert retried["contextSnapshot"] is not None
    assert retried["contextSnapshot"]["wakeReason"] == "issue_review_requested"


async def test_manual_retry_preserves_passive_followup_invocation_source(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="FollowupRetry")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        failed_followup = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="automation",
            run_purpose="closeout",
            trigger_detail="system",
            status="failed",
            error="closeout tool failed",
            context_snapshot={
                "issueId": str(uuid.uuid4()),
                "wakeSource": "automation",
                "wakeReason": "issue_passive_followup",
            },
        )
        session.add(failed_followup)
        await session.flush()
        retried = await heartbeat.retry_run(
            failed_followup.id,
            actor_type="board",
            actor_id="local-board",
            execute_immediately=False,
        )

    assert retried is not None
    assert retried["invocationSource"] == "automation"
    assert retried["runPurpose"] == "closeout"
    assert retried["retryOfRunId"] == failed_followup.id
    assert retried["contextSnapshot"] is not None
    assert retried["contextSnapshot"]["wakeReason"] == "issue_passive_followup"


async def test_orphaned_running_run_enqueues_automatic_recovery(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="Orphaned")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        orphan = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="running",
        )
        session.add(orphan)
        await session.flush()
        recovery = await heartbeat.recover_orphaned_runs()

    await session.refresh(orphan)
    assert orphan.status == "failed"
    assert orphan.error_code == "process_lost"
    assert recovery[0]["status"] == "queued"
    assert recovery[0]["invocationSource"] == "automation"
    assert recovery[0]["retryOfRunId"] == orphan.id
    assert recovery[0]["processLossRetryCount"] == 1
    assert recovery[0]["contextSnapshot"] is not None
    assert recovery[0]["contextSnapshot"]["recovery"]["recoveryTrigger"] == "automatic"


async def test_periodic_recovery_skips_running_local_child_that_is_still_alive(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    monkeypatch.setattr(heartbeat_module, "_is_process_alive", lambda _pid: True)
    agent = await _seed_agent(session, name="AliveChild")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            process_pid=12345,
            process_started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()
        recovery = await heartbeat.recover_orphaned_runs(require_process_loss=True)

    assert recovery == []
    await session.refresh(run)
    assert run.status == "running"
    assert run.error_code is None


async def test_periodic_recovery_does_not_cancel_live_run_after_issue_done(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    monkeypatch.setattr(heartbeat_module, "_is_process_alive", lambda _pid: True)
    agent = await _seed_agent(
        session,
        name="LiveDoneIssueOpenCode",
        runtime_type="opencode_local",
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Live issue closed by running agent",
            status="done",
            assignee_agent_id=agent["id"],
            completed_at=datetime.now(UTC),
        )
        session.add(issue)
        await session.flush()
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            process_pid=12345,
            process_started_at=datetime.now(UTC),
            context_snapshot={"issueId": issue.id},
        )
        session.add(run)
        await session.flush()
        issue.checkout_run_id = run.id
        issue.execution_run_id = run.id
        issue.execution_locked_at = datetime.now(UTC)
        HeartbeatService._active_run_ids.setdefault(agent["id"], set()).add(run.id)
        recovery = await heartbeat.recover_orphaned_runs(require_process_loss=True)

    await session.refresh(run)
    await session.refresh(issue)
    HeartbeatService._active_run_ids.get(agent["id"], set()).discard(run.id)
    assert recovery == []
    assert run.status == "running"
    assert run.error_code is None
    assert issue.execution_run_id == run.id


async def test_periodic_recovery_recovers_stale_active_local_child_loss(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    monkeypatch.setattr(heartbeat_module, "_is_process_alive", lambda _pid: False)
    agent = await _seed_agent(
        session,
        name="StaleActiveOpenCode",
        runtime_type="opencode_local",
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            process_pid=12345,
            process_started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()
        HeartbeatService._active_run_ids.setdefault(agent["id"], set()).add(run.id)
        recovery = await heartbeat.recover_orphaned_runs(require_process_loss=True)

    await session.refresh(run)
    assert run.status == "failed"
    assert run.error_code == "process_lost"
    assert recovery[0]["status"] == "queued"
    assert recovery[0]["retryOfRunId"] == run.id
    assert run.id not in HeartbeatService._active_run_ids.get(agent["id"], set())


async def test_periodic_recovery_claims_expired_timer_after_sqlite_reload(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    monkeypatch.setattr(heartbeat_module, "_is_process_alive", lambda _pid: False)
    agent = await _seed_agent(
        session,
        name="ReloadedExpiredTimer",
        runtime_type="opencode_local",
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="timer",
            trigger_detail="system",
            status="running",
            process_pid=12345,
            process_started_at=datetime.now(UTC) - timedelta(minutes=10),
            execution_owner_token="expired-owner",
            execution_lease_expires_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        session.expunge_all()

        recovery = await heartbeat.recover_orphaned_runs(require_process_loss=True)
        second_recovery = await heartbeat.recover_orphaned_runs(
            require_process_loss=True
        )

    persisted = await session.get(HeartbeatRun, run_id)
    assert persisted is not None
    assert persisted.status == "failed"
    assert persisted.error_code == "process_lost"
    assert recovery[0]["status"] == "queued"
    assert recovery[0]["retryOfRunId"] == run_id
    assert recovery[0]["processLossRetryCount"] == 1
    assert second_recovery == []


async def test_periodic_recovery_recovers_expired_run_without_process_pid(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ExpiredWithoutPid")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Expired assignment without pid",
            status="in_progress",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            execution_owner_token="expired-owner",
            execution_lease_expires_at=datetime.now(UTC) - timedelta(minutes=1),
            context_snapshot={"issueId": issue.id, "projectId": "project-1"},
        )
        session.add(run)
        await session.flush()
        issue.execution_run_id = run.id

        recovered = await heartbeat.recover_orphaned_runs(require_process_loss=True)
        retry_row = await session.get(HeartbeatRun, recovered[0]["id"])
        assert retry_row is not None
        retry_row.status = "running"
        retry_row.execution_owner_token = "expired-retry-owner"
        retry_row.execution_lease_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.flush()
        recovered_again = await heartbeat.recover_orphaned_runs(
            require_process_loss=True
        )

    await session.refresh(run)
    await session.refresh(issue)
    assert run.status == "failed"
    assert run.error_code == "process_lost"
    assert issue.execution_run_id is None
    assert len(recovered) == 1
    assert recovered[0]["status"] == "queued"
    assert recovered[0]["retryOfRunId"] == run.id
    assert recovered[0]["processLossRetryCount"] == 1
    assert recovered[0]["contextSnapshot"] is not None
    assert recovered[0]["contextSnapshot"]["issueId"] == issue.id
    assert recovered[0]["contextSnapshot"]["projectId"] == "project-1"
    assert recovered_again == []
    await session.refresh(retry_row)
    assert retry_row.status == "failed"
    runs = (
        (
            await session.execute(
                select(HeartbeatRun).where(HeartbeatRun.agent_id == agent["id"])
            )
        )
        .scalars()
        .all()
    )
    assert len(runs) == 2


async def test_periodic_recovery_keeps_recent_run_without_lease_or_pid(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="RecentWithoutLeaseOrPid")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            started_at=datetime.now(UTC),
        )
        session.add(run)
        await session.flush()

        recovered = await heartbeat.recover_orphaned_runs(require_process_loss=True)

    await session.refresh(run)
    assert recovered == []
    assert run.status == "running"


async def test_issue_run_repair_is_dry_run_by_default_and_scoped_to_issue_tree(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ScopedIssueRunRepair")
    repair = IssueRunRepairService(session)
    expired_at = datetime.now(UTC) - timedelta(minutes=1)
    async with async_transaction(session):
        parent = Issue(
            org_id=agent["orgId"],
            title="Repair root",
            status="blocked",
            assignee_agent_id=agent["id"],
        )
        unrelated = Issue(
            org_id=agent["orgId"],
            title="Unrelated",
            status="in_progress",
            assignee_agent_id=agent["id"],
        )
        session.add_all([parent, unrelated])
        await session.flush()
        child = Issue(
            org_id=agent["orgId"],
            parent_id=parent.id,
            title="Repair child",
            status="in_progress",
            assignee_agent_id=agent["id"],
        )
        session.add(child)
        await session.flush()
        original_parent_run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="failed",
            error_code="process_lost",
            context_snapshot={"issueId": parent.id},
        )
        session.add(original_parent_run)
        await session.flush()
        session.add(
            ActivityLog(
                org_id=parent.org_id,
                actor_type="agent",
                actor_id=agent["id"],
                action="issue.updated",
                entity_type="issue",
                entity_id=parent.id,
                run_id=original_parent_run.id,
                details={
                    "status": "blocked",
                    "fromStatus": "in_progress",
                    "reason": "run_failed",
                    "runId": original_parent_run.id,
                },
                created_at=datetime.now(UTC) - timedelta(minutes=2),
            )
        )
        completed_parent_recovery = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="automation",
            trigger_detail="system",
            status="succeeded",
            retry_of_run_id=original_parent_run.id,
            context_snapshot={
                "issueId": parent.id,
                "recovery": {"originalRunId": original_parent_run.id},
            },
        )
        session.add(completed_parent_recovery)
        target_run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            execution_owner_token="target-owner",
            execution_lease_expires_at=expired_at,
            context_snapshot={"issueId": child.id},
        )
        unrelated_run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            execution_owner_token="unrelated-owner",
            execution_lease_expires_at=expired_at,
            context_snapshot={"issueId": unrelated.id},
        )
        session.add_all([target_run, unrelated_run])
        await session.flush()

        report = await repair.inspect(parent.id)
        assert report["candidateRunIds"] == [target_run.id]
        assert target_run.status == "running"
        assert unrelated_run.status == "running"

        applied = await repair.repair(parent.id)
        applied_again = await repair.repair(parent.id)

    await session.refresh(target_run)
    await session.refresh(unrelated_run)
    assert applied["candidateRunIds"] == [target_run.id]
    assert len(applied["recoveryRuns"]) == 1
    assert applied["restoredIssueIds"] == [parent.id]
    assert applied_again["candidateRunIds"] == []
    assert applied_again["recoveryRuns"] == []
    assert applied_again["restoredIssueIds"] == []
    assert target_run.status == "failed"
    assert unrelated_run.status == "running"
    await session.refresh(parent)
    assert parent.status == "in_progress"


async def test_orphaned_opencode_run_with_lost_child_enqueues_automatic_recovery(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="OrphanedOpenCode",
        runtime_type="opencode_local",
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        orphan = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="running",
            process_pid=999_999,
            process_started_at=datetime.now(UTC),
        )
        session.add(orphan)
        await session.flush()
        recovery = await heartbeat.recover_orphaned_runs()

    await session.refresh(orphan)
    assert orphan.status == "failed"
    assert orphan.error_code == "process_lost"
    assert "999999" in (orphan.error or "")
    assert recovery[0]["status"] == "queued"
    assert recovery[0]["retryOfRunId"] == orphan.id


async def test_orphaned_assignment_run_for_closed_issue_is_cancelled_without_retry(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ClosedIssueOrphan")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Already closed issue",
            status="done",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        wakeup = AgentWakeupRequest(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            source="assignment",
            trigger_detail="system",
            payload={"issueId": issue.id},
            status="claimed",
            run_id=None,
            claimed_at=datetime.now(UTC),
        )
        session.add(wakeup)
        await session.flush()
        orphan = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            wakeup_request_id=wakeup.id,
            context_snapshot={"issueId": issue.id},
        )
        session.add(orphan)
        await session.flush()
        wakeup.run_id = orphan.id
        recovery = await heartbeat.recover_orphaned_runs()

    assert recovery == []
    await session.refresh(orphan)
    await session.refresh(wakeup)
    assert orphan.status == "cancelled"
    assert orphan.error_code == "issue_already_closed"
    assert wakeup.status == "cancelled"


async def test_closed_issue_recovery_does_not_override_finalized_run(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ClosedIssueFinalized")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Already completed during finalize",
            status="done",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        wakeup = AgentWakeupRequest(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            source="assignment",
            trigger_detail="system",
            payload={"issueId": issue.id},
            status="completed",
            run_id=None,
            claimed_at=datetime.now(UTC),
        )
        session.add(wakeup)
        await session.flush()
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            wakeup_request_id=wakeup.id,
            context_snapshot={"issueId": issue.id},
        )
        session.add(run)
        await session.flush()
        wakeup.run_id = run.id
        await session.execute(
            update(HeartbeatRun)
            .where(HeartbeatRun.id == run.id)
            .values(status="succeeded", finished_at=datetime.now(UTC))
        )
        handled = await heartbeat._cancel_orphaned_run_if_issue_closed(run)

    assert handled is True
    await session.refresh(run)
    await session.refresh(wakeup)
    assert run.status == "succeeded"
    assert run.error_code is None
    assert run.error is None
    assert wakeup.status == "completed"


async def test_closed_issue_recovery_restores_trusted_success_evidence(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ClosedIssuePartialFinalized")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        issue = Issue(
            org_id=agent["orgId"],
            title="Already completed before recovery",
            status="done",
            assignee_agent_id=agent["id"],
        )
        session.add(issue)
        await session.flush()
        wakeup = AgentWakeupRequest(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            source="assignment",
            trigger_detail="system",
            payload={"issueId": issue.id},
            status="completed",
            run_id=None,
            claimed_at=datetime.now(UTC),
        )
        session.add(wakeup)
        await session.flush()
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="assignment",
            trigger_detail="system",
            status="running",
            wakeup_request_id=wakeup.id,
            context_snapshot={"issueId": issue.id},
        )
        session.add(run)
        await session.flush()
        wakeup.run_id = run.id
        await session.execute(
            update(HeartbeatRun)
            .where(HeartbeatRun.id == run.id)
            .values(
                finished_at=datetime.now(UTC),
                exit_code=0,
                result_json={"summary": "completed"},
            )
        )
        await heartbeat._append_event(
            run,
            1,
            "lifecycle",
            message="run succeeded",
            level="info",
        )
        handled = await heartbeat._cancel_orphaned_run_if_issue_closed(run)

    assert handled is True
    await session.refresh(run)
    await session.refresh(wakeup)
    assert run.status == "succeeded"
    assert run.error_code is None
    assert run.error is None
    assert run.terminal_effects_pending is False
    assert wakeup.status == "completed"


async def test_recovery_does_not_infer_success_from_result_metadata(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="MetadataIsNotTerminalEvidence")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="running",
            finished_at=datetime.now(UTC),
            exit_code=0,
            result_json={"summary": "looks complete but is not authoritative"},
        )
        session.add(run)
        await session.flush()
        recovered = await heartbeat.recover_orphaned_runs()

    await session.refresh(run)
    assert run.status == "failed"
    assert run.error_code == "process_lost"
    assert recovered and recovered[0]["retryOfRunId"] == run.id


async def test_recovery_keeps_valid_execution_lease_running(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ValidLease")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="running",
            execution_owner_token="active-owner",
            execution_lease_expires_at=datetime.now(UTC) + timedelta(minutes=1),
        )
        session.add(run)
        await session.flush()
        recovered = await heartbeat.recover_orphaned_runs()

    await session.refresh(run)
    assert recovered == []
    assert run.status == "running"
    assert run.execution_owner_token == "active-owner"


async def test_recovery_records_conflicting_terminal_evidence_without_guessing(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ConflictingEvidence")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="running",
        )
        session.add(run)
        await session.flush()
        await heartbeat._append_event(
            run, 1, "lifecycle", message="run succeeded", level="info"
        )
        await heartbeat._append_event(
            run, 2, "lifecycle", message="run failed", level="error"
        )
        recovered = await heartbeat.recover_orphaned_runs()

    await session.refresh(run)
    errors = (
        (
            await session.execute(
                select(HeartbeatRunEvent).where(
                    HeartbeatRunEvent.run_id == run.id,
                    HeartbeatRunEvent.event_type == "recovery.error",
                )
            )
        )
        .scalars()
        .all()
    )
    assert recovered == []
    assert run.status == "running"
    assert len(errors) == 1


async def test_recovery_finishes_pending_terminal_effects_idempotently(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="PendingTerminalEffects")
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        agent_row = await session.get(AgentRow, agent["id"])
        assert agent_row is not None
        agent_row.status = "running"
        wakeup = AgentWakeupRequest(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            source="on_demand",
            trigger_detail="manual",
            status="claimed",
            claimed_at=datetime.now(UTC),
        )
        session.add(wakeup)
        await session.flush()
        run = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="succeeded",
            finished_at=datetime.now(UTC),
            wakeup_request_id=wakeup.id,
            terminal_effects_pending=True,
            terminal_effects_json={"version": 1},
            terminal_effects_next_attempt_at=datetime.now(UTC) - timedelta(minutes=5),
            terminal_effects_claim_token="stale-claim",
            terminal_effects_claimed_at=datetime.now(UTC) - timedelta(minutes=10),
        )
        session.add(run)
        await session.flush()
        wakeup.run_id = run.id
        await session.flush()
        run_id = run.id
        wakeup_id = wakeup.id
        agent_id = agent_row.id
        session.expunge_all()
        await heartbeat.recover_orphaned_runs()
        await heartbeat.recover_orphaned_runs()

    run = await session.get(HeartbeatRun, run_id)
    wakeup = await session.get(AgentWakeupRequest, wakeup_id)
    agent_row = await session.get(AgentRow, agent_id)
    assert run is not None
    assert wakeup is not None
    assert agent_row is not None
    terminal_events = (
        (
            await session.execute(
                select(HeartbeatRunEvent).where(
                    HeartbeatRunEvent.run_id == run.id,
                    HeartbeatRunEvent.idempotency_key
                    == "terminal-effect:outcome:succeeded",
                )
            )
        )
        .scalars()
        .all()
    )
    assert run.status == "succeeded"
    assert run.terminal_effects_pending is False
    assert wakeup.status == "completed"
    assert agent_row.status == "idle"
    assert len(terminal_events) == 1


async def test_process_run_persists_child_process_metadata(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ProcessMeta")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = await heartbeat.wakeup(
            agent["id"],
            {"source": "on_demand", "triggerDetail": "manual"},
            actor_type="board",
            actor_id="local-board",
        )

    assert run is not None
    assert run["status"] == "succeeded"
    assert isinstance(run["processPid"], int)
    assert run["processPid"] > 0
    assert run["processStartedAt"] is not None


async def test_running_adapter_emits_progress_events_without_log_output(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    class SilentSlowAdapter:
        type = "process"

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            if context.on_process_started is not None:
                await context.on_process_started(43210, datetime.now(UTC))
            await asyncio.sleep(0.05)
            return RuntimeExecutionResult(
                exit_code=0,
                result_json={"summary": "silent complete"},
            )

    agent = await _seed_agent(session, name="SilentProgress")
    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda _runtime_type: SilentSlowAdapter(),
    )
    monkeypatch.setattr(heartbeat_module, "_is_process_alive", lambda _pid: True)
    monkeypatch.setattr(HeartbeatService, "RUNTIME_PROGRESS_INTERVAL_SECONDS", 0.01)
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = await heartbeat.wakeup(
            agent["id"],
            {"source": "on_demand", "triggerDetail": "manual"},
            actor_type="board",
            actor_id="local-board",
        )

    assert run is not None
    assert run["status"] == "succeeded"
    progress_events = (
        (
            await session.execute(
                select(HeartbeatRunEvent)
                .where(
                    HeartbeatRunEvent.run_id == run["id"],
                    HeartbeatRunEvent.event_type == "runtime.progress",
                )
                .order_by(HeartbeatRunEvent.seq)
            )
        )
        .scalars()
        .all()
    )
    assert progress_events
    assert progress_events[-1].message == "runtime still running"
    payload = progress_events[-1].payload
    assert isinstance(payload, dict)
    assert payload["processPid"] == 43210
@pytest.mark.asyncio
async def test_silent_runtime_is_timed_out_instead_of_running_forever(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    class SilentAdapter:
        type = "process"

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            await asyncio.sleep(0.08)
            return RuntimeExecutionResult(exit_code=0)

    agent = await _seed_agent(
        session, name="SilentTimeout", runtime_type="opencode_local"
    )
    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda _runtime_type: SilentAdapter(),
    )
    monkeypatch.setattr(HeartbeatService, "RUNTIME_PROGRESS_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(HeartbeatService, "RUNTIME_NO_OUTPUT_TIMEOUT_SECONDS", 0.02)
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = await heartbeat.wakeup(
            agent["id"],
            {"source": "on_demand", "triggerDetail": "manual"},
            actor_type="board",
            actor_id="local-board",
        )

    assert run is not None
    assert run["status"] == "timed_out"
    assert run["errorCode"] == "timeout"
    assert run["error"] == "Runtime produced no output for 0.02s"


async def test_buffered_runtime_does_not_get_default_silence_timeout(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    class BufferedAdapter:
        type = "process"

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            await asyncio.sleep(0.04)
            return RuntimeExecutionResult(exit_code=0)

    agent = await _seed_agent(session, name="BufferedNoDefaultTimeout")
    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda _runtime_type: BufferedAdapter(),
    )
    monkeypatch.setattr(HeartbeatService, "RUNTIME_PROGRESS_INTERVAL_SECONDS", 0.005)
    monkeypatch.setattr(HeartbeatService, "RUNTIME_NO_OUTPUT_TIMEOUT_SECONDS", 0.01)

    async with async_transaction(session):
        run = await HeartbeatService(session).wakeup(
            agent["id"],
            {"source": "on_demand", "triggerDetail": "manual"},
            actor_type="board",
            actor_id="local-board",
        )

    assert run is not None
    assert run["status"] == "succeeded"


async def test_terminal_run_keeps_agent_running_while_another_run_is_active(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="ConcurrentAgentState")
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        agent_row = await session.get(AgentRow, agent["id"])
        assert agent_row is not None
        agent_row.status = "running"
        first = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="running",
        )
        second = HeartbeatRun(
            org_id=agent["orgId"],
            agent_id=agent["id"],
            invocation_source="on_demand",
            trigger_detail="manual",
            status="running",
        )
        session.add_all([first, second])
        await session.flush()
        cancelled_first = await heartbeat.cancel_run(first.id)

    assert cancelled_first is not None
    agent_row = await session.get(AgentRow, agent["id"])
    assert agent_row is not None and agent_row.status == "running"

    async with async_transaction(session):
        cancelled_second = await heartbeat.cancel_run(second.id)

    assert cancelled_second is not None
    await session.refresh(agent_row)
    assert agent_row.status == "idle"


async def test_successful_run_stays_succeeded_when_postprocess_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    class SuccessfulAdapter:
        type = "process"

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            return RuntimeExecutionResult(
                exit_code=0,
                result_json={"summary": "work completed"},
            )

    async def fail_release(self: HeartbeatService, final: HeartbeatRun) -> None:
        raise AssertionError

    agent = await _seed_agent(session, name="PostprocessCleanup")
    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda _runtime_type: SuccessfulAdapter(),
    )
    monkeypatch.setattr(
        HeartbeatService,
        "_release_issue_execution",
        fail_release,
    )
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = await heartbeat.wakeup(
            agent["id"],
            {"source": "on_demand", "triggerDetail": "manual"},
            actor_type="board",
            actor_id="local-board",
        )

    assert run is not None
    assert run["status"] == "succeeded"
    assert run["errorCode"] is None
    warning_events = (
        (
            await session.execute(
                select(HeartbeatRunEvent).where(
                    HeartbeatRunEvent.run_id == run["id"],
                    HeartbeatRunEvent.event_type == "postprocess.warning",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(warning_events) == 1
    assert warning_events[0].message == "AssertionError"


async def test_adapter_result_remains_authoritative_after_local_process_exits(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    class CompletedChildAdapter:
        type = "process"

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            if context.on_process_started is not None:
                await context.on_process_started(999_999, datetime.now(UTC))
            if context.on_process_exited is not None:
                await context.on_process_exited(999_999, 0, datetime.now(UTC))
            # The adapter still needs time to drain and parse the process output.
            await asyncio.sleep(0.05)
            return RuntimeExecutionResult(
                exit_code=0,
                result_json={"summary": "completed after output collection"},
            )

    agent = await _seed_agent(session, name="CompletedChild")
    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda _runtime_type: CompletedChildAdapter(),
    )
    monkeypatch.setattr(
        heartbeat_module,
        "_is_process_alive",
        lambda _pid: False,
        raising=False,
    )
    monkeypatch.setattr(HeartbeatService, "RUNTIME_PROGRESS_INTERVAL_SECONDS", 0.01)
    heartbeat = HeartbeatService(session)

    async with async_transaction(session):
        run = await heartbeat.wakeup(
            agent["id"],
            {"source": "on_demand", "triggerDetail": "manual"},
            actor_type="board",
            actor_id="local-board",
        )

    assert run is not None
    assert run["status"] == "succeeded"
    assert run["errorCode"] is None
    assert run["processExitedAt"] is not None


async def test_orphaned_running_run_does_not_terminate_tracked_child_process(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(session, name="OrphanedChild")
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        "import time; time.sleep(30)",
    )
    try:
        heartbeat = HeartbeatService(session)
        async with async_transaction(session):
            orphan = HeartbeatRun(
                org_id=agent["orgId"],
                agent_id=agent["id"],
                invocation_source="on_demand",
                trigger_detail="manual",
                status="running",
                process_pid=child.pid,
                process_started_at=datetime.now(UTC),
            )
            session.add(orphan)
            await session.flush()
            recovery = await heartbeat.recover_orphaned_runs()

        assert recovery and recovery[0]["retryOfRunId"] == orphan.id
        assert child.returncode is None
    finally:
        if child.returncode is None:
            child.kill()
            await child.wait()
