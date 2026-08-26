from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from packages.database.clients import async_transaction, create_session_factory
from packages.database.schema import (
    ActivityLog,
    Agent,
    AgentWakeupRequest,
    Base,
    HeartbeatRun,
    HeartbeatRunEvent,
    Issue,
    IssueComment,
    IssueWorkProduct,
    Organization,
)
from packages.shared.types.issue import CreateChildIssuesPayload, IssueDetail
from server.app import app as fastapi_app
from server.services.heartbeat import HeartbeatService
from server.services.child_recovery import (
    ChildRecoveryCoordinator,
    ChildRecoveryUnavailable,
)
from server.services.issues import IssueService
from server.services.parent_child_control import (
    ParentChildControlAuthorizer,
    ParentChildControlContext,
    ParentChildControlDenied,
)


class _ParentRunProbe:
    def __init__(self, active: bool) -> None:
        self.active = active

    async def is_active_parent_run(self, *_args: Any, **_kwargs: Any) -> bool:
        return self.active


class _ChildRunProbe:
    def __init__(self, runs: list[dict[str, Any]]) -> None:
        self.runs = runs

    async def list_for_issue(self, _issue_id: str) -> list[dict[str, Any]]:
        return self.runs


def _parent_control_issue() -> IssueDetail:
    return cast(
        IssueDetail,
        {
            "id": "parent-1",
            "orgId": "org-1",
            "assigneeAgentId": "manager-1",
        },
    )


async def test_parent_child_control_requires_active_parent_run_for_agents() -> None:
    context = ParentChildControlContext(parent=_parent_control_issue())
    inactive = ParentChildControlAuthorizer(
        cast(HeartbeatService, _ParentRunProbe(False))
    )
    with pytest.raises(ParentChildControlDenied, match="active parent Run"):
        await inactive.authorize(
            context,
            actor_type="agent",
            actor_id="manager-1",
            run_id="run-1",
        )

    active = ParentChildControlAuthorizer(cast(HeartbeatService, _ParentRunProbe(True)))
    await active.authorize(
        context,
        actor_type="agent",
        actor_id="manager-1",
        run_id="run-1",
    )


async def test_parent_child_control_rejects_non_owner_agent_but_allows_board() -> None:
    context = ParentChildControlContext(parent=_parent_control_issue())
    authorizer = ParentChildControlAuthorizer(
        cast(HeartbeatService, _ParentRunProbe(True))
    )
    with pytest.raises(ParentChildControlDenied, match="parent assignee"):
        await authorizer.authorize(
            context,
            actor_type="agent",
            actor_id="child-agent",
            run_id="run-1",
        )
    await authorizer.authorize(
        context,
        actor_type="board",
        actor_id="local-board",
        run_id=None,
    )


async def test_child_replacement_requires_one_failed_retry_first() -> None:
    original = {"runId": "run-original", "status": "failed", "retryOfRunId": None}
    coordinator = ChildRecoveryCoordinator(
        cast(IssueService, object()),
        cast(HeartbeatService, _ChildRunProbe([original])),
    )
    with pytest.raises(ChildRecoveryUnavailable, match="Retry the existing child"):
        await coordinator.require_failed_retry_before_replacement("child-1")

    failed_retry = {
        "runId": "run-retry",
        "status": "failed",
        "retryOfRunId": "run-original",
    }
    coordinator = ChildRecoveryCoordinator(
        cast(IssueService, object()),
        cast(HeartbeatService, _ChildRunProbe([failed_retry, original])),
    )
    await coordinator.require_failed_retry_before_replacement("child-1")


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
async def app(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[FastAPI]:
    original_settings = fastapi_app.state.settings
    fastapi_app.state.session_factory = session_factory
    fastapi_app.state.settings = replace(original_settings, local_trusted=True)
    try:
        yield fastapi_app
    finally:
        tasks = list(getattr(fastapi_app.state, "heartbeat_dispatch_tasks", set()))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        fastapi_app.state.heartbeat_dispatch_tasks = set()
        fastapi_app.state.settings = original_settings


async def _seed_org(
    session: AsyncSession,
) -> str:
    org_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"u-{org_id[:8]}",
                name="Step8 Org",
                issue_prefix=org_id[:6],
            )
        )
    return org_id


async def _seed_issue(
    session: AsyncSession,
    org_id: str,
    *,
    title: str = "Seeded issue",
    status: str = "todo",
    project_id: str | None = None,
    goal_id: str | None = None,
    assignee_agent_id: str | None = None,
    origin_kind: str = "manual",
    origin_id: str | None = None,
) -> str:
    issue_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title=title,
                status=status,
                project_id=project_id,
                goal_id=goal_id,
                assignee_agent_id=assignee_agent_id,
                origin_kind=origin_kind,
                origin_id=origin_id,
            )
        )
    return issue_id


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path, json=json, headers=headers)
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body


async def test_create_issue_route_returns_200_and_persists(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={"title": "Created from route", "status": "todo", "originKind": "manual"},
    )

    assert code == 200
    assert body["orgId"] == org_id
    assert body["title"] == "Created from route"
    assert body["status"] == "todo"

    async with session_factory() as verify:
        result = await verify.execute(select(Issue).where(Issue.org_id == org_id))
        rows = result.scalars().all()
    assert len(rows) == 1


async def test_create_children_batch_persists_once_and_reuses_on_retry(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    other_org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, title="Parent", status="backlog")
    agent_id = str(uuid.uuid4())
    other_agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add_all(
            [
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="Child Worker",
                    role="engineer",
                    status="paused",
                ),
                Agent(
                    id=other_agent_id,
                    org_id=other_org_id,
                    name="Other Org Worker",
                    role="engineer",
                ),
            ]
        )

    payload = {
        "children": [
            {
                "title": "Research Huangshan",
                "description": "Produce the Huangshan source material.",
                "assigneeAgentId": agent_id,
            },
            {
                "title": "Research Lushan",
                "description": "Produce the Lushan source material.",
                "assigneeAgentId": agent_id,
            },
        ]
    }
    first_code, first = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        json=payload,
    )
    retry_code, retry = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        json={
            "children": [
                {
                    "title": "Changed retry title",
                    "assigneeAgentId": agent_id,
                }
            ]
        },
    )
    missing_retry_code, missing_retry = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        json={
            "children": [
                {
                    "title": "Another changed retry title",
                    "assigneeAgentId": str(uuid.uuid4()),
                }
            ]
        },
    )
    cross_org_retry_code, cross_org_retry = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        json={
            "children": [
                {
                    "title": "Cross-org changed retry title",
                    "assigneeAgentId": other_agent_id,
                }
            ]
        },
    )

    async with async_transaction(session):
        persisted_parent = await session.get(Issue, parent_id)
        assert persisted_parent is not None
        persisted_parent.status = "done"
        persisted_parent.completed_at = datetime.now(UTC)
    closed_retry_code, closed_retry = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        json={
            "children": [
                {
                    "title": "Closed parent retry",
                    "assigneeAgentId": str(uuid.uuid4()),
                }
            ]
        },
    )

    assert first_code == 200
    assert first["created"] is True
    assert len(first["children"]) == 2
    assert retry_code == 200
    assert retry["created"] is False
    assert missing_retry_code == 200
    assert missing_retry["created"] is False
    assert cross_org_retry_code == 200
    assert cross_org_retry["created"] is False
    assert closed_retry_code == 200
    assert closed_retry["created"] is False
    assert {item["id"] for item in retry["children"]} == {
        item["id"] for item in first["children"]
    }
    assert {item["id"] for item in missing_retry["children"]} == {
        item["id"] for item in first["children"]
    }
    assert {item["id"] for item in cross_org_retry["children"]} == {
        item["id"] for item in first["children"]
    }
    assert {item["id"] for item in closed_retry["children"]} == {
        item["id"] for item in first["children"]
    }

    async with session_factory() as verify:
        children = (
            (await verify.execute(select(Issue).where(Issue.parent_id == parent_id)))
            .scalars()
            .all()
        )
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(children) == 2
    assert len(wakeups) == 2


async def test_create_children_batch_rejects_duplicate_titles(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, title="Parent", status="in_progress")
    agent_id = str(uuid.uuid4())

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        json={
            "children": [
                {"title": "Research Lushan", "assigneeAgentId": agent_id},
                {"title": " research lushan ", "assigneeAgentId": agent_id},
            ]
        },
    )

    assert code == 422
    assert "duplicates another child" in body["detail"]
    children = (
        (await session.execute(select(Issue).where(Issue.parent_id == parent_id)))
        .scalars()
        .all()
    )
    assert children == []


async def test_create_children_batch_rejects_missing_or_cross_org_assignee(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    other_org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, title="Parent", status="in_progress")
    other_agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=other_agent_id,
                org_id=other_org_id,
                name="Other Org Worker",
                role="engineer",
            )
        )

    for assignee_id in (str(uuid.uuid4()), other_agent_id):
        code, body = await _request(
            app,
            "POST",
            f"/api/issues/{parent_id}/children/batch",
            json={
                "children": [
                    {"title": "Research Lushan", "assigneeAgentId": assignee_id}
                ]
            },
        )
        assert code == 422
        assert "parent organization" in body["detail"]

    children = (
        (await session.execute(select(Issue).where(Issue.parent_id == parent_id)))
        .scalars()
        .all()
    )
    assert children == []


