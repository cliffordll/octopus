from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

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
    Agent,
    AgentEnabledSkill,
    Base,
    Organization,
)


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    async with factory() as active_session:
        yield active_session


async def _seed_org(session: AsyncSession) -> Organization:
    org = Organization(url_key="agents-flow", name="Agents", issue_prefix="AGT")
    async with async_transaction(session):
        session.add(org)
    return org


async def test_agent_lifecycle_writes_activity_and_prevents_reporting_cycle(
    session: AsyncSession,
) -> None:
    from server.services.agents import AgentService

    org = await _seed_org(session)
    org_id = org.id
    service = AgentService(session)

    async with async_transaction(session):
        manager = await service.create_agent(
            org_id, {"name": "Lead"}, actor_type="board", actor_id="local-board"
        )
        worker = await service.create_agent(
            org_id,
            {"name": "Worker", "reportsTo": manager["id"]},
            actor_type="board",
            actor_id="local-board",
        )

    with pytest.raises(ValueError, match="cycle"):
        async with async_transaction(session):
            await service.update_agent(
                manager["id"],
                {"reportsTo": worker["id"]},
                actor_type="board",
                actor_id="local-board",
            )

    async with async_transaction(session):
        paused = await service.pause_agent(
            worker["id"], actor_type="board", actor_id="local-board"
        )
        resumed = await service.resume_agent(
            worker["id"], actor_type="board", actor_id="local-board"
        )
        terminated = await service.terminate_agent(
            worker["id"], actor_type="board", actor_id="local-board"
        )

    assert paused is not None and paused["status"] == "paused"
    assert resumed is not None and resumed["status"] == "idle"
    assert terminated is not None and terminated["status"] == "terminated"

    rows = (
        (
            await session.execute(
                select(ActivityLog)
                .where(ActivityLog.org_id == org_id)
                .order_by(ActivityLog.created_at, ActivityLog.id)
            )
        )
        .scalars()
        .all()
    )
    assert [row.action for row in rows] == [
        "agent.created",
        "agent.created",
        "agent.paused",
        "agent.resumed",
        "agent.terminated",
    ]


async def test_agent_creation_defaults_control_plane_skill_unless_explicit(
    session: AsyncSession,
) -> None:
    from server.services.agents import AgentService

    org = await _seed_org(session)
    service = AgentService(session)

    async with async_transaction(session):
        default_agent = await service.create_agent(
            org.id,
            {"name": "Default Skills"},
            actor_type="board",
            actor_id="local-board",
        )
        explicit_empty_agent = await service.create_agent(
            org.id,
            {"name": "Explicit Empty", "desiredSkills": []},
            actor_type="board",
            actor_id="local-board",
        )

    assert default_agent["desiredSkills"] == ["skills/control-plane"]
    assert explicit_empty_agent["desiredSkills"] == []

    rows = (
        (
            await session.execute(
                select(AgentEnabledSkill).order_by(
                    AgentEnabledSkill.agent_id, AgentEnabledSkill.skill_key
                )
            )
        )
        .scalars()
        .all()
    )
    assert [(row.agent_id, row.skill_key) for row in rows] == [
        (default_agent["id"], "skills/control-plane")
    ]


async def test_agent_runtime_config_prepares_organization_skills_root(
    session: AsyncSession, tmp_path, monkeypatch
) -> None:
    from server.services.agents import AgentService, prepare_agent_runtime_config

    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "octopus-home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "test")
    org = await _seed_org(session)
    service = AgentService(session)

    async with async_transaction(session):
        agent = await service.create_agent(
            org.id,
            {"name": "Runtime Config"},
            actor_type="board",
            actor_id="local-board",
        )

    row = (
        await session.execute(select(Agent).where(Agent.id == agent["id"]))
    ).scalar_one()
    config = await prepare_agent_runtime_config(session, row)
    skills_root = Path(config["skillsRootPath"])

    assert skills_root.is_dir()
    assert skills_root == (
        tmp_path
        / "octopus-home"
        / "instances"
        / "test"
        / "organizations"
        / org.id
        / "workspaces"
        / "skills"
    ).resolve()
    assert config["_octopus"]["organizationSkillsRootPath"] == str(skills_root)
    agent_skills_root = Path(config["_octopus"]["agentSkillsRootPath"])
    expected_agents_root = (
        tmp_path
        / "octopus-home"
        / "instances"
        / "test"
        / "organizations"
        / org.id
        / "workspaces"
        / "agents"
    ).resolve()
    assert agent_skills_root.parent.parent == expected_agents_root
    assert agent_skills_root.name == "skills"
    agent_home = agent_skills_root.parent
    assert (agent_home / "instructions").is_dir()
    assert (agent_home / "skills").is_dir()
    assert (agent_home / "life").is_dir()
    assert (agent_home / "memory").is_dir()


