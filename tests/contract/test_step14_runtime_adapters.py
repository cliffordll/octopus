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
from packages.runtimes.codex_local.runner import execute as execute_codex_local
from packages.runtimes.types import RuntimeExecutionContext
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
    snapshot_entries = {entry["key"]: entry for entry in snapshot["entries"]}
    assert snapshot_entries["review"]["selectionKey"] == "review"
    assert snapshot_entries["review"]["runtimeName"] == "review"
    assert snapshot_entries["review"]["desired"] is True
    assert snapshot_entries["review"]["state"] == "configured"
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
    assert entries["conversation-to-skill"]["state"] == "missing"
    assert entries["conversation-to-skill"]["sourceClass"] == "bundled"
    assert entries["conversation-to-skill"]["readOnly"] is True


async def test_codex_skills_sync_materializes_desired_bundled_skill(
    app: tuple[FastAPI, async_sessionmaker], tmp_path: Path
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    codex_home = tmp_path / "codex-home"
    _, agent = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Codex Skill Agent",
            "agentRuntimeType": "codex_local",
            "agentRuntimeConfig": {"env": {"CODEX_HOME": str(codex_home)}},
        },
    )

    snapshot_code, snapshot = await _request(
        application, "GET", f"/api/agents/{agent['id']}/skills"
    )
    target = codex_home / "skills" / "conversation-to-skill" / "SKILL.md"
    assert snapshot_code == 200
    assert target.exists() is False

    sync_code, sync = await _request(
        application,
        "POST",
        f"/api/agents/{agent['id']}/skills/sync",
        json={"desiredSkills": ["conversation-to-skill"]},
    )

    assert sync_code == 200
    assert target.is_file()
    entries = {entry["key"]: entry for entry in sync["entries"]}
    assert entries["conversation-to-skill"]["state"] == "installed"
    assert entries["conversation-to-skill"]["managed"] is True
    assert entries["conversation-to-skill"]["targetPath"] == str(
        codex_home / "skills" / "conversation-to-skill"
    )


async def test_codex_execute_reports_loaded_skills_and_filtered_runtime_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codex_home = tmp_path / "codex-home"
    skill_dir = codex_home / "skills" / "review"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "# Review\n\nReview code changes.", encoding="utf-8"
    )
    captured_logs: list[tuple[str, str]] = []
    captured_env: dict[str, str] = {}

    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return (
                (
                    '{"type":"thread.started","thread_id":"thread-14"}\n'
                    '{"type":"item.completed","item":{"type":"agent_message",'
                    '"text":"done"}}\n'
                    '{"type":"turn.completed","usage":{"input_tokens":10,'
                    '"cached_input_tokens":4,"output_tokens":6}}\n'
                ).encode(),
                b"OpenAI telemetry disabled\nmeaningful warning\n",
            )

        def kill(self) -> None:
            raise AssertionError("successful Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        captured_env.update(kwargs["env"])
        return FakeCodexProcess()

    async def on_log(stream: str, chunk: str) -> None:
        captured_logs.append((stream, chunk))

    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-14",
            agent_id="agent-14",
            org_id="org-14",
            agent_name="Codex",
            config={
                "command": "codex-test",
                "env": {
                    "CODEX_HOME": str(codex_home),
                    "OPENAI_API_KEY": "test-key",
                },
            },
            on_log=on_log,
        )
    )

    assert captured_env["CODEX_HOME"] == str(codex_home)
    assert result.usage_json == {
        "inputTokens": 10,
        "cachedInputTokens": 4,
        "outputTokens": 6,
        "billingType": "api",
        "biller": "openai",
    }
    assert result.result_json == {
        "stdout": (
            '{"type":"thread.started","thread_id":"thread-14"}\n'
            '{"type":"item.completed","item":{"type":"agent_message",'
            '"text":"done"}}\n'
            '{"type":"turn.completed","usage":{"input_tokens":10,'
            '"cached_input_tokens":4,"output_tokens":6}}\n'
        ),
        "stderr": "meaningful warning\n",
        "summary": "done",
        "loadedSkills": [
            {
                "key": "review",
                "runtimeName": "review",
                "name": "Review",
                "description": "Review code changes.",
            }
        ],
        "billingType": "api",
        "biller": "openai",
    }
    assert ("stderr", "meaningful warning\n") in captured_logs
    assert all("telemetry" not in chunk.lower() for _, chunk in captured_logs)