async def test_create_children_batch_checks_org_access_before_write(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    other_org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, title="Parent", status="in_progress")
    other_agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=other_agent_id,
                org_id=other_org_id,
                name="Other Org Agent",
                role="engineer",
            )
        )

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        json={
            "children": [
                {"title": "Unauthorized child", "assigneeAgentId": other_agent_id}
            ]
        },
        headers={"x-test-agent-id": other_agent_id, "x-test-org-id": other_org_id},
    )

    assert code == 403
    assert "another organization" in body["detail"]
    children = (
        (await session.execute(select(Issue).where(Issue.parent_id == parent_id)))
        .scalars()
        .all()
    )
    assert children == []


async def test_create_children_batch_is_single_winner_across_sqlite_sessions(
    tmp_path: Path,
) -> None:
    database_path = (tmp_path / "child-batch.db").resolve().as_posix()
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}", connect_args={"timeout": 10}
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    org_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    async with factory() as seed:
        async with seed.begin():
            seed.add_all(
                [
                    Organization(
                        id=org_id,
                        url_key=f"batch-{uuid.uuid4()}",
                        name="Batch Org",
                        issue_prefix="BAT",
                    ),
                    Agent(
                        id=agent_id,
                        org_id=org_id,
                        name="Batch Worker",
                        role="engineer",
                    ),
                    Issue(
                        id=parent_id,
                        org_id=org_id,
                        title="Concurrent parent",
                        status="in_progress",
                    ),
                ]
            )

    async def create_batch(title: str) -> tuple[list[str], bool]:
        async with factory() as current:
            async with current.begin():
                _parent, children, created = await IssueService(
                    current
                ).create_child_issues(
                    parent_id,
                    {"children": [{"title": title, "assigneeAgentId": agent_id}]},
                    actor_type="board",
                    actor_id="local-board",
                )
            return [child["id"] for child in children], created

    try:
        first, second = await asyncio.gather(
            create_batch("First proposed split"),
            create_batch("Changed retry split"),
        )
        assert sorted((first[1], second[1])) == [False, True]
        assert first[0] == second[0]
        async with factory() as verify:
            children = (
                (
                    await verify.execute(
                        select(Issue).where(Issue.parent_id == parent_id)
                    )
                )
                .scalars()
                .all()
            )
        assert len(children) == 1
    finally:
        await engine.dispose()


async def test_create_children_batch_scopes_retries_to_parent_run(
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, title="Parent", status="in_progress")
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Worker",
                role="engineer",
            )
        )

    payload: CreateChildIssuesPayload = {
        "closeoutPolicy": {"version": 1, "mode": "child_outputs_are_final"},
        "children": [{"title": "Same title", "assigneeAgentId": agent_id}],
    }
    first_parent_run_id = str(uuid.uuid4())
    second_parent_run_id = str(uuid.uuid4())
    async with async_transaction(session):
        _parent, first, first_created = await IssueService(session).create_child_issues(
            parent_id,
            payload,
            actor_type="agent",
            actor_id=str(uuid.uuid4()),
            run_id=first_parent_run_id,
        )
    async with async_transaction(session):
        _parent, replay, replay_created = await IssueService(
            session
        ).create_child_issues(
            parent_id,
            payload,
            actor_type="agent",
            actor_id=str(uuid.uuid4()),
            run_id=first_parent_run_id,
        )
    async with async_transaction(session):
        _parent, second, second_created = await IssueService(
            session
        ).create_child_issues(
            parent_id,
            payload,
            actor_type="agent",
            actor_id=str(uuid.uuid4()),
            run_id=second_parent_run_id,
        )

    assert first_created is True
    assert replay_created is False
    assert second_created is True
    assert replay[0]["id"] == first[0]["id"]
    assert second[0]["id"] != first[0]["id"]
    assert first[0]["originRunId"] == first_parent_run_id
    assert second[0]["originRunId"] == second_parent_run_id
    assert first[0]["closeoutPolicy"] == {
        "version": 1,
        "mode": "child_outputs_are_final",
    }
    parent = await IssueService(session).get_by_id(parent_id)
    assert parent is not None
    assert parent["status"] == "in_progress"


async def test_create_children_batch_rolls_back_if_any_wakeup_fails(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, title="Parent", status="in_progress")
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Child Worker",
                role="engineer",
                status="paused",
            )
        )

    wakeup_calls = 0
    from server.routes import issues as issue_routes

    original_wakeup = issue_routes.queue_issue_assignment_wakeup

    async def fail_second_wakeup(*args: Any, **kwargs: Any) -> None:
        nonlocal wakeup_calls
        wakeup_calls += 1
        if wakeup_calls == 2:
            raise RuntimeError("simulated wakeup failure")
        await original_wakeup(*args, **kwargs)

    monkeypatch.setattr(
        "server.routes.issues.queue_issue_assignment_wakeup", fail_second_wakeup
    )

    with pytest.raises(RuntimeError, match="simulated wakeup failure"):
        await _request(
            app,
            "POST",
            f"/api/issues/{parent_id}/children/batch",
            json={
                "children": [
                    {"title": "Research Huangshan", "assigneeAgentId": agent_id},
                    {"title": "Research Lushan", "assigneeAgentId": agent_id},
                ]
            },
        )

    async with session_factory() as verify:
        children = (
            (await verify.execute(select(Issue).where(Issue.parent_id == parent_id)))
            .scalars()
            .all()
        )
        wakeups = (await verify.execute(select(AgentWakeupRequest))).scalars().all()
    assert children == []
    assert wakeups == []
    assert wakeup_calls == 2


async def test_create_children_batch_commits_before_dispatch_is_scheduled(
    app: FastAPI,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, title="Parent", status="in_progress")
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Child Worker",
                role="engineer",
                status="paused",
            )
        )

    committed = False
    scheduled: list[str] = []
    original_commit = IssueService.commit_child_issues

    async def record_commit(service: IssueService) -> None:
        nonlocal committed
        await original_commit(service)
        committed = True

    def record_schedule(request: Any, scheduled_agent_id: str) -> None:
        assert committed is True
        scheduled.append(scheduled_agent_id)

    monkeypatch.setattr(IssueService, "commit_child_issues", record_commit)
    monkeypatch.setattr("server.routes.issues._schedule_dispatch", record_schedule)

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        json={"children": [{"title": "Research Lushan", "assigneeAgentId": agent_id}]},
    )

    assert code == 200
    assert body["created"] is True
    assert body["dispatchAgentIds"] == []
    assert scheduled == []


async def test_parent_run_and_children_are_dispatchable_concurrently(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = await _seed_org(session)
    parent_agent_id = str(uuid.uuid4())
    child_agent_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    parent_id = str(uuid.uuid4())
    parent_run_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add_all(
            [
                Agent(
                    id=parent_agent_id,
                    org_id=org_id,
                    name="Parent Worker",
                    role="manager",
                    status="running",
                ),
                *[
                    Agent(
                        id=agent_id,
                        org_id=org_id,
                        name=f"Child Worker {index}",
                        role="engineer",
                    )
                    for index, agent_id in enumerate(child_agent_ids)
                ],
                Issue(
                    id=parent_id,
                    org_id=org_id,
                    title="Coordinating parent",
                    status="in_progress",
                    assignee_agent_id=parent_agent_id,
                    execution_run_id=parent_run_id,
                ),
                HeartbeatRun(
                    id=parent_run_id,
                    org_id=org_id,
                    agent_id=parent_agent_id,
                    invocation_source="assignment",
                    run_purpose="task_execution",
                    trigger_detail="system",
                    status="running",
                    execution_owner_token="parent-owner",
                    context_snapshot={"issueId": parent_id},
                ),
            ]
        )

    scheduled: list[str] = []
    monkeypatch.setattr(
        "server.routes.issues._schedule_dispatch",
        lambda _request, agent_id: scheduled.append(agent_id),
    )
    headers = {
        "x-test-agent-id": parent_agent_id,
        "x-test-org-id": org_id,
        "x-test-run-id": parent_run_id,
    }
    create_code, created = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        headers=headers,
        json={
            "closeoutPolicy": {
                "version": 1,
                "mode": "child_outputs_are_final",
            },
            "children": [
                {
                    "title": "Child A",
                    "assigneeAgentId": child_agent_ids[0],
                },
                {
                    "title": "Child B",
                    "assigneeAgentId": child_agent_ids[1],
                },
            ],
        },
    )

    assert create_code == 200
    assert {child["originRunId"] for child in created["children"]} == {parent_run_id}
    assert {child["closeoutPolicy"]["mode"] for child in created["children"]} == {
        "child_outputs_are_final"
    }
    assert created["dispatchAgentIds"] == sorted(child_agent_ids)
    assert set(scheduled) == set(child_agent_ids)
    async with session_factory() as verify:
        parent_run = await verify.get(HeartbeatRun, parent_run_id)
        wakeups = (await verify.execute(select(AgentWakeupRequest))).scalars().all()
        child_runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(HeartbeatRun.id != parent_run_id)
                )
            )
            .scalars()
            .all()
        )
    assert parent_run is not None and parent_run.status == "running"
    assert len(wakeups) == 2
    assert {wakeup.status for wakeup in wakeups} == {"queued"}
    assert len(child_runs) == 2
    assert {run.status for run in child_runs} == {"queued"}

    replay_code, replayed = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        headers=headers,
        json={
            "children": [
                {
                    "title": "Changed replay title A",
                    "assigneeAgentId": child_agent_ids[0],
                },
                {
                    "title": "Changed replay title B",
                    "assigneeAgentId": child_agent_ids[1],
                },
            ]
        },
    )
    assert replay_code == 200
    assert replayed["created"] is False
    assert [child["id"] for child in replayed["children"]] == [
        child["id"] for child in created["children"]
    ]
    async with session_factory() as verify:
        wakeups_after_replay = (
            (await verify.execute(select(AgentWakeupRequest))).scalars().all()
        )
        parent_run = await verify.get(HeartbeatRun, parent_run_id)
    assert len(wakeups_after_replay) == 2
    assert parent_run is not None and parent_run.status == "running"


