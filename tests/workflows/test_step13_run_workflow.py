from __future__ import annotations

import sys
import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from packages.database.clients import (
    async_transaction,
    create_database_engine,
    create_session_factory,
)
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
from server.services.agents import AgentService
from server.services.heartbeat import HeartbeatService, dispatch_queued_agent


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

    assert first is not None and first["status"] == "succeeded"
    assert second is not None and second["status"] == "succeeded"
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
            assert reviewer_run.status == "failed"
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


async def test_timer_wakeup_does_not_stack_when_timer_run_is_active(
    session: AsyncSession,
) -> None:
    agent = await _seed_agent(
        session,
        name="TimerCoalesces",
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
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
        runtime_config={"heartbeat": {"enabled": True, "intervalSec": 1}},
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


async def test_running_local_child_loss_fails_before_adapter_returns(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
) -> None:
    from server.services import heartbeat as heartbeat_module

    class LostChildAdapter:
        type = "process"

        async def execute(
            self, context: RuntimeExecutionContext
        ) -> RuntimeExecutionResult:
            if context.on_process_started is not None:
                await context.on_process_started(999_999, datetime.now(UTC))
            await asyncio.sleep(0.05)
            return RuntimeExecutionResult(
                exit_code=0,
                result_json={"summary": "should not complete"},
            )

    agent = await _seed_agent(session, name="LostChild")
    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda _runtime_type: LostChildAdapter(),
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
    assert run["status"] == "failed"
    assert run["errorCode"] == "process_lost"
    assert "999999" in (run["error"] or "")


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
