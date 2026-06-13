from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

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

from packages.database.clients import async_transaction
from packages.database.schema import (
    ActivityLog,
    Agent,
    AgentWakeupRequest,
    Base,
    HeartbeatRun,
    HeartbeatRunEvent,
    Issue,
    IssueComment,
    Organization,
)
from server.app import app as fastapi_app


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
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
def app(session_factory: async_sessionmaker[AsyncSession]) -> Iterator[FastAPI]:
    original_settings = fastapi_app.state.settings
    fastapi_app.state.session_factory = session_factory
    fastapi_app.state.settings = replace(original_settings, local_trusted=True)
    try:
        yield fastapi_app
    finally:
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


async def test_review_returned_to_assignee_queues_changes_requested_wakeup(
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
    assert run.status == "queued"
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


async def test_issue_comment_queues_assignee_wakeup(
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


async def test_issue_comment_queues_mentioned_agent_wakeup(
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
        assignee_wakeup = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == assignee_agent_id,
                        AgentWakeupRequest.reason == "issue_comment_added",
                    )
                )
            )
            .scalars()
            .one()
        )
        mentioned_wakeup = (
            (
                await verify.execute(
                    select(AgentWakeupRequest).where(
                        AgentWakeupRequest.agent_id == mentioned_agent_id,
                        AgentWakeupRequest.reason == "issue_comment_mentioned",
                    )
                )
            )
            .scalars()
            .one()
        )
        run = (
            await verify.execute(
                select(HeartbeatRun).where(
                    HeartbeatRun.wakeup_request_id == mentioned_wakeup.id
                )
            )
        ).scalar_one()

    assert assignee_wakeup.payload == {
        "issueId": issue_id,
        "mutation": "comment",
        "commentId": create_body["id"],
    }
    assert mentioned_wakeup.source == "on_demand"
    assert mentioned_wakeup.payload == {
        "issueId": issue_id,
        "mutation": "comment_mention",
        "commentId": create_body["id"],
    }
    assert run.context_snapshot is not None
    assert run.context_snapshot["wakeSource"] == "mention"
    assert run.context_snapshot["wakeReason"] == "issue_comment_mentioned"
    assert run.context_snapshot["commentId"] == create_body["id"]


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


async def test_parent_done_auto_closes_open_children(
    app: FastAPI,
    session: AsyncSession,
) -> None:
    org_id = await _seed_org(session)
    parent_id = await _seed_issue(session, org_id, status="todo")
    child_a_id = await _seed_issue(session, org_id, title="Child A", status="todo")
    child_b_id = await _seed_issue(session, org_id, title="Child B", status="blocked")
    done_child_id = await _seed_issue(session, org_id, title="Child C", status="done")
    async with async_transaction(session):
        for issue_id in (child_a_id, child_b_id, done_child_id):
            row = await session.get(Issue, issue_id)
            assert row is not None
            row.parent_id = parent_id

    code, body = await _request(
        app,
        "PATCH",
        f"/api/issues/{parent_id}",
        json={"status": "done"},
    )

    assert code == 200
    assert body["status"] == "done"
    child_code, children = await _request(
        app, "GET", f"/api/orgs/{org_id}/issues?parentId={parent_id}"
    )
    assert child_code == 200
    assert {child["id"]: child["status"] for child in children} == {
        child_a_id: "done",
        child_b_id: "done",
        done_child_id: "done",
    }


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