async def test_recovery_does_not_block_already_dispatched_children(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = await _seed_org(session)
    parent_agent_id = str(uuid.uuid4())
    child_agent_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    parent_run_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add_all(
            [
                Agent(
                    id=parent_agent_id,
                    org_id=org_id,
                    name="Parent Worker",
                    role="manager",
                    status="running",
                ),
                Agent(
                    id=child_agent_id,
                    org_id=org_id,
                    name="Child Worker",
                    role="engineer",
                ),
                Issue(
                    id=parent_id,
                    org_id=org_id,
                    title="Parent that forgets to yield",
                    status="in_progress",
                    assignee_agent_id=parent_agent_id,
                    execution_run_id=parent_run_id,
                ),
                HeartbeatRun(
                    id=parent_run_id,
                    org_id=org_id,
                    agent_id=parent_agent_id,
                    invocation_source="assignment",
                    run_purpose="task_execution",
                    trigger_detail="system",
                    status="running",
                    execution_owner_token="parent-owner",
                    context_snapshot={"issueId": parent_id},
                ),
            ]
        )
    monkeypatch.setattr("server.routes.issues._schedule_dispatch", lambda *_args: None)
    headers = {
        "x-test-agent-id": parent_agent_id,
        "x-test-org-id": org_id,
        "x-test-run-id": parent_run_id,
    }
    create_code, created = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/children/batch",
        headers=headers,
        json={
            "children": [{"title": "Deferred child", "assigneeAgentId": child_agent_id}]
        },
    )
    assert create_code == 200
    assert created["dispatchAgentIds"] == [child_agent_id]

    monkeypatch.setattr(HeartbeatService, "PARENT_COORDINATION_GRACE_SECONDS", 0)
    async with session_factory() as recovery_session:
        async with async_transaction(recovery_session):
            await HeartbeatService(recovery_session).recover_orphaned_runs(
                require_process_loss=True
            )

    async with session_factory() as verify:
        parent_run = await verify.get(HeartbeatRun, parent_run_id)
        child_runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(HeartbeatRun.id != parent_run_id)
                )
            )
            .scalars()
            .all()
        )
        wakeups = (await verify.execute(select(AgentWakeupRequest))).scalars().all()
    assert parent_run is not None and parent_run.status == "running"
    child_issue_id = created["children"][0]["id"]
    assert any(
        run.status == "queued"
        and isinstance(run.context_snapshot, dict)
        and run.context_snapshot.get("issueId") == child_issue_id
        for run in child_runs
    )
    assert len(wakeups) == 1 and wakeups[0].status == "queued"

    async with session_factory() as expire_session:
        async with async_transaction(expire_session):
            expiring = await expire_session.get(HeartbeatRun, parent_run_id)
            assert expiring is not None
            expiring.execution_lease_expires_at = datetime.now(UTC) - timedelta(
                seconds=1
            )
    async with session_factory() as recovery_session:
        async with async_transaction(recovery_session):
            await HeartbeatService(recovery_session).recover_orphaned_runs()
    async with session_factory() as verify:
        parent_run = await verify.get(HeartbeatRun, parent_run_id)
        child_runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(HeartbeatRun.id != parent_run_id)
                )
            )
            .scalars()
            .all()
        )
    assert parent_run is not None and parent_run.status in {"failed", "timed_out"}
    assert any(
        run.status == "queued"
        and isinstance(run.context_snapshot, dict)
        and run.context_snapshot.get("issueId") == child_issue_id
        for run in child_runs
    )


async def test_parent_yield_without_child_work_is_rejected(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add_all(
            [
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="Parent Without Children",
                    role="manager",
                    status="running",
                ),
                Issue(
                    id=parent_id,
                    org_id=org_id,
                    title="No child work",
                    status="in_progress",
                    assignee_agent_id=agent_id,
                    execution_run_id=run_id,
                ),
                HeartbeatRun(
                    id=run_id,
                    org_id=org_id,
                    agent_id=agent_id,
                    invocation_source="assignment",
                    run_purpose="task_execution",
                    trigger_detail="system",
                    status="running",
                    execution_owner_token="no-child-owner",
                    context_snapshot={"issueId": parent_id},
                ),
            ]
        )

    code, response = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/yield-children",
        headers={
            "x-test-agent-id": agent_id,
            "x-test-org-id": org_id,
            "x-test-run-id": run_id,
        },
        json={},
    )

    assert code == 404
    assert response["detail"] == "Not Found"
    async with session_factory() as verify:
        parent_run = await verify.get(HeartbeatRun, run_id)
    assert parent_run is not None and parent_run.status == "running"


