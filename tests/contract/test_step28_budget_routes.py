from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import (
    ActivityLog,
    Agent,
    Approval,
    Base,
    BudgetIncident,
    HeartbeatRun,
    Organization,
    Project,
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


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json)
    return response.status_code, response.json()


async def _seed_scope(factory: async_sessionmaker) -> tuple[str, str, str]:
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"budget-{uuid.uuid4().hex[:8]}",
                name="Budget Org",
                issue_prefix=f"BG{uuid.uuid4().hex[:4].upper()}",
                require_board_approval_for_new_agents=False,
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Budget Agent",
                workspace_key="budget-agent",
                role="engineer",
                agent_runtime_type="codex_local",
            )
        )
        session.add(
            Project(
                id=project_id,
                org_id=org_id,
                name="Budget Project",
                status="active",
            )
        )
        await session.commit()
    return org_id, agent_id, project_id


async def test_budget_policy_overview_and_budget_patch_routes(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id, _ = await _seed_scope(factory)

    code, policy = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/budgets/policies",
        json={"scopeType": "agent", "scopeId": agent_id, "amount": 100},
    )
    overview_code, overview = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/budgets/overview",
    )
    org_budget_code, org_budget = await _request(
        application,
        "PATCH",
        f"/api/orgs/{org_id}/budgets",
        json={"budgetMonthlyCents": 5000},
    )
    agent_budget_code, agent_budget = await _request(
        application,
        "PATCH",
        f"/api/agents/{agent_id}/budgets",
        json={"budgetMonthlyCents": 2500},
    )

    assert code == 200
    assert policy["scopeType"] == "agent"
    assert policy["scopeId"] == agent_id
    assert policy["amount"] == 100
    assert policy["observedAmount"] == 0
    assert policy["status"] == "ok"
    assert overview_code == 200
    assert overview["policies"][0]["policyId"] == policy["policyId"]
    assert org_budget_code == 200
    assert org_budget["budgetMonthlyCents"] == 5000
    assert agent_budget_code == 200
    assert agent_budget["budgetMonthlyCents"] == 2500

    async with factory() as session:
        org = await session.get(Organization, org_id)
        agent = await session.get(Agent, agent_id)
    assert org is not None and org.budget_monthly_cents == 5000
    assert agent is not None and agent.budget_monthly_cents == 2500


async def test_cost_event_crosses_budget_thresholds_and_blocks_new_work(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id, project_id = await _seed_scope(factory)
    queued_run_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            HeartbeatRun(
                id=queued_run_id,
                org_id=org_id,
                agent_id=agent_id,
                invocation_source="manual",
                status="queued",
            )
        )
        await session.commit()

    policy_code, _ = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/budgets/policies",
        json={
            "scopeType": "agent",
            "scopeId": agent_id,
            "amount": 100,
            "warnPercent": 50,
        },
    )
    cost_code, _ = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/cost-events",
        json={
            "agentId": agent_id,
            "projectId": project_id,
            "sourceType": "run",
            "sourceId": "budget-run",
            "costCents": 120,
            "occurredAt": datetime.now(UTC).isoformat(),
        },
    )
    wake_code, wake_body = await _request(
        application,
        "POST",
        f"/api/agents/{agent_id}/wakeup",
        json={"reason": "manual"},
    )

    assert policy_code == 200
    assert cost_code == 201
    assert wake_code == 422
    assert "budget hard-stop" in wake_body["detail"]

    async with factory() as session:
        agent = await session.get(Agent, agent_id)
        queued = await session.get(HeartbeatRun, queued_run_id)
        incidents = (
            (await session.execute(select(BudgetIncident).order_by(BudgetIncident.id)))
            .scalars()
            .all()
        )
        approvals = (await session.execute(select(Approval))).scalars().all()
        actions = [
            row.action for row in (await session.execute(select(ActivityLog))).scalars()
        ]

    assert agent is not None
    assert agent.status == "paused"
    assert agent.pause_reason == "budget"
    assert queued is not None
    assert queued.status == "cancelled"
    assert {incident.threshold_type for incident in incidents} == {"soft", "hard"}
    assert {incident.threshold_type: incident.status for incident in incidents} == {
        "soft": "resolved",
        "hard": "open",
    }
    assert len(approvals) == 1
    assert approvals[0].type == "budget_override_required"
    assert "budget.hard_threshold_crossed" in actions


async def test_budget_incident_resolve_raises_budget_and_resumes_scope(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id, _ = await _seed_scope(factory)

    await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/budgets/policies",
        json={"scopeType": "agent", "scopeId": agent_id, "amount": 100},
    )
    await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/cost-events",
        json={"agentId": agent_id, "costCents": 120},
    )
    async with factory() as session:
        incident = (
            await session.execute(
                select(BudgetIncident).where(BudgetIncident.threshold_type == "hard")
            )
        ).scalar_one()

    bad_code, bad = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/budget-incidents/{incident.id}/resolve",
        json={"action": "raise_budget_and_resume", "amount": 100},
    )
    good_code, resolved = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/budget-incidents/{incident.id}/resolve",
        json={
            "action": "raise_budget_and_resume",
            "amount": 200,
            "decisionNote": "increase approved",
        },
    )

    assert bad_code == 422
    assert "exceed current observed spend" in bad["detail"]
    assert good_code == 200
    assert resolved["status"] == "resolved"

    async with factory() as session:
        agent = await session.get(Agent, agent_id)
        updated_incident = await session.get(BudgetIncident, incident.id)
    assert agent is not None
    assert agent.status == "idle"
    assert agent.pause_reason is None
    assert updated_incident is not None
    assert updated_incident.status == "resolved"
