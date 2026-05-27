from __future__ import annotations

import importlib
import importlib.util
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
import uuid

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.responses import Response

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.migrations.runner import upgrade_to_head
from packages.database.schema import Base, Organization
from server.app import create_app


def test_agent_contract_modules_define_management_boundary() -> None:
    modules = (
        "packages.shared.api_paths.agents",
        "packages.shared.constants.agent",
        "packages.shared.types.agent",
        "packages.shared.validators.agent",
    )
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    paths = importlib.import_module("packages.shared.api_paths.agents")
    constants = importlib.import_module("packages.shared.constants.agent")
    validators = importlib.import_module("packages.shared.validators.agent")

    assert paths.ORG_AGENT_LIST_PATH == "/api/orgs/{orgId}/agents"
    assert paths.AGENT_DETAIL_PATH == "/api/agents/{id}"
    assert paths.AGENT_PAUSE_PATH == "/api/agents/{id}/pause"
    assert constants.AGENT_STATUSES == (
        "active",
        "paused",
        "idle",
        "running",
        "error",
        "pending_approval",
        "terminated",
    )
    assert constants.AGENT_RUNTIME_TYPES == (
        "process",
        "http",
        "claude_local",
        "codex_local",
        "gemini_local",
        "opencode_local",
        "pi_local",
        "cursor",
        "openclaw_gateway",
        "hermes_local",
    )
    payload = validators.validate_create_agent({"name": "Operator"})
    assert payload["role"] == "general"
    assert payload["agentRuntimeType"] == "process"
    assert payload["agentRuntimeConfig"] == {}
    with pytest.raises(ValueError, match="role"):
        validators.validate_create_agent({"role": "invalid"})


def test_agent_schema_matches_step11a_boundary() -> None:
    schema = importlib.import_module("packages.database.schema")
    agent = schema.Agent
    assert agent.__tablename__ == "agents"
    assert isinstance(agent.__table__, Table)
    assert {index.name for index in agent.__table__.indexes} == {
        "agents_company_status_idx",
        "agents_company_reports_to_idx",
        "agents_org_workspace_key_idx",
    }
    assert "agents" in {table.name for table in Base.metadata.sorted_tables}


async def test_upgrade_to_head_creates_agents_table(tmp_path: Path) -> None:
    db_path = tmp_path / "step11a-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")

    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master "
                    "where type='table' and name = 'agents'"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()

    assert names == {"agents"}


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
async def session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return create_session_factory(engine)


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker,
) -> FastAPI:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    application = create_app()
    application.state.session_factory = session_factory

    @application.middleware("http")
    async def inject_agent_actor(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        actor_id = request.headers.get("x-test-agent-id")
        if actor_id:
            request.state.actor = {
                "type": "agent",
                "id": actor_id,
                "agentId": actor_id,
                "orgId": request.headers["x-test-org-id"],
            }
        return await call_next(request)

    return application


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
    return response.status_code, response.json()


async def _seed_org(session_factory: async_sessionmaker, *, key: str) -> str:
    async with session_factory() as session:
        org = Organization(
            id=str(uuid.uuid4()), url_key=key, name=key, issue_prefix=key[:3].upper()
        )
        session.add(org)
        await session.commit()
        return org.id


async def test_agent_routes_manage_lifecycle_and_hide_terminated_agents(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="agents")

    create_code, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={"name": "Runner", "role": "engineer"},
    )
    assert create_code == 201
    assert created["orgId"] == org_id
    assert created["urlKey"] == "runner"
    assert created["status"] == "idle"
    assert created["agentRuntimeType"] == "process"

    detail_code, detail = await _request(app, "GET", f"/api/agents/{created['id']}")
    assert detail_code == 200
    assert detail["chainOfCommand"] == []
    assert detail["access"]["taskAssignSource"] == "none"

    patch_code, updated = await _request(
        app,
        "PATCH",
        f"/api/agents/{created['id']}",
        json={"title": "Execution owner"},
    )
    assert patch_code == 200
    assert updated["title"] == "Execution owner"

    pause_code, paused = await _request(
        app, "POST", f"/api/agents/{created['id']}/pause"
    )
    assert pause_code == 200
    assert paused["status"] == "paused"
    assert paused["pauseReason"] == "manual"

    resume_code, resumed = await _request(
        app, "POST", f"/api/agents/{created['id']}/resume"
    )
    assert resume_code == 200
    assert resumed["status"] == "idle"
    assert resumed["pauseReason"] is None

    terminate_code, terminated = await _request(
        app, "POST", f"/api/agents/{created['id']}/terminate"
    )
    assert terminate_code == 200
    assert terminated["status"] == "terminated"

    list_code, listed = await _request(app, "GET", f"/api/orgs/{org_id}/agents")
    assert list_code == 200
    assert listed == []


async def test_agent_manager_must_belong_to_same_organization(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    home_id = await _seed_org(session_factory, key="home")
    foreign_id = await _seed_org(session_factory, key="foreign")
    _, manager = await _request(
        app,
        "POST",
        f"/api/orgs/{foreign_id}/agents",
        json={"name": "Foreign Manager"},
    )

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{home_id}/agents",
        json={"name": "Worker", "reportsTo": manager["id"]},
    )
    assert code == 422
    assert "same organization" in body["detail"]


async def test_agent_update_merges_runtime_configuration_unless_replace_requested(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="adapter-config")
    _, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Configured",
            "agentRuntimeConfig": {"cwd": "workspace", "model": "initial"},
        },
    )

    code, merged = await _request(
        app,
        "PATCH",
        f"/api/agents/{created['id']}",
        json={"agentRuntimeConfig": {"model": "updated"}},
    )
    assert code == 200
    assert merged["agentRuntimeConfig"] == {"cwd": "workspace", "model": "updated"}

    code, replaced = await _request(
        app,
        "PATCH",
        f"/api/agents/{created['id']}",
        json={
            "agentRuntimeConfig": {"model": "only"},
            "replaceAgentRuntimeConfig": True,
        },
    )
    assert code == 200
    assert replaced["agentRuntimeConfig"] == {"model": "only"}


async def test_agent_cannot_list_other_organization(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    org_id = await _seed_org(session_factory, key="private")
    code, _ = await _request(
        app,
        "GET",
        f"/api/orgs/{org_id}/agents",
        headers={
            "x-test-agent-id": "agent-1",
            "x-test-org-id": "another-org",
        },
    )
    assert code == 403