async def test_parent_child_retry_is_queued_while_parent_runs(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = await _seed_org(session)
    parent_agent_id = str(uuid.uuid4())
    child_agent_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    parent_run_id = str(uuid.uuid4())
    failed_run_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add_all(
            [
                Agent(
                    id=parent_agent_id,
                    org_id=org_id,
                    name="Parent Worker",
                    role="manager",
                    status="running",
                ),
                Agent(
                    id=child_agent_id,
                    org_id=org_id,
                    name="Child Worker",
                    role="engineer",
                ),
                Issue(
                    id=parent_id,
                    org_id=org_id,
                    title="Parent retry coordinator",
                    status="in_progress",
                    assignee_agent_id=parent_agent_id,
                    execution_run_id=parent_run_id,
                ),
                Issue(
                    id=child_id,
                    org_id=org_id,
                    parent_id=parent_id,
                    title="Blocked child",
                    status="blocked",
                    assignee_agent_id=child_agent_id,
                ),
                HeartbeatRun(
                    id=parent_run_id,
                    org_id=org_id,
                    agent_id=parent_agent_id,
                    invocation_source="assignment",
                    run_purpose="task_execution",
                    trigger_detail="system",
                    status="running",
                    execution_owner_token="parent-owner",
                    context_snapshot={"issueId": parent_id},
                ),
                HeartbeatRun(
                    id=failed_run_id,
                    org_id=org_id,
                    agent_id=child_agent_id,
                    invocation_source="assignment",
                    run_purpose="task_execution",
                    trigger_detail="system",
                    status="timed_out",
                    finished_at=datetime.now(UTC),
                    error="Runtime produced no output for 300s",
                    error_code="timeout",
                    context_snapshot={"issueId": child_id},
                ),
            ]
        )
    scheduled: list[str] = []
    monkeypatch.setattr(
        "server.routes.issues._schedule_dispatch",
        lambda _request, agent_id: scheduled.append(agent_id),
    )
    headers = {
        "x-test-agent-id": parent_agent_id,
        "x-test-org-id": org_id,
        "x-test-run-id": parent_run_id,
    }

    retry_code, retried = await _request(
        app,
        "POST",
        f"/api/issues/{child_id}/retry-child",
        headers=headers,
        json={},
    )
    assert retry_code == 200
    assert retried["status"] == "queued"
    repeated_retry_code, repeated_retry = await _request(
        app,
        "POST",
        f"/api/issues/{child_id}/retry-child",
        headers=headers,
        json={},
    )
    assert repeated_retry_code == 200
    assert repeated_retry.get("runId", repeated_retry.get("id")) == retried.get(
        "runId", retried.get("id")
    )
    async with session_factory() as verify:
        retry_run = await verify.get(
            HeartbeatRun, retried.get("runId", retried.get("id"))
        )
        parent_run = await verify.get(HeartbeatRun, parent_run_id)
    assert retry_run is not None and retry_run.status == "queued"
    assert parent_run is not None and parent_run.status == "running"
    assert scheduled == []


async def test_parent_replacement_retires_old_child_and_dispatches_immediately(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = await _seed_org(session)
    parent_agent_id = str(uuid.uuid4())
    child_agent_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    old_child_id = str(uuid.uuid4())
    parent_run_id = str(uuid.uuid4())
    failed_run_id = str(uuid.uuid4())
    failed_retry_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add_all(
            [
                Agent(
                    id=parent_agent_id,
                    org_id=org_id,
                    name="Parent Worker",
                    role="manager",
                    status="running",
                ),
                Agent(
                    id=child_agent_id,
                    org_id=org_id,
                    name="Child Worker",
                    role="engineer",
                ),
                Issue(
                    id=parent_id,
                    org_id=org_id,
                    title="Replacement coordinator",
                    status="in_progress",
                    assignee_agent_id=parent_agent_id,
                    execution_run_id=parent_run_id,
                ),
                Issue(
                    id=old_child_id,
                    org_id=org_id,
                    parent_id=parent_id,
                    title="Old blocked child",
                    status="blocked",
                    assignee_agent_id=child_agent_id,
                ),
                HeartbeatRun(
                    id=parent_run_id,
                    org_id=org_id,
                    agent_id=parent_agent_id,
                    invocation_source="assignment",
                    run_purpose="task_execution",
                    trigger_detail="system",
                    status="running",
                    execution_owner_token="parent-owner",
                    context_snapshot={"issueId": parent_id},
                ),
                HeartbeatRun(
                    id=failed_run_id,
                    org_id=org_id,
                    agent_id=child_agent_id,
                    invocation_source="assignment",
                    run_purpose="task_execution",
                    trigger_detail="system",
                    status="failed",
                    created_at=datetime.now(UTC) - timedelta(minutes=2),
                    finished_at=datetime.now(UTC) - timedelta(minutes=1),
                    context_snapshot={"issueId": old_child_id},
                ),
                HeartbeatRun(
                    id=failed_retry_id,
                    org_id=org_id,
                    agent_id=child_agent_id,
                    invocation_source="on_demand",
                    run_purpose="task_execution",
                    trigger_detail="manual",
                    status="failed",
                    retry_of_run_id=failed_run_id,
                    created_at=datetime.now(UTC) - timedelta(seconds=30),
                    finished_at=datetime.now(UTC),
                    context_snapshot={"issueId": old_child_id},
                ),
            ]
        )
    scheduled: list[str] = []
    monkeypatch.setattr(
        "server.routes.issues._schedule_dispatch",
        lambda _request, agent_id: scheduled.append(agent_id),
    )
    headers = {
        "x-test-agent-id": parent_agent_id,
        "x-test-org-id": org_id,
        "x-test-run-id": parent_run_id,
    }

    replace_code, replacement = await _request(
        app,
        "POST",
        f"/api/issues/{old_child_id}/replace-child",
        headers=headers,
        json={"title": "Replacement child"},
    )
    assert replace_code == 201
    repeated_replace_code, repeated_replacement = await _request(
        app,
        "POST",
        f"/api/issues/{old_child_id}/replace-child",
        headers=headers,
        json={"title": "A different replay title"},
    )
    assert repeated_replace_code == 201
    assert repeated_replacement["id"] == replacement["id"]
    async with session_factory() as verify:
        old_child = await verify.get(Issue, old_child_id)
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.payload["issueId"].as_string()
                        == replacement["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
    assert old_child is not None and old_child.hidden_at is not None
    assert len(wakeups) == 1 and wakeups[0].status == "queued"
    assert scheduled == [child_agent_id]
    async with session_factory() as verify:
        replacement_runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(
                        HeartbeatRun.context_snapshot["issueId"].as_string()
                        == replacement["id"]
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(replacement_runs) == 1
    assert replacement_runs[0].status == "queued"
    assert scheduled == [child_agent_id]


async def test_terminal_child_updated_by_identifier_queues_parent_continuation(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    parent_agent_id = str(uuid.uuid4())
    child_agent_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add_all(
            [
                Agent(
                    id=parent_agent_id,
                    org_id=org_id,
                    name="Parent Worker",
                    role="engineer",
                    status="paused",
                ),
                Agent(
                    id=child_agent_id,
                    org_id=org_id,
                    name="Child Worker",
                    role="engineer",
                    status="paused",
                ),
                Issue(
                    id=parent_id,
                    org_id=org_id,
                    identifier="PAR-1",
                    title="Parent",
                    status="in_progress",
                    assignee_agent_id=parent_agent_id,
                ),
                Issue(
                    id=child_id,
                    org_id=org_id,
                    identifier="CHD-1",
                    parent_id=parent_id,
                    title="Child",
                    status="in_progress",
                    assignee_agent_id=child_agent_id,
                ),
            ]
        )

    code, body = await _request(
        app,
        "PATCH",
        "/api/issues/CHD-1",
        json={"status": "done"},
    )

    assert code == 200
    assert body["id"] == child_id
    async with session_factory() as verify:
        wakeup = (
            await verify.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == parent_agent_id,
                    AgentWakeupRequest.reason == "issue_children_settled",
                )
            )
        ).scalar_one()
    assert wakeup.payload is not None
    assert wakeup.payload["issueId"] == parent_id


async def test_replace_child_rejects_stale_request_for_completed_work_product(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, title="Parent", status="in_progress")
    child_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Issue(
                id=child_id,
                org_id=org_id,
                parent_id=parent_id,
                title="Completed child",
                status="done",
                completed_at=datetime.now(UTC),
            )
        )
        session.add(
            IssueWorkProduct(
                org_id=org_id,
                issue_id=child_id,
                type="document",
                provider="octopus",
                title="reports/child.md",
                status="active",
                is_primary=True,
            )
        )

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{child_id}/replace-child",
        json={"title": "Stale replacement"},
    )

    assert code == 409
    assert body["detail"] == (
        "Completed child issue already has registered work products"
    )
    async with session_factory() as verify:
        children = (
            (await verify.execute(select(Issue).where(Issue.parent_id == parent_id)))
            .scalars()
            .all()
        )
    assert [child.id for child in children] == [child_id]


async def test_issue_lookup_prefers_exact_uuid_over_identifier_collision(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    exact_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add_all(
            [
                Issue(
                    id=exact_id,
                    org_id=org_id,
                    identifier="EXACT-1",
                    title="Exact UUID issue",
                    status="todo",
                ),
                Issue(
                    org_id=org_id,
                    identifier=exact_id,
                    title="Identifier collision",
                    status="todo",
                ),
            ]
        )

    code, body = await _request(app, "GET", f"/api/issues/{exact_id}")

    assert code == 200
    assert body["id"] == exact_id
    assert body["title"] == "Exact UUID issue"


async def test_create_assigned_issue_queues_assignment_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Issue Owner",
                role="engineer",
                status="idle",
            )
        )

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={
            "title": "Assigned task",
            "status": "todo",
            "priority": "high",
            "assigneeAgentId": agent_id,
        },
    )

    assert code == 200
    assert body["assigneeAgentId"] == agent_id

    async with session_factory() as verify:
        wakeup = (
            await verify.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == agent_id
                )
            )
        ).scalar_one()
        run = (
            await verify.execute(
                select(HeartbeatRun).where(HeartbeatRun.agent_id == agent_id)
            )
        ).scalar_one()
        events = (
            (
                await verify.execute(
                    select(HeartbeatRunEvent).where(HeartbeatRunEvent.run_id == run.id)
                )
            )
            .scalars()
            .all()
        )
        issue = await verify.get(Issue, body["id"])

    assert wakeup.source == "assignment"
    assert wakeup.trigger_detail == "system"
    assert wakeup.reason == "issue_assigned"
    assert wakeup.payload == {"issueId": body["id"], "mutation": "create"}
    assert run.status == "queued"
    assert run.invocation_source == "assignment"
    assert run.trigger_detail == "system"
    assert run.context_snapshot is not None
    assert run.context_snapshot["triggeredBy"] == "user"
    assert run.context_snapshot["actorId"] == "local-board"
    assert run.context_snapshot["forceFreshSession"] is False
    assert run.context_snapshot["issueId"] == body["id"]
    assert run.context_snapshot["source"] == "issue.create"
    assert run.context_snapshot["wakeSource"] == "assignment"
    assert run.context_snapshot["wakeReason"] == "issue_assigned"
    assert run.context_snapshot["issue"] == {
        "id": body["id"],
        "title": "Assigned task",
        "description": None,
        "status": "todo",
        "priority": "high",
    }
    assert run.context_snapshot["commentCursor"] is None
    assert run.context_snapshot["documentSummaries"] == []
    assert run.context_snapshot["ancestors"] == []
    assert run.context_snapshot["project"] is None
    assert run.context_snapshot["goal"] is None
    assert run.context_snapshot["planDocument"] is None
    assert run.context_snapshot["legacyPlanDocument"] is None
    assert run.context_snapshot["issueDocumentsPrompt"] == ""
    assert run.context_snapshot["wakeComment"] is None
    assert [(event.seq, event.event_type, event.message) for event in events] == [
        (1, "lifecycle", "run queued")
    ]
    assert issue is not None
    assert issue.status == "in_progress"
    assert issue.execution_run_id == run.id
    assert issue.checkout_run_id == run.id


async def test_create_assigned_issue_skips_wakeup_when_on_demand_disabled(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="No Demand Owner",
                role="engineer",
                status="idle",
                runtime_config={
                    "heartbeat": {
                        "enabled": True,
                        "intervalSec": 300,
                        "wakeOnDemand": False,
                    }
                },
            )
        )

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={
            "title": "Assigned but demand disabled",
            "status": "todo",
            "assigneeAgentId": agent_id,
        },
    )

    assert code == 200
    assert body["assigneeAgentId"] == agent_id
    async with session_factory() as verify:
        wakeup = (
            await verify.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == agent_id
                )
            )
        ).scalar_one()
        runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(HeartbeatRun.agent_id == agent_id)
                )
            )
            .scalars()
            .all()
        )

    assert wakeup.source == "assignment"
    assert wakeup.status == "skipped"
    assert wakeup.reason == "issue_assigned"
    assert wakeup.error == "heartbeat.wakeOnDemand.disabled"
    assert runs == []


async def test_agent_duplicate_child_issue_create_does_not_queue_second_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, status="in_progress")
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Child Owner",
                role="engineer",
                status="idle",
            )
        )

    payload = {
        "title": "Duplicate delegated child",
        "status": "todo",
        "parentId": parent_id,
        "assigneeAgentId": agent_id,
    }
    headers = {
        "x-test-org-id": org_id,
        "x-test-agent-id": "agent-parent",
        "x-octopus-run-id": "run-parent",
    }
    first_code, first_body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json=payload,
        headers=headers,
    )
    second_code, second_body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json=payload,
        headers={**headers, "x-octopus-run-id": "run-parent-retry"},
    )

    assert first_code == 200
    assert second_code == 200
    assert second_body["id"] == first_body["id"]
    async with session_factory() as verify:
        runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(HeartbeatRun.agent_id == agent_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(runs) == 1


async def test_create_in_review_issue_queues_reviewer_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    reviewer_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=reviewer_id,
                org_id=org_id,
                name="Issue Reviewer",
                role="engineer",
                status="idle",
            )
        )

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={
            "title": "Ready for review",
            "status": "in_review",
            "reviewerAgentId": reviewer_id,
            "originKind": "manual",
        },
    )

    assert code == 200
    async with session_factory() as verify:
        wakeup = (
            await verify.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == reviewer_id
                )
            )
        ).scalar_one()
        run = (
            await verify.execute(
                select(HeartbeatRun).where(HeartbeatRun.wakeup_request_id == wakeup.id)
            )
        ).scalar_one()

    assert wakeup.source == "review"
    assert wakeup.reason == "issue_review_requested"
    assert wakeup.payload == {
        "issueId": body["id"],
        "mutation": "create_in_review",
    }
    assert run.context_snapshot is not None
    assert run.context_snapshot["role"] == "reviewer"


