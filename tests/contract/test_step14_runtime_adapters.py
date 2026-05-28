from __future__ import annotations

import importlib
import sys
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import ActivityLog, AgentEnabledSkill, Base, Organization
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
    assert paths.AGENT_SKILLS_ENABLE_PATH == "/api/agents/{id}/skills/enable"
    assert paths.AGENT_SKILLS_PRIVATE_PATH == "/api/agents/{id}/skills/private"
    assert paths.AGENT_SKILLS_ANALYTICS_PATH == "/api/agents/{id}/skills/analytics"
    assert paths.ORG_ADAPTER_METADATA_PATH == "/api/orgs/{orgId}/adapters/{type}"
    assert (
        paths.ORG_ADAPTER_QUOTA_WINDOWS_PATH
        == "/api/orgs/{orgId}/adapters/{type}/quota-windows"
    )


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

    metadata_code, metadata = await _request(
        application, "GET", f"/api/orgs/{org_id}/adapters/codex_local"
    )
    quota_code, quota = await _request(
        application, "GET", f"/api/orgs/{org_id}/adapters/codex_local/quota-windows"
    )
    unavailable_quota_code, unavailable_quota = await _request(
        application, "GET", f"/api/orgs/{org_id}/adapters/gemini_local/quota-windows"
    )

    assert metadata_code == 200
    assert metadata["type"] == "codex_local"
    assert metadata["capabilities"]["models"] is True
    assert metadata["capabilities"]["skills"] is True
    assert metadata["capabilities"]["quotaWindows"] is True
    assert metadata["supportsLocalAgentJwt"] is True
    assert isinstance(metadata["agentConfigurationDoc"], str)
    assert quota_code == 200
    assert quota["provider"] == "openai"
    assert quota["ok"] is False
    assert quota["windows"] == []
    assert unavailable_quota_code == 200
    assert unavailable_quota["provider"] == "gemini_local"
    assert unavailable_quota["ok"] is False


async def test_agent_skills_snapshot_and_sync_routes(
    app: tuple[FastAPI, async_sessionmaker], tmp_path: Path
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    skills_root = tmp_path / "skills"
    review_skill = skills_root / "review"
    review_skill.mkdir(parents=True)
    review_skill.joinpath("SKILL.md").write_text(
        "# Review\n\nReview code changes.", encoding="utf-8"
    )
    _, agent = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Skill Agent",
            "capabilities": "Review code and explain runtime risks.",
            "agentRuntimeType": "opencode_local",
            "agentRuntimeConfig": {
                "command": sys.executable,
                "promptTemplate": "Use the agent capabilities as operating guidance.",
                "skillsRootPath": str(skills_root),
            },
            "desiredSkills": ["review"],
        },
    )
    assert agent["capabilities"] == "Review code and explain runtime risks."
    assert agent["desiredSkills"] == ["review"]
    assert (
        agent["agentRuntimeConfig"]["promptTemplate"]
        == "Use the agent capabilities as operating guidance."
    )

    snapshot_code, snapshot = await _request(
        application, "GET", f"/api/agents/{agent['id']}/skills"
    )
    sync_code, sync = await _request(
        application,
        "POST",
        f"/api/agents/{agent['id']}/skills/sync",
        json={"desiredSkills": ["review", "debug"]},
    )

    assert snapshot_code == 200
    assert snapshot["agentRuntimeType"] == "opencode_local"
    assert snapshot["supported"] is True
    assert snapshot["mode"] == "ephemeral"
    assert snapshot["desiredSkills"] == ["review"]
    assert snapshot["entries"][0]["key"] == "review"
    assert snapshot["entries"][0]["selectionKey"] == "review"
    assert snapshot["entries"][0]["runtimeName"] == "review"
    assert snapshot["entries"][0]["desired"] is True
    assert snapshot["entries"][0]["state"] == "configured"
    assert sync_code == 200
    assert sync["desiredSkills"] == ["review", "debug"]

    detail_code, detail = await _request(
        application, "GET", f"/api/agents/{agent['id']}"
    )
    assert detail_code == 200
    assert detail["desiredSkills"] == ["review", "debug"]

    async with factory() as session:
        actions = [
            row.action for row in (await session.execute(select(ActivityLog))).scalars()
        ]
        skill_keys = [
            row.skill_key
            for row in (await session.execute(select(AgentEnabledSkill))).scalars()
        ]
    assert "agent.skills_synced" in actions
    assert skill_keys == ["review", "debug"]


async def test_agent_skills_snapshot_includes_bundled_skills_without_configured_root(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    _, agent = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Bundled Skill Agent",
            "agentRuntimeType": "codex_local",
            "desiredSkills": ["conversation-to-skill"],
        },
    )

    snapshot_code, snapshot = await _request(
        application, "GET", f"/api/agents/{agent['id']}/skills"
    )

    assert snapshot_code == 200
    entries = {entry["key"]: entry for entry in snapshot["entries"]}
    assert {
        "control-plane",
        "conversation-to-skill",
        "create-agent",
        "create-plugin",
        "para-memory-files",
        "skill-creator",
        "skill-optimizer",
    }.issubset(entries)
    assert entries["conversation-to-skill"]["desired"] is True
    assert entries["conversation-to-skill"]["state"] == "configured"
    assert entries["conversation-to-skill"]["sourceClass"] == "bundled"
    assert entries["conversation-to-skill"]["readOnly"] is True


async def test_agent_skills_enable_private_and_analytics_routes(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    _, agent = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Skill Ops Agent",
            "agentRuntimeType": "codex_local",
            "desiredSkills": ["review"],
        },
    )

    enable_code, enabled = await _request(
        application,
        "POST",
        f"/api/agents/{agent['id']}/skills/enable",
        json={"skills": ["debug", "review"]},
    )
    private_code, private = await _request(
        application,
        "POST",
        f"/api/agents/{agent['id']}/skills/private",
        json={
            "name": "Incident Notes",
            "slug": "incident-notes",
            "description": "Capture incident context.",
            "markdown": "# Incident Notes\n",
        },
    )
    analytics_code, analytics = await _request(
        application,
        "GET",
        f"/api/agents/{agent['id']}/skills/analytics",
    )

    assert enable_code == 200
    assert enabled["desiredSkills"] == ["review", "debug"]
    assert private_code == 201
    assert private["key"] == "incident-notes"
    assert private["selectionKey"] == "private:incident-notes"
    assert private["sourceClass"] == "agent_home"
    assert private["desired"] is False
    assert analytics_code == 200
    assert analytics["agentId"] == agent["id"]
    assert analytics["orgId"] == org_id
    assert analytics["totalCount"] == 0
    assert analytics["skills"] == []
    assert analytics["days"] == []

    detail_code, detail = await _request(
        application, "GET", f"/api/agents/{agent['id']}"
    )
    assert detail_code == 200
    assert detail["desiredSkills"] == ["review", "debug"]

    async with factory() as session:
        actions = [
            row.action for row in (await session.execute(select(ActivityLog))).scalars()
        ]
    assert "agent.skills_enabled" in actions
    assert "agent.private_skill_created" in actions