async def test_codex_execute_uses_default_managed_codex_home(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    default_home = (
        tmp_path / ".octopus" / "runtime-homes" / "codex_local" / "org-14" / "agent-14"
    )
    skill_dir = default_home / "skills" / "default-skill"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text(
        "# Default Skill\n\nDefault managed skill.", encoding="utf-8"
    )
    captured_env: dict[str, str] = {}

    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return (
                (
                    '{"type":"thread.started","thread_id":"thread-default"}\n'
                    '{"type":"turn.completed","usage":{}}\n'
                ).encode(),
                b"",
            )

        def kill(self) -> None:
            raise AssertionError("successful Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        captured_env.update(kwargs["env"])
        return FakeCodexProcess()

    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-14",
            agent_id="agent-14",
            org_id="org-14",
            agent_name="Codex",
            config={"command": "codex-test"},
            on_log=lambda stream, chunk: _noop_log(stream, chunk),
        )
    )

    assert captured_env["CODEX_HOME"] == str(default_home)
    assert result.result_json is not None
    assert result.result_json["loadedSkills"] == [
        {
            "key": "default-skill",
            "runtimeName": "default-skill",
            "name": "Default Skill",
            "description": "Default managed skill.",
        }
    ]


async def test_codex_execute_suppresses_closed_stdin_tool_session_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCodexProcess:
        returncode = 1

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return (
                (
                    '{"type":"turn.failed","error":{"message":'
                    '"write_stdin failed because stdin is closed"}}\n'
                ).encode(),
                b"",
            )

        def kill(self) -> None:
            raise AssertionError("failed Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        return FakeCodexProcess()

    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-14",
            agent_id="agent-14",
            org_id="org-14",
            agent_name="Codex",
            config={"command": "codex-test"},
            on_log=lambda stream, chunk: _noop_log(stream, chunk),
        )
    )

    assert result.error_message == "Codex exited with code 1"


async def _noop_log(stream: str, chunk: str) -> None:
    return None


async def test_agent_skills_enable_private_and_analytics_routes(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    application, factory = app
    org_id = await _seed_org(factory)
    codex_home = tmp_path / "codex-home"
    _, agent = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Skill Ops Agent",
            "agentRuntimeType": "codex_local",
            "agentRuntimeConfig": {"env": {"CODEX_HOME": str(codex_home)}},
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
    assert private["selectionKey"] == "agent:incident-notes"
    assert private["sourceClass"] == "agent_home"
    assert private["desired"] is False
    assert private["state"] == "external"
    assert private["origin"] == "user_installed"
    assert private["originLabel"] == "Agent skill"
    assert private["locationLabel"] == "AGENT_HOME/skills"
    assert isinstance(private["sourcePath"], str)
    private_skill_file = Path(private["sourcePath"]) / "SKILL.md"
    assert private_skill_file.read_text(encoding="utf-8") == "# Incident Notes\n"

    snapshot_code, snapshot = await _request(
        application, "GET", f"/api/agents/{agent['id']}/skills"
    )
    snapshot_entries = {entry["selectionKey"]: entry for entry in snapshot["entries"]}
    assert snapshot_code == 200
    assert snapshot_entries["agent:incident-notes"]["sourceClass"] == "agent_home"
    assert snapshot_entries["agent:incident-notes"]["state"] == "external"

    private_enable_code, private_enabled = await _request(
        application,
        "POST",
        f"/api/agents/{agent['id']}/skills/enable",
        json={"skills": ["agent:incident-notes"]},
    )
    private_target = codex_home / "skills" / "incident-notes" / "SKILL.md"
    private_entries = {
        entry["selectionKey"]: entry for entry in private_enabled["entries"]
    }
    assert private_enable_code == 200
    assert private_target.is_file()
    assert private_entries["agent:incident-notes"]["desired"] is True
    assert private_entries["agent:incident-notes"]["state"] == "installed"
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
    assert detail["desiredSkills"] == ["review", "debug", "agent:incident-notes"]

    async with factory() as session:
        actions = [
            row.action for row in (await session.execute(select(ActivityLog))).scalars()
        ]
    assert "agent.skills_enabled" in actions
    assert "agent.private_skill_created" in actions