async def test_create_in_review_issue_requires_reviewer(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={
            "title": "Missing reviewer",
            "status": "in_review",
            "originKind": "manual",
        },
    )

    assert code == 422
    assert body["detail"] == "in_review requires reviewerAgentId or reviewerUserId"


async def test_create_issue_rejects_same_assignee_and_reviewer_agent(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={
            "title": "Self review should be rejected",
            "status": "todo",
            "assigneeAgentId": agent_id,
            "reviewerAgentId": agent_id,
            "originKind": "manual",
        },
    )

    assert code == 422
    assert body["detail"] == "reviewerAgentId must differ from assigneeAgentId"


async def test_create_in_review_issue_with_user_reviewer_does_not_queue_agent(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={
            "title": "Human review",
            "status": "in_review",
            "reviewerUserId": str(uuid.uuid4()),
            "originKind": "manual",
        },
    )

    assert code == 200
    assert body["status"] == "in_review"
    async with session_factory() as verify:
        wakeups = (await verify.execute(select(AgentWakeupRequest))).scalars().all()
    assert wakeups == []


async def test_update_issue_to_in_review_queues_reviewer_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    reviewer_id = str(uuid.uuid4())
    issue_id = await _seed_issue(session, org_id, status="todo")
    async with async_transaction(session):
        session.add(
            Agent(
                id=reviewer_id,
                org_id=org_id,
                name="Patch Reviewer",
                role="engineer",
                status="idle",
            )
        )

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"status": "in_review", "reviewerAgentId": reviewer_id},
    )

    assert code == 200
    assert body["status"] == "in_review"
    async with session_factory() as verify:
        wakeup = (
            await verify.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == reviewer_id
                )
            )
        ).scalar_one()
    assert wakeup.reason == "issue_review_requested"
    assert wakeup.payload == {
        "issueId": issue_id,
        "mutation": "status_to_in_review",
    }


async def test_update_issue_to_in_review_requires_reviewer(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id, status="todo")

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"status": "in_review"},
    )

    assert code == 422
    assert body["detail"] == "in_review requires reviewerAgentId or reviewerUserId"


async def test_update_issue_rejects_same_assignee_and_reviewer_agent(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    issue_id = await _seed_issue(
        session,
        org_id,
        status="todo",
        assignee_agent_id=agent_id,
    )

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"reviewerAgentId": agent_id},
    )

    assert code == 422
    assert body["detail"] == "reviewerAgentId must differ from assigneeAgentId"


async def test_update_in_review_issue_cannot_clear_last_reviewer(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id, status="in_review")
    async with async_transaction(session):
        issue = await session.get_one(Issue, issue_id)
        issue.reviewer_agent_id = str(uuid.uuid4())

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"reviewerAgentId": None},
    )

    assert code == 422
    assert body["detail"] == "in_review requires reviewerAgentId or reviewerUserId"


async def test_update_issue_to_in_review_dispatches_reviewer_run(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    reviewer_id = str(uuid.uuid4())
    issue_id = await _seed_issue(session, org_id, status="todo")
    async with async_transaction(session):
        session.add(
            Agent(
                id=reviewer_id,
                org_id=org_id,
                name="Dispatch Reviewer",
                role="engineer",
                status="idle",
            )
        )

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"status": "in_review", "reviewerAgentId": reviewer_id},
    )

    assert code == 200
    assert body["status"] == "in_review"
    tasks = list(getattr(app.state, "heartbeat_dispatch_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)
    async with session_factory() as verify:
        run = (
            await verify.execute(
                select(HeartbeatRun).where(HeartbeatRun.agent_id == reviewer_id)
            )
        ).scalar_one()
    assert run.run_purpose == "review"
    assert run.status != "queued"
    assert run.started_at is not None


async def test_backlog_issue_moved_to_todo_queues_assignee_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    assignee_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=assignee_id,
                org_id=org_id,
                name="Backlog Owner",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="backlog",
        assignee_agent_id=assignee_id,
    )

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"status": "todo"},
    )

    assert code == 200
    assert body["status"] == "todo"
    tasks = list(getattr(app.state, "heartbeat_dispatch_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)
    async with session_factory() as verify:
        wakeup = (
            await verify.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == assignee_id
                )
            )
        ).scalar_one()
        run = (
            await verify.execute(
                select(HeartbeatRun).where(HeartbeatRun.agent_id == assignee_id)
            )
        ).scalar_one()

    assert wakeup.source == "assignment"
    assert wakeup.reason == "issue_status_changed"
    assert wakeup.payload == {"issueId": issue_id, "mutation": "update"}
    assert run.status != "queued"
    assert run.invocation_source == "assignment"
    assert run.context_snapshot is not None
    assert run.context_snapshot["source"] == "issue.status_change"
    assert run.context_snapshot["wakeSource"] == "assignment"
    assert run.context_snapshot["wakeReason"] == "issue_status_changed"


async def test_review_returned_to_assignee_dispatches_changes_requested_run(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    assignee_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=assignee_id,
                org_id=org_id,
                name="Review Owner",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="in_review",
        assignee_agent_id=assignee_id,
    )

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"status": "in_progress"},
    )

    assert code == 200
    assert body["status"] == "in_progress"
    tasks = list(getattr(app.state, "heartbeat_dispatch_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)
    async with session_factory() as verify:
        wakeup = (
            await verify.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == assignee_id
                )
            )
        ).scalar_one()
        run = (
            await verify.execute(
                select(HeartbeatRun).where(HeartbeatRun.agent_id == assignee_id)
            )
        ).scalar_one()

    assert wakeup.source == "assignment"
    assert wakeup.reason == "issue_changes_requested"
    assert wakeup.payload == {
        "issueId": issue_id,
        "mutation": "review_changes_requested",
    }
    assert run.status != "queued"
    assert run.started_at is not None
    assert run.invocation_source == "assignment"
    assert run.context_snapshot is not None
    assert run.context_snapshot["source"] == "issue.review_changes_requested"
    assert run.context_snapshot["wakeReason"] == "issue_changes_requested"


async def test_update_issue_route_returns_200_and_updates(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id, title="Before", status="todo")

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"title": "After", "status": "in_progress"},
    )

    assert code == 200
    assert body["id"] == issue_id
    assert body["title"] == "After"
    assert body["status"] == "in_progress"


async def test_agent_cannot_change_another_agents_issue_status(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(
        session,
        org_id,
        title="Parent task",
        status="in_progress",
        assignee_agent_id="parent-agent",
    )

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"status": "blocked"},
        headers={
            "x-test-org-id": org_id,
            "x-test-agent-id": "child-agent",
        },
    )

    assert code == 403
    assert body["detail"] == "Only the assigned Agent can change issue status"
    row = await session.get_one(Issue, issue_id)
    await session.refresh(row)
    assert row.status == "in_progress"


async def test_issue_heartbeat_context_route_returns_compact_issue_context(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(
        session,
        org_id,
        title="Context task",
        status="todo",
        assignee_agent_id="agent-context",
    )

    code, body = await _request(
        app,
        "GET",
        f"/api/issues/{issue_id}/heartbeat-context",
    )

    assert code == 200
    assert body["issue"] == {
        "id": issue_id,
        "identifier": None,
        "title": "Context task",
        "description": None,
        "status": "todo",
        "priority": "medium",
        "projectId": None,
        "goalId": None,
        "parentId": None,
        "assigneeAgentId": "agent-context",
        "assigneeUserId": None,
        "updatedAt": body["issue"]["updatedAt"],
    }
    assert body["ancestors"] == []
    assert body["project"] is None
    assert body["goal"] is None
    assert body["commentCursor"] is None
    assert body["wakeComment"] is None


async def test_issue_checkout_route_atomically_claims_issue_for_agent(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id, title="Checkout task", status="todo")
    agent_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Checkout Agent",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=agent_id,
                status="running",
                invocation_source="assignment",
                trigger_detail="system",
                context_snapshot={"issueId": issue_id},
            )
        )

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/checkout",
        json={"agentId": agent_id, "expectedStatuses": ["todo"]},
    )

    assert code == 200
    assert body["id"] == issue_id
    assert body["status"] == "in_progress"
    assert body["assigneeAgentId"] == agent_id
    assert body["checkoutRunId"] is None
    assert body["executionRunId"] is None
    tasks = list(getattr(app.state, "heartbeat_dispatch_tasks", set()))
    if tasks:
        await asyncio.gather(*tasks)
    async with session_factory() as verify:
        row = await verify.get(Issue, issue_id)
        runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(HeartbeatRun.agent_id == agent_id)
                )
            )
            .scalars()
            .all()
        )
        assert row is not None
        assert row.status == "in_progress"
        assert row.assignee_agent_id == agent_id
    assert any(run.status in {"running", "succeeded", "failed"} for run in runs)

    conflict_code, conflict = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/checkout",
        json={"agentId": agent_id, "expectedStatuses": ["todo"]},
    )

    assert conflict_code == 409
    assert "checkout conflict" in conflict["detail"].lower()


