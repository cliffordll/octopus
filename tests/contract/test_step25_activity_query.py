from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.queries.activity_log import insert_activity_log
from packages.database.schema import (
    Agent,
    Base,
    ChatContextLink,
    ChatConversation,
    HeartbeatRun,
    Issue,
    Organization,
)
from server.app import create_app


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker]]:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory
    try:
        yield application, factory
    finally:
        await engine.dispose()


def test_step25_activity_contract_exposes_paths() -> None:
    from packages.shared.api_paths import activity

    assert activity.ORG_ACTIVITY_PATH == "/api/orgs/{orgId}/activity"
    assert activity.ISSUE_ACTIVITY_PATH == "/api/issues/{id}/activity"
    assert activity.ISSUE_RUNS_PATH == "/api/issues/{id}/runs"
    assert activity.HEARTBEAT_RUN_ISSUES_PATH == "/api/heartbeat-runs/{runId}/issues"


async def test_org_activity_filters_and_redacts_details(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id = await _seed_org_and_agent(factory)

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/activity",
        json={
            "actorType": "agent",
            "actorId": agent_id,
            "action": "agent.token_tested",
            "entityType": "agent",
            "entityId": agent_id,
            "agentId": agent_id,
            "details": {
                "apiKey": "sk-live",
                "nested": {"authorization": "Bearer secret"},
                "safe": "visible",
            },
        },
    )
    list_code, events = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/activity?action=agent.token_tested&agentId={agent_id}",
    )

    assert create_code == 201
    assert created["details"]["apiKey"] == "[REDACTED]"
    assert created["details"]["nested"]["authorization"] == "[REDACTED]"
    assert created["details"]["safe"] == "visible"
    assert list_code == 200
    assert [event["id"] for event in events] == [created["id"]]
    assert events[0]["details"]["apiKey"] == "[REDACTED]"


async def test_issue_activity_merges_relevant_chat_events_and_hides_noise(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id = await _seed_org_and_agent(factory)
    issue_id = str(uuid.uuid4())
    chat_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Activity issue",
                status="todo",
                priority="medium",
                assignee_agent_id=agent_id,
                identifier="OCT-25",
            )
        )
        session.add(
            ChatConversation(
                id=chat_id,
                org_id=org_id,
                title="Issue chat",
            )
        )
        session.add(
            ChatContextLink(
                org_id=org_id,
                conversation_id=chat_id,
                entity_type="issue",
                entity_id=issue_id,
            )
        )
        await session.flush()
        await insert_activity_log(
            session,
            org_id=org_id,
            actor_type="agent",
            actor_id=agent_id,
            action="issue.updated",
            entity_type="issue",
            entity_id=issue_id,
            details={"description": "only noise"},
        )
        await insert_activity_log(
            session,
            org_id=org_id,
            actor_type="agent",
            actor_id=agent_id,
            action="issue.updated",
            entity_type="issue",
            entity_id=issue_id,
            details={"status": "in_progress"},
        )
        await insert_activity_log(
            session,
            org_id=org_id,
            actor_type="user",
            actor_id="local-board",
            action="chat.created",
            entity_type="chat",
            entity_id=chat_id,
            details={"contextLinkCount": 1},
        )
        await session.commit()

    code, events = await _request(application, "GET", "/api/issues/OCT-25/activity")

    assert code == 200
    assert [event["action"] for event in events] == [
        "chat.created",
        "issue.updated",
    ]
    assert events[0]["details"]["conversationTitle"] == "Issue chat"


async def test_issue_runs_and_run_issues_include_activity_linked_runs(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id = await _seed_org_and_agent(factory)
    issue_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Linked issue",
                status="in_progress",
                priority="high",
                assignee_agent_id=agent_id,
            )
        )
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                result_json={"summary": "done"},
                context_snapshot={"source": "manual"},
            )
        )
        await session.flush()
        await insert_activity_log(
            session,
            org_id=org_id,
            actor_type="agent",
            actor_id=agent_id,
            action="issue.comment_added",
            entity_type="issue",
            entity_id=issue_id,
            agent_id=agent_id,
            run_id=run_id,
            details={"commentId": str(uuid.uuid4())},
        )
        await session.commit()

    runs_code, runs = await _request(application, "GET", f"/api/issues/{issue_id}/runs")
    issues_code, issues = await _request(
        application, "GET", f"/api/heartbeat-runs/{run_id}/issues"
    )

    assert runs_code == 200
    assert [run["runId"] for run in runs] == [run_id]
    assert runs[0]["summary"] == "done"
    assert issues_code == 200
    assert issues == [
        {
            "issueId": issue_id,
            "identifier": None,
            "title": "Linked issue",
            "status": "in_progress",
            "priority": "high",
        }
    ]


async def test_activity_routes_reject_cross_organization_access(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id = await _seed_org_and_agent(factory, key="allowed")
    other_org_id, other_agent_id = await _seed_org_and_agent(factory, key="other")
    run_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="on_demand",
                status="queued",
            )
        )
        await session.commit()

    headers = {"x-test-agent-id": other_agent_id, "x-test-org-id": other_org_id}
    org_code, _ = await _request(
        application, "GET", f"/api/orgs/{org_id}/activity", headers=headers
    )
    run_code, _ = await _request(
        application, "GET", f"/api/heartbeat-runs/{run_id}/issues", headers=headers
    )

    assert org_code == 403
    assert run_code == 403


async def _seed_org_and_agent(
    factory: async_sessionmaker, *, key: str = "step25"
) -> tuple[str, str]:
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                name=f"Step 25 {key}",
                url_key=f"step25-{key}-{uuid.uuid4().hex[:8]}",
                issue_prefix=f"S25{uuid.uuid4().hex[:4].upper()}",
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name=f"Step 25 agent {key}",
                role="engineer",
                status="idle",
            )
        )
        await session.commit()
    return org_id, agent_id


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json, headers=headers)
    return response.status_code, response.json()
