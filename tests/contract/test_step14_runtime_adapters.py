from __future__ import annotations

import importlib
import sys
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Base, Organization
from server.app import create_app


def test_step14_runtime_contract_exposes_adapter_paths() -> None:
    paths = importlib.import_module("packages.shared.api_paths.agents")

    assert paths.ORG_ADAPTER_MODELS_PATH == "/api/orgs/{orgId}/adapters/{type}/models"
    assert (
        paths.ORG_ADAPTER_TEST_ENVIRONMENT_PATH
        == "/api/orgs/{orgId}/adapters/{type}/test-environment"
    )
    assert paths.AGENT_SKILLS_PATH == "/api/agents/{id}/skills"
    assert paths.AGENT_SKILLS_SYNC_PATH == "/api/agents/{id}/skills/sync"


def test_step14_registry_returns_known_adapters_or_unavailable() -> None:
    registry = importlib.import_module("packages.runtimes.registry")

    assert registry.get_runtime_adapter("http").type == "http"
    assert registry.get_runtime_adapter("claude_local").type == "claude_local"
    assert registry.get_runtime_adapter("opencode_local").type == "opencode_local"
    assert registry.get_runtime_adapter("gemini_local").type == "gemini_local"


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


async def _seed_org(factory: async_sessionmaker) -> str:
    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id, url_key="step14", name="Step 14", issue_prefix="RTA"
            )
        )
        await session.commit()
    return org_id


async def test_adapter_models_and_environment_routes(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)

    models_code, models = await _request(
        application, "GET", f"/api/orgs/{org_id}/adapters/codex_local/models"
    )
    env_code, env = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/adapters/http/test-environment",
        json={"agentRuntimeConfig": {"url": "http://example.test"}},
    )
    skipped_code, skipped = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/adapters/gemini_local/test-environment",
        json={"agentRuntimeConfig": {}},
    )

    assert models_code == 200
    assert isinstance(models, list)
    assert env_code == 200
    assert env["agentRuntimeType"] == "http"
    assert env["status"] in {"ok", "warning"}
    assert skipped_code == 200
    assert skipped["status"] == "unavailable"


async def test_agent_skills_snapshot_and_sync_routes(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    _, agent = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Skill Agent",
            "agentRuntimeType": "opencode_local",
            "agentRuntimeConfig": {"command": sys.executable},
            "desiredSkills": ["review"],
        },
    )

    snapshot_code, snapshot = await _request(
        application, "GET", f"/api/agents/{agent['id']}/skills"
    )
    sync_code, sync = await _request(
        application,
        "POST",
        f"/api/agents/{agent['id']}/skills/sync",
        json={"skills": ["review", "debug"]},
    )

    assert snapshot_code == 200
    assert snapshot["agentRuntimeType"] == "opencode_local"
    assert snapshot["supported"] is True
    assert sync_code == 200
    assert sync["desiredSkills"] == ["review", "debug"]