async def test_agent_checkout_adopts_current_run_without_creating_another_run(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    issue_id = await _seed_issue(
        session,
        org_id,
        title="Adopt current run",
        status="todo",
        assignee_agent_id=agent_id,
    )
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Current Run Agent",
                role="engineer",
                status="working",
            )
        )
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=agent_id,
                status="running",
                invocation_source="timer",
                trigger_detail="scheduled",
                context_snapshot={},
            )
        )

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/checkout",
        json={"agentId": agent_id, "expectedStatuses": ["todo"]},
        headers={
            "x-test-agent-id": agent_id,
            "x-test-org-id": org_id,
            "x-test-run-id": run_id,
        },
    )

    assert code == 200
    assert body["status"] == "in_progress"
    assert body["checkoutRunId"] == run_id
    assert body["executionRunId"] == run_id
    async with session_factory() as verify:
        runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(HeartbeatRun.agent_id == agent_id)
                )
            )
            .scalars()
            .all()
        )
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [run.id for run in runs] == [run_id]
    assert wakeups == []


async def test_issue_execute_route_queues_assigned_issue_idempotently(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Issue Executor",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        title="Executable task",
        status="todo",
        assignee_agent_id=agent_id,
    )

    code, run = await _request(app, "POST", f"/api/issues/{issue_id}/execute")
    repeat_code, repeat = await _request(app, "POST", f"/api/issues/{issue_id}/execute")

    assert code == 202
    assert run["status"] == "queued"
    assert run["agentId"] == agent_id
    assert run["issueId"] == issue_id
    assert run["invocationSource"] == "assignment"
    assert repeat_code == 200
    assert repeat["id"] == run["id"]
    async with session_factory() as verify:
        rows = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(
                        HeartbeatRun.agent_id == agent_id,
                        HeartbeatRun.context_snapshot["issueId"].as_string()
                        == issue_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        activity_rows = (
            (
                await verify.execute(
                    select(ActivityLog).where(
                        ActivityLog.org_id == org_id,
                        ActivityLog.entity_type == "issue",
                        ActivityLog.entity_id == issue_id,
                        ActivityLog.run_id == run["id"],
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(rows) == 1
    assert len(activity_rows) == 1
    assert activity_rows[0].action == "issue.executed"
    assert activity_rows[0].details is not None
    assert activity_rows[0].details["runId"] == run["id"]
    assert activity_rows[0].details["agentId"] == agent_id


async def test_agent_cannot_execute_issue_to_create_run(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="No Direct Execute",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        title="System scheduled only",
        status="todo",
        assignee_agent_id=agent_id,
    )

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/execute",
        headers={"x-test-agent-id": agent_id, "x-test-org-id": org_id},
    )

    assert code == 403
    assert body["detail"] == ("Agent cannot create Runs directly; use the current Run")


async def test_issue_execute_route_rejects_completed_issue(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Terminal Executor",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        title="Finished task",
        status="done",
        assignee_agent_id=agent_id,
    )

    code, body = await _request(app, "POST", f"/api/issues/{issue_id}/execute")

    assert code == 409
    assert "Reopen the issue before execution" in body["detail"]
    async with session_factory() as verify:
        runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(
                        HeartbeatRun.context_snapshot["issueId"].as_string()
                        == issue_id,
                    )
                )
            )
            .scalars()
            .all()
        )
    assert runs == []


async def test_issue_execute_route_retries_after_terminal_execution_run(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    old_run_id = str(uuid.uuid4())
    old_wakeup_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Retry Executor",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            HeartbeatRun(
                id=old_run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="assignment",
                trigger_detail="system",
                status="failed",
                error="Process lost -- child pid 31740 is no longer running",
                error_code="process_lost",
                context_snapshot={"issueId": issue_id, "wakeReason": "issue_execute"},
            )
        )
        session.add(
            AgentWakeupRequest(
                id=old_wakeup_id,
                org_id=org_id,
                agent_id=agent_id,
                source="assignment",
                trigger_detail="system",
                reason="issue_execute",
                payload={"issueId": issue_id, "mutation": "execute"},
                status="failed",
                run_id=old_run_id,
                idempotency_key=f"issue:{issue_id}:execute",
                error="Run interrupted before server recovery",
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Retry executable task",
                status="in_progress",
                priority="medium",
                assignee_agent_id=agent_id,
                checkout_run_id=old_run_id,
                execution_run_id=old_run_id,
            )
        )

    code, run = await _request(app, "POST", f"/api/issues/{issue_id}/execute")

    assert code == 202
    assert run["id"] != old_run_id
    assert run["status"] == "queued"
    assert run["issueId"] == issue_id
    async with session_factory() as verify:
        issue = await verify.get(Issue, issue_id)
        new_wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id,
                        AgentWakeupRequest.reason == "issue_execute",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert issue is not None
    assert issue.execution_run_id == run["id"]
    assert issue.checkout_run_id == run["id"]
    assert {wakeup.run_id for wakeup in new_wakeups} == {old_run_id, run["id"]}


async def test_issue_execute_route_creates_new_run_after_completed_execution(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    old_run_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Repeat Executor",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            HeartbeatRun(
                id=old_run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={"issueId": issue_id, "wakeReason": "issue_execute"},
            )
        )
        session.add(
            AgentWakeupRequest(
                org_id=org_id,
                agent_id=agent_id,
                source="assignment",
                trigger_detail="system",
                reason="issue_execute",
                payload={"issueId": issue_id, "mutation": "execute"},
                status="completed",
                run_id=old_run_id,
                idempotency_key=f"issue:{issue_id}:execute",
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Repeat executable task",
                status="in_progress",
                priority="medium",
                assignee_agent_id=agent_id,
            )
        )

    code, run = await _request(app, "POST", f"/api/issues/{issue_id}/execute")

    assert code == 202
    assert run["id"] != old_run_id
    assert run["status"] == "queued"
    async with session_factory() as verify:
        issue = await verify.get(Issue, issue_id)
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id,
                        AgentWakeupRequest.reason == "issue_execute",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert issue is not None
    assert issue.execution_run_id == run["id"]
    assert issue.checkout_run_id == run["id"]
    assert {wakeup.run_id for wakeup in wakeups} == {old_run_id, run["id"]}


async def test_issue_execute_route_reports_paused_assignee_deferred(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Paused Executor",
                role="engineer",
                status="paused",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        title="Deferred executable task",
        status="todo",
        assignee_agent_id=agent_id,
    )

    code, body = await _request(app, "POST", f"/api/issues/{issue_id}/execute")

    assert code == 202
    assert body == {
        "status": "deferred_agent_paused",
        "detail": (
            "Issue execution was deferred because the assignee agent is paused. "
            "Resume the agent to continue."
        ),
    }
    async with session_factory() as verify:
        wakeup = (
            await verify.execute(
                select(AgentWakeupRequest).where(
                    AgentWakeupRequest.agent_id == agent_id,
                    AgentWakeupRequest.reason == "issue_execute",
                )
            )
        ).scalar_one()
    assert wakeup.status == "deferred_agent_paused"


async def test_agent_cannot_mark_issue_done_without_checkout_ownership(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    owner_id = str(uuid.uuid4())
    other_id = str(uuid.uuid4())
    issue_id = await _seed_issue(
        session,
        org_id,
        title="Owned task",
        status="in_progress",
        assignee_agent_id=owner_id,
    )
    async with async_transaction(session):
        session.add_all(
            [
                Agent(id=owner_id, org_id=org_id, name="Owner", role="engineer"),
                Agent(id=other_id, org_id=org_id, name="Other", role="engineer"),
            ]
        )

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"status": "done"},
        headers={"x-test-agent-id": other_id, "x-test-org-id": org_id},
    )

    assert code == 403
    assert "checkout owner" in body["detail"].lower()


async def test_issue_comment_routes_create_and_list(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id)

    create_code, create_body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={"body": "First route comment"},
    )
    assert create_code == 200
    assert create_body["body"] == "First route comment"

    list_code, list_body = await _request(
        app, "GET", f"/api/issues/{issue_id}/comments"
    )
    assert list_code == 200
    assert len(list_body) == 1
    assert list_body[0]["body"] == "First route comment"

    async with session_factory() as verify:
        result = await verify.execute(
            select(IssueComment).where(IssueComment.issue_id == issue_id)
        )
        rows = result.scalars().all()
    assert len(rows) == 1


async def test_plain_issue_comment_queues_assignee_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Comment Assignee",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="in_progress",
        assignee_agent_id=agent_id,
    )

    create_code, create_body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={"body": "请根据反馈更新状态"},
    )

    assert create_code == 200
    async with session_factory() as verify:
        wakeup = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id,
                        AgentWakeupRequest.reason == "issue_comment_added",
                    )
                )
            )
            .scalars()
            .one()
        )
        run = (
            await verify.execute(
                select(HeartbeatRun).where(HeartbeatRun.wakeup_request_id == wakeup.id)
            )
        ).scalar_one()
    assert wakeup.source == "assignment"
    assert wakeup.payload == {
        "issueId": issue_id,
        "mutation": "comment",
        "commentId": create_body["id"],
    }
    assert run.context_snapshot is not None
    assert run.context_snapshot["commentId"] == create_body["id"]
    assert run.context_snapshot["wakeReason"] == "issue_comment_added"


