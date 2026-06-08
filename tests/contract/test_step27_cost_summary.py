from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import ActivityLog, Agent, Base, Organization, Project
from packages.database.schema import HeartbeatRun
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


async def _seed_org_agent_project(
    factory: async_sessionmaker,
    *,
    prefix: str,
) -> tuple[str, str, str]:
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"{prefix}-{uuid.uuid4().hex[:8]}",
                name=f"{prefix} Org",
                issue_prefix=f"{prefix[:2].upper()}{uuid.uuid4().hex[:4].upper()}",
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name=f"{prefix} Agent",
                workspace_key=f"{prefix}-agent",
                role="engineer",
                agent_runtime_type="codex_local",
                budget_monthly_cents=5000,
            )
        )
        session.add(
            Project(
                id=project_id,
                org_id=org_id,
                name=f"{prefix} Project",
                status="active",
            )
        )
        await session.commit()
    return org_id, agent_id, project_id


def test_step27_cost_api_paths_are_exported() -> None:
    from packages.shared.api_paths import costs

    assert costs.ORG_COST_EVENT_LIST_PATH == "/api/orgs/{orgId}/cost-events"
    assert costs.ORG_COST_SUMMARY_PATH == "/api/orgs/{orgId}/costs/summary"
    assert costs.ORG_COST_BY_AGENT_PATH == "/api/orgs/{orgId}/costs/by-agent"
    assert costs.ORG_COST_BY_PROVIDER_PATH == "/api/orgs/{orgId}/costs/by-provider"


async def test_cost_event_creation_records_activity_and_spend(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id, project_id = await _seed_org_agent_project(
        factory, prefix="cost"
    )

    code, event = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/cost-events",
        json={
            "agentId": agent_id,
            "projectId": project_id,
            "sourceType": "run",
            "sourceId": "run-1",
            "runtimeType": "codex_local",
            "provider": "openai",
            "model": "gpt-5",
            "biller": "openrouter",
            "costCents": 123,
            "inputTokens": 1000,
            "outputTokens": 200,
            "metadata": {"safe": "visible"},
            "occurredAt": "2026-06-08T12:00:00Z",
        },
    )

    assert code == 201
    assert event["orgId"] == org_id
    assert event["agentId"] == agent_id
    assert event["projectId"] == project_id
    assert event["costCents"] == 123
    assert event["provider"] == "openai"
    assert event["biller"] == "openrouter"

    async with factory() as session:
        org = await session.get(Organization, org_id)
        agent = await session.get(Agent, agent_id)
        actions = [
            row.action for row in (await session.execute(select(ActivityLog))).scalars()
        ]
    assert org is not None and org.spent_monthly_cents == 123
    assert agent is not None and agent.spent_monthly_cents == 123
    assert "cost.reported" in actions


async def test_cost_summary_groups_by_dimensions_and_filters_dates(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id, project_id = await _seed_org_agent_project(
        factory, prefix="sum"
    )
    for payload in [
        {
            "agentId": agent_id,
            "projectId": project_id,
            "sourceType": "run",
            "sourceId": "run-a",
            "provider": "openai",
            "model": "gpt-5",
            "biller": "openrouter",
            "costCents": 100,
            "occurredAt": "2026-06-01T00:00:00Z",
        },
        {
            "agentId": agent_id,
            "sourceType": "chat",
            "sourceId": "chat-a",
            "provider": "anthropic",
            "model": "claude",
            "biller": "anthropic",
            "costCents": 50,
            "occurredAt": "2026-05-01T00:00:00Z",
        },
    ]:
        code, _ = await _request(
            application, "POST", f"/api/orgs/{org_id}/cost-events", json=payload
        )
        assert code == 201

    query = "startTime=2026-06-01T00:00:00Z&endTime=2026-06-30T23:59:59Z"
    summary_code, summary = await _request(
        application, "GET", f"/api/orgs/{org_id}/costs/summary?{query}"
    )
    agent_code, by_agent = await _request(
        application, "GET", f"/api/orgs/{org_id}/costs/by-agent?{query}"
    )
    provider_code, by_provider = await _request(
        application, "GET", f"/api/orgs/{org_id}/costs/by-provider?{query}"
    )
    biller_code, by_biller = await _request(
        application, "GET", f"/api/orgs/{org_id}/costs/by-biller?{query}"
    )
    project_code, by_project = await _request(
        application, "GET", f"/api/orgs/{org_id}/costs/by-project?{query}"
    )
    model_code, by_model = await _request(
        application, "GET", f"/api/orgs/{org_id}/costs/by-agent-model?{query}"
    )
    trend_code, trend = await _request(
        application, "GET", f"/api/orgs/{org_id}/costs/trend?{query}"
    )
    window_code, window = await _request(
        application, "GET", f"/api/orgs/{org_id}/costs/window-spend?{query}"
    )

    assert summary_code == 200
    assert summary["totalCostCents"] == 100
    assert summary["eventCount"] == 1
    assert agent_code == 200 and by_agent[0]["costCents"] == 100
    assert provider_code == 200 and by_provider[0]["provider"] == "openai"
    assert biller_code == 200 and by_biller[0]["biller"] == "openrouter"
    assert project_code == 200 and by_project[0]["projectId"] == project_id
    assert model_code == 200 and by_model[0]["model"] == "gpt-5"
    assert trend_code == 200 and trend[0]["bucket"] == "2026-06-01"
    assert window_code == 200 and window["costCents"] == 100


async def test_cost_scope_rejects_cross_org_and_agent_impersonation(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id, _ = await _seed_org_agent_project(factory, prefix="scope-a")
    other_org_id, other_agent_id, _ = await _seed_org_agent_project(
        factory, prefix="scope-b"
    )

    cross_code, cross = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/cost-events",
        json={"agentId": other_agent_id, "costCents": 5},
    )
    impersonation_code, impersonation = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/cost-events",
        headers={"x-test-agent-id": agent_id, "x-test-org-id": org_id},
        json={"agentId": other_agent_id, "costCents": 5},
    )
    wrong_org_code, wrong_org = await _request(
        application,
        "GET",
        f"/api/orgs/{other_org_id}/costs/summary",
        headers={"x-test-agent-id": agent_id, "x-test-org-id": org_id},
    )

    assert cross_code == 422
    assert "organization" in cross["detail"]
    assert impersonation_code == 403
    assert "own cost" in impersonation["detail"]
    assert wrong_org_code == 403
    assert "another organization" in wrong_org["detail"]


async def test_run_cost_can_be_recorded_from_runtime_result(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    _, factory = app
    org_id, agent_id, _ = await _seed_org_agent_project(factory, prefix="run-cost")
    run_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            HeartbeatRun(
                id=run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="manual",
                status="succeeded",
                usage_json={"inputTokens": 10, "outputTokens": 5},
                result_json={
                    "costUsd": 1.25,
                    "provider": "openai",
                    "model": "gpt-5",
                    "biller": "openrouter",
                },
            )
        )
        await session.commit()

    from server.services.costs import CostService

    async with factory() as session:
        created = await CostService(session).record_run_cost_if_present(run_id)
        await session.commit()

    assert created is not None
    assert created["sourceType"] == "run"
    assert created["sourceId"] == run_id
    assert created["costCents"] == 125
    assert created["inputTokens"] == 10
    assert created["outputTokens"] == 5