async def test_agent_config_revision_and_runtime_session_reset_write_activity(
    session: AsyncSession,
) -> None:
    from packages.database.schema import AgentRuntimeState, AgentTaskSession
    from server.services.agents import AgentService

    org = await _seed_org(session)
    org_id = org.id
    service = AgentService(session)
    async with async_transaction(session):
        agent = await service.create_agent(
            org_id, {"name": "Configured"}, actor_type="board", actor_id="local-board"
        )
        await service.update_agent(
            agent["id"],
            {"runtimeConfig": {"heartbeat": "enabled"}},
            actor_type="board",
            actor_id="local-board",
        )
        session.add(
            AgentRuntimeState(
                agent_id=agent["id"],
                org_id=org_id,
                agent_runtime_type="process",
                session_id="session-1",
                state_json={"resume": True},
            )
        )
        session.add(
            AgentTaskSession(
                org_id=org_id,
                agent_id=agent["id"],
                agent_runtime_type="process",
                task_key="issue-1",
                session_display_id="session-1",
            )
        )

    revisions = await service.list_config_revisions(agent["id"])
    assert revisions[0]["changedKeys"] == ["runtimeConfig"]
    await session.rollback()

    async with async_transaction(session):
        reset = await service.reset_runtime_session(
            agent["id"],
            {"taskKey": "issue-1"},
            actor_type="board",
            actor_id="local-board",
        )
    assert reset is not None
    assert reset["clearedTaskSessions"] == 1

    rows = (
        (
            await session.execute(
                select(ActivityLog)
                .where(ActivityLog.org_id == org_id)
                .order_by(ActivityLog.created_at, ActivityLog.id)
            )
        )
        .scalars()
        .all()
    )
    assert [row.action for row in rows] == [
        "agent.created",
        "agent.updated",
        "agent.runtime_session_reset",
    ]


async def test_wakeup_executes_process_runtime_and_records_failed_run(
    session: AsyncSession,
) -> None:
    from packages.database.schema import (
        AgentWakeupRequest,
        HeartbeatRun,
        HeartbeatRunEvent,
    )
    from server.services.agents import AgentService
    from server.services.heartbeat import HeartbeatService

    org = await _seed_org(session)
    agent_service = AgentService(session)
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        agent = await agent_service.create_agent(
            org.id,
            {"name": "Broken Adapter", "agentRuntimeConfig": {}},
            actor_type="board",
            actor_id="local-board",
        )
        run = await heartbeat.wakeup(
            agent["id"],
            {"source": "on_demand", "reason": "validate failure"},
            actor_type="board",
            actor_id="local-board",
        )
        assert run is not None
        await heartbeat.record_invoked_activity(
            run, actor_type="board", actor_id="local-board"
        )

    assert run is not None
    assert run["status"] == "failed"
    assert "command" in (run["error"] or "").lower()

    wakeup = (await session.execute(select(AgentWakeupRequest))).scalar_one()
    persisted_run = (await session.execute(select(HeartbeatRun))).scalar_one()
    events = (
        (
            await session.execute(
                select(HeartbeatRunEvent).order_by(HeartbeatRunEvent.seq)
            )
        )
        .scalars()
        .all()
    )
    activities = (
        (await session.execute(select(ActivityLog).order_by(ActivityLog.created_at)))
        .scalars()
        .all()
    )
    assert wakeup.status == "failed"
    assert persisted_run.status == "failed"
    assert [event.event_type for event in events] == [
        "lifecycle",
        "lifecycle",
        "adapter.invoke",
        "error",
    ]
    assert [activity.action for activity in activities] == [
        "agent.created",
        "heartbeat.invoked",
    ]


async def test_failed_issue_backed_run_releases_issue_execution_lock(
    session: AsyncSession,
) -> None:
    from packages.database.schema import Agent, HeartbeatRun, Issue
    from server.services.heartbeat import HeartbeatService

    org = await _seed_org(session)
    agent = Agent(
        org_id=org.id,
        name="Broken Issue Executor",
        role="engineer",
        status="idle",
        agent_runtime_config={},
    )
    issue = Issue(
        org_id=org.id,
        title="Failing issue execution",
        status="in_progress",
        assignee_agent_id=agent.id,
        origin_kind="manual",
    )
    heartbeat = HeartbeatService(session)
    async with async_transaction(session):
        session.add_all([agent, issue])
        await session.flush()
        queued = await heartbeat.wakeup(
            agent.id,
            {
                "source": "assignment",
                "reason": "issue_execute",
                "payload": {"issueId": issue.id},
                "contextSnapshot": {
                    "issueId": issue.id,
                    "wakeSource": "assignment",
                    "wakeReason": "issue_execute",
                },
            },
            actor_type="system",
            actor_id="issue-execution-test",
            execute_immediately=False,
        )
        assert queued is not None
        issue.execution_run_id = queued["id"]
        issue.checkout_run_id = queued["id"]
        issue.execution_agent_name_key = "broken-issue-executor"
        issue.execution_locked_at = datetime.now(UTC)

    resumed = await heartbeat.resume_queued_runs(agent.id)

    assert len(resumed) == 1
    executed = resumed[0]
    assert executed["status"] == "failed"
    persisted_run = (await session.execute(select(HeartbeatRun))).scalar_one()
    persisted_issue = (await session.execute(select(Issue))).scalar_one()
    assert persisted_run.status == "failed"
    assert persisted_issue.status == "in_progress"
    assert persisted_issue.execution_run_id is None
    assert persisted_issue.checkout_run_id is None
    assert persisted_issue.execution_agent_name_key is None
    assert persisted_issue.execution_locked_at is None