async def test_issue_comment_on_closed_issue_does_not_queue_assignee_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Closed Comment Assignee",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="done",
        assignee_agent_id=agent_id,
    )

    create_code, create_body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={"body": "补充归档说明，不要重新执行"},
    )

    assert create_code == 200
    assert create_body["body"] == "补充归档说明，不要重新执行"
    async with session_factory() as verify:
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id,
                        AgentWakeupRequest.reason == "issue_comment_added",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert wakeups == []


async def test_user_mention_reopens_done_issue_and_queues_assignee_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="closed-owner",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="done",
        assignee_agent_id=agent_id,
    )
    async with async_transaction(session):
        issue = await session.get(Issue, issue_id)
        assert issue is not None
        issue.completed_at = datetime.now(UTC)

    create_code, create_body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={"body": "@closed-owner 请继续补充旅游计划"},
    )

    assert create_code == 200
    async with session_factory() as verify:
        issue = await verify.get(Issue, issue_id)
        wakeup = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id,
                        AgentWakeupRequest.reason == "issue_comment_mentioned",
                    )
                )
            )
            .scalars()
            .one()
        )
        run = (
            await verify.execute(
                select(HeartbeatRun).where(HeartbeatRun.wakeup_request_id == wakeup.id)
            )
        ).scalar_one()
    assert issue is not None
    assert issue.status != "done"
    assert issue.completed_at is None
    assert wakeup.source == "on_demand"
    assert wakeup.payload == {
        "issueId": issue_id,
        "mutation": "comment_mention",
        "commentId": create_body["id"],
    }
    assert run.context_snapshot is not None
    assert run.context_snapshot["commentBody"] == ("@closed-owner 请继续补充旅游计划")


async def test_user_mention_does_not_reopen_cancelled_issue(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="cancelled-owner",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="cancelled",
        assignee_agent_id=agent_id,
    )

    code, _ = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={"body": "@cancelled-owner 请继续执行"},
    )

    assert code == 200
    async with session_factory() as verify:
        issue = await verify.get(Issue, issue_id)
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert issue is not None
    assert issue.status == "cancelled"
    assert wakeups == []


async def test_agent_mention_cannot_reopen_its_done_issue(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="agent-closed-owner",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="done",
        assignee_agent_id=agent_id,
    )

    code, _ = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={"body": "@agent-closed-owner 再执行一次"},
        headers={"x-test-agent-id": agent_id, "x-test-org-id": org_id},
    )

    assert code == 200
    async with session_factory() as verify:
        issue = await verify.get(Issue, issue_id)
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert issue is not None
    assert issue.status == "done"
    assert wakeups == []


async def test_issue_comment_keeps_control_with_assignee_despite_other_mention(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    assignee_agent_id = str(uuid.uuid4())
    mentioned_agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add_all(
            [
                Agent(
                    id=assignee_agent_id,
                    org_id=org_id,
                    name="Comment Assignee",
                    role="engineer",
                    status="idle",
                ),
                Agent(
                    id=mentioned_agent_id,
                    org_id=org_id,
                    name="reviewer-1",
                    role="engineer",
                    status="idle",
                ),
            ]
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="in_progress",
        assignee_agent_id=assignee_agent_id,
    )

    create_code, create_body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={"body": "请 @reviewer-1 看一下这个边界情况"},
    )

    assert create_code == 200
    async with session_factory() as verify:
        mentioned_wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == mentioned_agent_id,
                        AgentWakeupRequest.reason == "issue_comment_mentioned",
                    )
                )
            )
            .scalars()
            .all()
        )
        assignee_wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == assignee_agent_id,
                        AgentWakeupRequest.reason == "issue_comment_added",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert mentioned_wakeups == []
    assert len(assignee_wakeups) == 1
    assert assignee_wakeups[0].source == "assignment"
    assert assignee_wakeups[0].payload == {
        "issueId": issue_id,
        "mutation": "comment",
        "commentId": create_body["id"],
    }


async def test_issue_comment_mentioning_assignee_queues_assignee_wakeup_once(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    assignee_agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=assignee_agent_id,
                org_id=org_id,
                name="owner-1",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="in_progress",
        assignee_agent_id=assignee_agent_id,
    )

    create_code, create_body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={"body": "@owner-1 请根据反馈继续处理"},
    )

    assert create_code == 200
    async with session_factory() as verify:
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == assignee_agent_id
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(wakeups) == 1
    assert wakeups[0].reason == "issue_comment_added"
    assert wakeups[0].payload == {
        "issueId": issue_id,
        "mutation": "comment",
        "commentId": create_body["id"],
    }


async def test_issue_comment_request_replay_reuses_comment_and_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="owner-replay",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="in_progress",
        assignee_agent_id=agent_id,
    )
    payload = {
        "body": "@owner-replay 请继续",
        "requestId": "comment-request-replay",
    }

    first_code, first_body = await _request(
        app, "POST", f"/api/issues/{issue_id}/comments", json=payload
    )
    second_code, second_body = await _request(
        app, "POST", f"/api/issues/{issue_id}/comments", json=payload
    )

    assert first_code == second_code == 200
    assert first_body["id"] == second_body["id"]
    async with session_factory() as verify:
        comments = (
            (
                await verify.execute(
                    select(IssueComment).where(IssueComment.issue_id == issue_id)
                )
            )
            .scalars()
            .all()
        )
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(comments) == 1
    assert comments[0].request_id == "comment-request-replay"
    assert len(wakeups) == 1


async def test_issue_comment_merges_into_deferred_issue_execution(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="owner-deferred",
                role="engineer",
                status="idle",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="todo",
        assignee_agent_id=agent_id,
    )
    async with async_transaction(session):
        session.add(
            AgentWakeupRequest(
                org_id=org_id,
                agent_id=agent_id,
                source="assignment",
                reason="issue_assigned",
                status="deferred_issue_execution",
                payload={
                    "issueId": issue_id,
                    "__releaseAfterParentRunId": "parent-run-1",
                    "__deferredContextSnapshot": {"issueId": issue_id},
                },
            )
        )

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={
            "body": "补充执行说明",
            "requestId": "deferred-comment-1",
        },
    )

    assert code == 200
    async with session_factory() as verify:
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id
                    )
                )
            )
            .scalars()
            .all()
        )
        runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(HeartbeatRun.agent_id == agent_id)
                )
            )
            .scalars()
            .all()
        )
    assert len(wakeups) == 1
    assert wakeups[0].status == "deferred_issue_execution"
    assert wakeups[0].coalesced_count == 1
    assert wakeups[0].payload is not None
    context = wakeups[0].payload["__deferredContextSnapshot"]
    assert context["commentId"] == body["id"]
    assert context["commentIds"] == [body["id"]]
    assert runs == []


async def test_issue_comments_during_active_run_coalesce_into_one_followup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    agent_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="active-owner",
                role="engineer",
                status="working",
            )
        )
    issue_id = await _seed_issue(
        session,
        org_id,
        status="in_progress",
        assignee_agent_id=agent_id,
    )
    async with async_transaction(session):
        issue = await session.get(Issue, issue_id)
        assert issue is not None
        issue.checkout_run_id = run_id
        issue.execution_run_id = run_id
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="assignment",
                status="running",
                context_snapshot={"issueId": issue_id},
            )
        )

    first_code, first_body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={"body": "第一次调整", "requestId": "active-comment-1"},
    )
    second_code, second_body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/comments",
        json={"body": "第二次调整", "requestId": "active-comment-2"},
    )

    assert first_code == second_code == 200
    async with session_factory() as verify:
        runs = (
            (
                await verify.execute(
                    select(HeartbeatRun).where(HeartbeatRun.agent_id == agent_id)
                )
            )
            .scalars()
            .all()
        )
        wakeups = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == agent_id,
                        AgentWakeupRequest.status == "deferred_issue_execution",
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [run.id for run in runs] == [run_id]
    assert len(wakeups) == 1
    assert wakeups[0].coalesced_count == 1
    assert wakeups[0].payload is not None
    context = wakeups[0].payload["__deferredContextSnapshot"]
    assert context["commentIds"] == [first_body["id"], second_body["id"]]


async def test_review_decision_route_applies_status_mapping(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id, status="in_review")

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/review-decision",
        json={"decision": "approve"},
    )

    assert code == 200
    assert body["id"] == issue_id
    assert body["status"] == "done"


async def test_review_decision_skips_queued_reviewer_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    reviewer_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    wakeup_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=reviewer_id,
                org_id=org_id,
                name="Queued Reviewer",
                role="engineer",
                status="idle",
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Queued review",
                status="in_review",
                priority="medium",
                reviewer_agent_id=reviewer_id,
            )
        )
        session.add(
            AgentWakeupRequest(
                id=wakeup_id,
                org_id=org_id,
                agent_id=reviewer_id,
                source="review",
                trigger_detail="system",
                reason="issue_review_requested",
                payload={"issueId": issue_id, "mutation": "status_to_in_review"},
                status="queued",
                run_id=run_id,
                idempotency_key=f"issue:{issue_id}:review:status_to_in_review",
            )
        )
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=reviewer_id,
                invocation_source="review",
                trigger_detail="system",
                status="queued",
                wakeup_request_id=wakeup_id,
                run_purpose="review",
                context_snapshot={
                    "issueId": issue_id,
                    "wakeSource": "review",
                    "wakeReason": "issue_review_requested",
                    "role": "reviewer",
                },
            )
        )

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/review-decision",
        json={"decision": "approve"},
    )

    assert code == 200
    assert body["status"] == "done"
    async with session_factory() as verify:
        wakeup = await verify.get(AgentWakeupRequest, wakeup_id)
        run = await verify.get(HeartbeatRun, run_id)
    assert wakeup is not None
    assert wakeup.status == "skipped"
    assert wakeup.finished_at is not None
    assert run is not None
    assert run.status == "cancelled"
    assert run.finished_at is not None
    assert run.error == "review already resolved"


async def test_review_decision_cancels_running_reviewer_wakeup(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    reviewer_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    wakeup_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Agent(
                id=reviewer_id,
                org_id=org_id,
                name="Running Reviewer",
                role="engineer",
                status="running",
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Running review",
                status="in_review",
                priority="medium",
                reviewer_agent_id=reviewer_id,
            )
        )
        session.add(
            AgentWakeupRequest(
                id=wakeup_id,
                org_id=org_id,
                agent_id=reviewer_id,
                source="review",
                trigger_detail="system",
                reason="issue_review_requested",
                payload={"issueId": issue_id, "mutation": "status_to_in_review"},
                status="claimed",
                run_id=run_id,
                claimed_at=datetime.now(UTC),
                idempotency_key=f"issue:{issue_id}:review:status_to_in_review",
            )
        )
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=reviewer_id,
                invocation_source="review",
                trigger_detail="system",
                status="running",
                wakeup_request_id=wakeup_id,
                run_purpose="review",
                started_at=datetime.now(UTC),
                context_snapshot={
                    "issueId": issue_id,
                    "wakeSource": "review",
                    "wakeReason": "issue_review_requested",
                    "role": "reviewer",
                },
            )
        )

    code, body = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/review-decision",
        json={"decision": "approve"},
    )

    assert code == 200
    assert body["status"] == "done"
    async with session_factory() as verify:
        wakeup = await verify.get(AgentWakeupRequest, wakeup_id)
        run = await verify.get(HeartbeatRun, run_id)
        reviewer = await verify.get(Agent, reviewer_id)
    assert wakeup is not None
    assert wakeup.status == "cancelled"
    assert wakeup.finished_at is not None
    assert wakeup.error == "review already resolved"
    assert run is not None
    assert run.status == "cancelled"
    assert run.finished_at is not None
    assert run.error == "review already resolved"
    assert run.error_code == "cancelled"
    assert reviewer is not None
    assert reviewer.status == "idle"


async def test_org_issue_list_supports_step8_filters(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    await _seed_issue(
        session,
        org_id,
        title="Match route filter",
        status="todo",
        project_id="proj-1",
        goal_id="goal-1",
        assignee_agent_id="agent-1",
        origin_kind="manual",
        origin_id="origin-1",
    )
    await _seed_issue(
        session,
        org_id,
        title="Skip route filter",
        status="done",
        project_id="proj-2",
        goal_id="goal-2",
        assignee_agent_id="agent-2",
        origin_kind="automation_execution",
        origin_id="origin-2",
    )

    code, body = await _request(
        app,
        "GET",
        "/api/orgs/"
        f"{org_id}/issues?status=todo&assigneeAgentId=agent-1&projectId=proj-1"
        "&goalId=goal-1&originKind=manual&originId=origin-1",
    )

    assert code == 200
    assert len(body) == 1
    assert body[0]["title"] == "Match route filter"
    assert body[0]["projectId"] == "proj-1"
    assert body[0]["goalId"] == "goal-1"
    assert body[0]["originKind"] == "manual"
    assert body[0]["originId"] == "origin-1"


async def test_issue_parent_filter_and_depth_are_applied(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)

    parent_code, parent = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={"title": "Parent issue", "status": "todo", "originKind": "manual"},
    )
    child_code, child = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={
            "title": "Child issue",
            "status": "todo",
            "originKind": "manual",
            "parentId": parent["id"],
        },
    )

    assert parent_code == 200
    assert child_code == 200
    assert child["parentId"] == parent["id"]
    assert child["requestDepth"] == 1

    code, body = await _request(
        app, "GET", f"/api/orgs/{org_id}/issues?parentId={parent['id']}"
    )

    assert code == 200
    assert [row["id"] for row in body] == [child["id"]]


async def test_issue_create_rejects_parent_from_another_org(
    app: FastAPI, session: AsyncSession
) -> None:
    parent_org_id = await _seed_org(session)
    child_org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, parent_org_id, title="External parent")

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{child_org_id}/issues",
        json={
            "title": "Invalid child",
            "status": "todo",
            "originKind": "manual",
            "parentId": parent_id,
        },
    )

    assert code == 422
    assert "Parent issue not found" in body["detail"]


async def test_issue_update_rejects_parent_cycle(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    parent_code, parent = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={"title": "Parent", "status": "todo", "originKind": "manual"},
    )
    child_code, child = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={
            "title": "Child",
            "status": "todo",
            "originKind": "manual",
            "parentId": parent["id"],
        },
    )
    assert parent_code == 200
    assert child_code == 200

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{parent['id']}",
        json={"parentId": child["id"]},
    )

    assert code == 422
    assert "cycle" in body["detail"].lower()


async def test_parent_done_rejects_open_children(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, status="todo")
    child_a_id = await _seed_issue(session, org_id, title="Child A", status="todo")
    child_b_id = await _seed_issue(session, org_id, title="Child B", status="blocked")
    child_cancelled_id = await _seed_issue(
        session, org_id, title="Child Cancelled", status="cancelled"
    )
    done_child_id = await _seed_issue(session, org_id, title="Child C", status="done")
    async with async_transaction(session):
        for issue_id in (child_a_id, child_b_id, child_cancelled_id, done_child_id):
            row = await session.get(Issue, issue_id)
            assert row is not None
            row.parent_id = parent_id

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{parent_id}",
        json={"status": "done"},
    )

    assert code == 422
    assert "child issues" in body["detail"]
    child_code, children = await _request(
        app, "GET", f"/api/orgs/{org_id}/issues?parentId={parent_id}"
    )
    assert child_code == 200
    assert {child["id"]: child["status"] for child in children} == {
        child_a_id: "todo",
        child_b_id: "blocked",
        child_cancelled_id: "cancelled",
        done_child_id: "done",
    }


async def test_parent_done_allows_accepted_cancelled_child(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, status="todo")
    child_id = await _seed_issue(
        session, org_id, title="Cancelled child", status="cancelled"
    )
    async with async_transaction(session):
        child = await session.get(Issue, child_id)
        assert child is not None
        child.parent_id = parent_id

    accept_code, accept_body = await _request(
        app,
        "POST",
        f"/api/issues/{parent_id}/accept-incomplete",
        json={
            "childIssueId": child_id,
            "reason": "用户确认取消该子任务，不影响父任务交付",
        },
    )
    assert accept_code == 200
    assert accept_body["status"] == "in_progress"

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{parent_id}",
        json={"status": "done"},
    )

    assert code == 200
    assert body["status"] == "done"


async def test_agent_cannot_accept_incomplete_child_work(app: FastAPI) -> None:
    code, body = await _request(
        app,
        "POST",
        "/api/issues/parent-1/accept-incomplete",
        json={"childIssueId": "child-1", "reason": "skip"},
        headers={
            "x-test-agent-id": "agent-1",
            "x-test-org-id": "org-1",
            "x-test-run-id": "run-1",
        },
    )

    assert code == 403
    assert "human operator" in body["detail"]


async def test_issue_detail_returns_association_fields_and_nulls(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    associated_issue_id = await _seed_issue(
        session,
        org_id,
        title="Associated detail",
        project_id="proj-9",
        goal_id="goal-9",
        assignee_agent_id="agent-9",
        origin_kind="manual",
        origin_id="origin-9",
    )
    plain_issue_id = await _seed_issue(
        session,
        org_id,
        title="Plain detail",
        project_id=None,
        goal_id=None,
        assignee_agent_id=None,
        origin_kind="manual",
        origin_id=None,
    )

    associated_code, associated_body = await _request(
        app, "GET", f"/api/issues/{associated_issue_id}"
    )
    assert associated_code == 200
    assert associated_body["projectId"] == "proj-9"
    assert associated_body["goalId"] == "goal-9"
    assert associated_body["assigneeAgentId"] == "agent-9"
    assert associated_body["originKind"] == "manual"
    assert associated_body["originId"] == "origin-9"

    plain_code, plain_body = await _request(app, "GET", f"/api/issues/{plain_issue_id}")
    assert plain_code == 200
    assert plain_body["projectId"] is None
    assert plain_body["goalId"] is None
    assert plain_body["assigneeAgentId"] is None
    assert plain_body["originId"] is None


async def test_update_issue_route_rejects_unknown_field(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id)

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{issue_id}",
        json={"workspaceConfig": {}},
    )

    assert code == 422
    assert "Unsupported field" in body["detail"]


async def test_review_decision_route_writes_activity(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id, status="in_review")
    async with async_transaction(session):
        issue = await session.get_one(Issue, issue_id)
        issue.reviewer_user_id = str(uuid.uuid4())

    code, _ = await _request(
        app,
        "POST",
        f"/api/issues/{issue_id}/review-decision",
        json={"decision": "needs_followup"},
    )
    assert code == 200

    async with session_factory() as verify:
        result = await verify.execute(
            select(ActivityLog)
            .where(ActivityLog.org_id == org_id)
            .order_by(ActivityLog.created_at, ActivityLog.id)
        )
        rows = result.scalars().all()
    assert [row.action for row in rows] == [
        "issue.review_decision_recorded",
        "issue.human_intervention_required",
    ]
