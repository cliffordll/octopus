from __future__ import annotations

import importlib
import subprocess
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
from packages.runtimes.claude_local.runner import execute as execute_claude_local
from packages.runtimes.codex_local.runner import execute as execute_codex_local
from packages.runtimes.opencode_local.runner import execute as execute_opencode_local
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


async def test_local_runtime_environment_reports_cwd_command_and_auth_checks(
    app: tuple[FastAPI, async_sessionmaker], tmp_path: Path
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    cwd = tmp_path / "workspace"
    missing_cwd = tmp_path / "missing"
    cwd.mkdir()

    claude_code, claude = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/adapters/claude_local/test-environment",
        json={
            "agentRuntimeConfig": {
                "cwd": str(cwd),
                "command": sys.executable,
                "env": {"ANTHROPIC_API_KEY": "test-key"},
            }
        },
    )
    opencode_code, opencode = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/adapters/opencode_local/test-environment",
        json={
            "agentRuntimeConfig": {
                "cwd": str(missing_cwd),
                "command": "definitely-missing-opencode",
            }
        },
    )

    assert claude_code == 200
    assert claude["status"] == "ok"
    claude_checks = {check["id"]: check for check in claude["checks"]}
    assert claude_checks["cwd"]["status"] == "ok"
    assert claude_checks["command"]["status"] == "ok"
    assert claude_checks["auth"]["status"] == "ok"

    assert opencode_code == 200
    assert opencode["status"] == "failed"
    opencode_checks = {check["id"]: check for check in opencode["checks"]}
    assert opencode_checks["cwd"]["status"] == "failed"
    assert opencode_checks["command"]["status"] == "failed"
    assert opencode_checks["model"]["status"] == "failed"
    assert opencode_checks["auth"]["status"] == "warning"

    codex_code, codex = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/adapters/codex_local/test-environment",
        json={
            "agentRuntimeConfig": {
                "cwd": str(cwd),
                "command": sys.executable,
                "env": {"OPENAI_API_KEY": "test-key"},
            }
        },
    )
    assert codex_code == 200
    assert codex["status"] == "ok"
    codex_checks = {check["id"]: check for check in codex["checks"]}
    assert codex_checks["cwd"]["status"] == "ok"
    assert codex_checks["command"]["status"] == "ok"
    assert codex_checks["auth"]["status"] == "ok"


async def test_opencode_environment_validates_model_configuration(
    app: tuple[FastAPI, async_sessionmaker], tmp_path: Path
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    cwd = tmp_path / "workspace"
    cwd.mkdir()

    invalid_code, invalid = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/adapters/opencode_local/test-environment",
        json={
            "agentRuntimeConfig": {
                "cwd": str(cwd),
                "command": sys.executable,
                "model": "gpt-5",
            }
        },
    )
    valid_code, valid = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/adapters/opencode_local/test-environment",
        json={
            "agentRuntimeConfig": {
                "cwd": str(cwd),
                "command": sys.executable,
                "model": "openai/gpt-5",
            }
        },
    )

    assert invalid_code == 200
    invalid_checks = {check["id"]: check for check in invalid["checks"]}
    assert invalid["status"] == "failed"
    assert invalid_checks["model"]["status"] == "failed"
    assert "provider/model" in invalid_checks["model"]["message"]

    assert valid_code == 200
    valid_checks = {check["id"]: check for check in valid["checks"]}
    assert valid_checks["model"]["status"] == "ok"
    assert valid_checks["model"]["message"] == "Configured model: openai/gpt-5"


async def test_http_environment_validates_url_shape(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)

    code, result = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/adapters/http/test-environment",
        json={"agentRuntimeConfig": {"url": "not-a-url"}},
    )

    assert code == 200
    assert result["status"] == "failed"
    checks = {check["id"]: check for check in result["checks"]}
    assert checks["url"]["status"] == "failed"


async def test_agent_skills_snapshot_and_sync_routes(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
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
                "model": "openai/gpt-5",
                "promptTemplate": "Use the agent capabilities as operating guidance.",
                "skillsRootPath": str(skills_root),
            },
            "desiredSkills": ["review"],
        },
    )
    assert agent["capabilities"] == "Review code and explain runtime risks."
    assert agent["desiredSkills"] == ["review"]
    runtime_config = agent["agentRuntimeConfig"]
    assert "promptTemplate" not in runtime_config
    assert runtime_config["instructionsBundleMode"] == "managed"
    assert runtime_config["instructionsEntryFile"] == "SOUL.md"
    assert Path(runtime_config["instructionsRootPath"]).is_dir()
    soul_path = Path(runtime_config["instructionsFilePath"])
    assert soul_path.name == "SOUL.md"
    assert (
        soul_path.read_text(encoding="utf-8")
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
    assert snapshot_entries["review"]["sourceRole"] == "review"
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


async def test_local_runtime_agent_resolves_explicit_relative_instructions_path(
    app: tuple[FastAPI, async_sessionmaker], tmp_path: Path
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    create_code, agent = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Explicit Instructions Agent",
            "agentRuntimeType": "codex_local",
            "agentRuntimeConfig": {
                "cwd": str(workspace),
                "instructionsFilePath": "instructions/SOUL.md",
                "promptTemplate": "Keep this legacy prompt because path is explicit.",
            },
        },
    )

    assert create_code == 201
    config = agent["agentRuntimeConfig"]
    assert config["instructionsFilePath"] == str(
        (workspace / "instructions" / "SOUL.md").resolve()
    )
    assert "instructionsBundleMode" not in config
    assert (
        config["promptTemplate"] == "Keep this legacy prompt because path is explicit."
    )


async def test_local_runtime_agent_rejects_relative_instructions_without_absolute_cwd(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)

    create_code, error = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Invalid Instructions Agent",
            "agentRuntimeType": "codex_local",
            "agentRuntimeConfig": {"instructionsFilePath": "SOUL.md"},
        },
    )

    assert create_code == 422
    assert "Relative instructionsFilePath requires" in error["detail"]


async def test_opencode_local_agent_requires_provider_model(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)

    missing_code, missing_error = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "OpenCode Missing Model",
            "agentRuntimeType": "opencode_local",
            "agentRuntimeConfig": {},
        },
    )
    invalid_code, invalid_error = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "OpenCode Invalid Model",
            "agentRuntimeType": "opencode_local",
            "agentRuntimeConfig": {"model": "gpt-5"},
        },
    )

    assert missing_code == 422
    assert "opencode_local requires agentRuntimeConfig.model" in missing_error["detail"]
    assert invalid_code == 422
    assert "provider/model" in invalid_error["detail"]


async def test_opencode_local_update_requires_provider_model(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    _, agent = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={"name": "Process Agent"},
    )

    switch_code, switch_error = await _request(
        application,
        "PATCH",
        f"/api/agents/{agent['id']}",
        json={"agentRuntimeType": "opencode_local"},
    )
    valid_code, valid = await _request(
        application,
        "PATCH",
        f"/api/agents/{agent['id']}",
        json={
            "agentRuntimeType": "opencode_local",
            "agentRuntimeConfig": {"model": "openai/gpt-5"},
        },
    )
    invalid_code, invalid_error = await _request(
        application,
        "PATCH",
        f"/api/agents/{agent['id']}",
        json={"agentRuntimeConfig": {"model": "gpt-5"}},
    )

    assert switch_code == 422
    assert "opencode_local requires agentRuntimeConfig.model" in switch_error["detail"]
    assert valid_code == 200
    assert valid["agentRuntimeType"] == "opencode_local"
    assert invalid_code == 422
    assert "provider/model" in invalid_error["detail"]


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


async def test_codex_execute_streams_agent_message_delta(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return (
                b'{"type":"thread.started","thread_id":"thread-stream"}\n'
                b'{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n',
                b"",
            )

        def kill(self) -> None:
            raise AssertionError("successful Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        return FakeCodexProcess()

    async def on_log(stream: str, chunk: str) -> None:
        return None

    streamed: list[dict[str, object]] = []

    async def on_stream_event(event: dict[str, object]) -> None:
        streamed.append(event)

    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-14-stream",
            agent_id="agent-14",
            org_id="org-14",
            agent_name="Codex",
            config={"command": "codex-test"},
            on_log=on_log,
            on_stream_event=on_stream_event,
        )
    )

    assert result.exit_code == 0
    assert streamed == [{"type": "assistant_delta", "delta": "done"}]


async def test_codex_execute_infers_openrouter_biller_from_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return b'{"type":"turn.completed","usage":{}}\n', b""

        def kill(self) -> None:
            raise AssertionError("successful Codex process must not be killed")

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
            config={
                "command": "codex-test",
                "env": {"OPENAI_API_KEY": "sk-test", "OPENROUTER_API_KEY": "sk-or"},
            },
            on_log=lambda stream, chunk: _noop_log(stream, chunk),
        )
    )

    assert result.usage_json is not None
    assert result.usage_json["billingType"] == "api"
    assert result.usage_json["biller"] == "openrouter"
    assert result.result_json is not None
    assert result.result_json["biller"] == "openrouter"


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


async def test_codex_execute_uses_managed_home_and_syncs_cli_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator_home = tmp_path / "operator-home"
    operator_home.joinpath(".config", "gh").mkdir(parents=True)
    operator_home.joinpath(".config", "gh", "hosts.yml").write_text(
        "github.com: {}\n", encoding="utf-8"
    )
    operator_home.joinpath(".npmrc").write_text(
        "//registry.npmjs.org/:_authToken=test\n", encoding="utf-8"
    )
    codex_home = tmp_path / "codex-home"
    captured_env: dict[str, str] = {}
    logs: list[tuple[str, str]] = []

    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return (
                b'{"type":"thread.started","thread_id":"thread-home"}\n',
                b"",
            )

        def kill(self) -> None:
            raise AssertionError("successful Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        captured_env.update(kwargs["env"])
        return FakeCodexProcess()

    async def on_log(stream: str, chunk: str) -> None:
        logs.append((stream, chunk))

    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-14",
            agent_id="agent-14",
            org_id="org-14",
            agent_name="Codex",
            config={
                "command": "codex-test",
                "env": {
                    "CODEX_HOME": str(codex_home),
                    "RUDDER_OPERATOR_HOME": str(operator_home),
                    "GIT_AUTHOR_NAME": "Bad Author",
                    "GIT_AUTHOR_EMAIL": "agent@host.local",
                },
            },
            on_log=on_log,
        )
    )

    managed_home = codex_home / "home"
    assert captured_env["HOME"] == str(managed_home)
    assert captured_env["USERPROFILE"] == str(managed_home)
    assert captured_env["AGENT_HOME"] == str(managed_home)
    assert captured_env["GIT_CONFIG_GLOBAL"] == str(managed_home / ".gitconfig")
    assert "GIT_AUTHOR_NAME" not in captured_env
    assert "GIT_AUTHOR_EMAIL" not in captured_env
    assert captured_env["GIT_CONFIG_KEY_0"] == "credential.helper"
    assert captured_env["GIT_CONFIG_VALUE_0"] == ""
    assert captured_env["GIT_CONFIG_KEY_1"] == "credential.helper"
    assert captured_env["GIT_CONFIG_VALUE_1"] == "!gh auth git-credential"
    assert (managed_home / ".gitconfig").read_text(encoding="utf-8") == (
        "[user]\n\tuseConfigOnly = true\n"
    )
    assert managed_home.joinpath(".config", "gh", "hosts.yml").exists()
    assert managed_home.joinpath(".npmrc").exists()
    assert any("Shared 2 local CLI credential entries" in chunk for _, chunk in logs)


async def test_codex_execute_retries_unknown_resume_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_args: list[tuple[str, ...]] = []
    logs: list[tuple[str, str]] = []

    class FakeCodexProcess:
        def __init__(self, returncode: int, stdout: bytes, stderr: bytes) -> None:
            self.returncode = returncode
            self._stdout = stdout
            self._stderr = stderr

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return self._stdout, self._stderr

        def kill(self) -> None:
            raise AssertionError("Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        captured_args.append(args)
        if len(captured_args) == 1:
            return FakeCodexProcess(
                1,
                b"",
                b"Error: thread/resume failed: no rollout found for thread id old\n",
            )
        return FakeCodexProcess(
            0,
            (
                b'{"type":"thread.started","thread_id":"new-thread"}\n'
                b'{"type":"item.completed","item":{"type":"agent_message",'
                b'"text":"retried"}}\n'
            ),
            b"",
        )

    async def on_log(stream: str, chunk: str) -> None:
        logs.append((stream, chunk))

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
                "_octopus": {"sessionIdBefore": "old-thread"},
            },
            on_log=on_log,
        )
    )

    assert captured_args[0][-3:] == ("resume", "old-thread", "-")
    assert captured_args[1][-1:] == ("-",)
    assert result.exit_code == 0
    assert result.session_id_after == "new-thread"
    assert result.result_json is not None
    assert result.result_json["summary"] == "retried"
    assert any("retrying with a fresh session" in chunk for _, chunk in logs)


async def test_codex_execute_injects_runtime_context_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_env: dict[str, str] = {}

    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return b'{"type":"thread.started","thread_id":"thread-env"}\n', b""

        def kill(self) -> None:
            raise AssertionError("successful Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        captured_env.update(kwargs["env"])
        return FakeCodexProcess()

    monkeypatch.setenv("RUDDER_API_URL", "http://control.test")
    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-14",
            agent_id="agent-14",
            org_id="org-14",
            agent_name="Codex",
            config={
                "command": "codex-test",
                "_octopus": {
                    "taskId": "task-1",
                    "wakeReason": "assignment",
                    "wakeCommentId": "comment-1",
                    "approvalId": "approval-1",
                    "approvalStatus": "approved",
                    "issueIds": ["issue-1", "issue-2"],
                },
            },
            workspace={
                "rudderWorkspace": {
                    "cwd": "D:/workspaces/task-1",
                    "source": "workspace",
                    "strategy": "worktree",
                    "workspaceId": "workspace-1",
                    "repoUrl": "https://example.test/repo.git",
                    "repoRef": "main",
                    "branchName": "task-1",
                    "worktreePath": "D:/worktrees/task-1",
                    "agentHome": "D:/agents/agent-14",
                    "instructionsDir": "D:/agents/agent-14/instructions",
                    "memoryDir": "D:/agents/agent-14/memory",
                    "skillsDir": "D:/agents/agent-14/skills",
                    "orgWorkspaceRoot": "D:/orgs/org-14/workspaces",
                    "orgSkillsDir": "D:/orgs/org-14/skills",
                    "orgPlansDir": "D:/orgs/org-14/plans",
                    "orgArtifactsDir": "D:/orgs/org-14/artifacts",
                },
                "rudderRuntimeServices": [{"id": "svc-1", "url": "http://svc"}],
                "rudderRuntimePrimaryUrl": "http://svc",
            },
            env={
                "RUDDER_WORKSPACES_JSON": '[{"id":"workspace-1"}]',
                "RUDDER_RUNTIME_SERVICE_INTENTS_JSON": '[{"serviceName":"preview"}]',
            },
            on_log=lambda stream, chunk: _noop_log(stream, chunk),
        )
    )

    assert captured_env["RUDDER_AGENT_ID"] == "agent-14"
    assert captured_env["RUDDER_ORG_ID"] == "org-14"
    assert captured_env["RUDDER_RUN_ID"] == "run-14"
    assert captured_env["RUDDER_API_URL"] == "http://control.test"
    assert captured_env["RUDDER_TASK_ID"] == "task-1"
    assert captured_env["RUDDER_WAKE_REASON"] == "assignment"
    assert captured_env["RUDDER_WAKE_COMMENT_ID"] == "comment-1"
    assert captured_env["RUDDER_APPROVAL_ID"] == "approval-1"
    assert captured_env["RUDDER_APPROVAL_STATUS"] == "approved"
    assert captured_env["RUDDER_LINKED_ISSUE_IDS"] == "issue-1,issue-2"
    assert captured_env["RUDDER_WORKSPACE_CWD"] == "D:/workspaces/task-1"
    assert captured_env["RUDDER_WORKSPACE_SOURCE"] == "workspace"
    assert captured_env["RUDDER_WORKSPACE_STRATEGY"] == "worktree"
    assert captured_env["RUDDER_WORKSPACE_ID"] == "workspace-1"
    assert captured_env["RUDDER_WORKSPACE_REPO_URL"] == "https://example.test/repo.git"
    assert captured_env["RUDDER_WORKSPACE_REPO_REF"] == "main"
    assert captured_env["RUDDER_WORKSPACE_BRANCH"] == "task-1"
    assert captured_env["RUDDER_WORKSPACE_WORKTREE_PATH"] == "D:/worktrees/task-1"
    assert captured_env["AGENT_HOME"] == "D:/agents/agent-14"
    assert captured_env["RUDDER_AGENT_ROOT"] == "D:/agents/agent-14"
    assert captured_env["RUDDER_AGENT_INSTRUCTIONS_DIR"] == (
        "D:/agents/agent-14/instructions"
    )
    assert captured_env["RUDDER_AGENT_MEMORY_DIR"] == "D:/agents/agent-14/memory"
    assert captured_env["RUDDER_AGENT_SKILLS_DIR"] == "D:/agents/agent-14/skills"
    assert captured_env["RUDDER_ORG_WORKSPACE_ROOT"] == "D:/orgs/org-14/workspaces"
    assert captured_env["RUDDER_ORG_SKILLS_DIR"] == "D:/orgs/org-14/skills"
    assert captured_env["RUDDER_ORG_PLANS_DIR"] == "D:/orgs/org-14/plans"
    assert captured_env["RUDDER_ORG_ARTIFACTS_DIR"] == "D:/orgs/org-14/artifacts"
    assert captured_env["RUDDER_RUNTIME_SERVICES_JSON"] == (
        '[{"id": "svc-1", "url": "http://svc"}]'
    )
    assert captured_env["RUDDER_WORKSPACES_JSON"] == '[{"id":"workspace-1"}]'
    assert captured_env["RUDDER_RUNTIME_SERVICE_INTENTS_JSON"] == (
        '[{"serviceName":"preview"}]'
    )
    assert captured_env["RUDDER_RUNTIME_PRIMARY_URL"] == "http://svc"


async def test_codex_execute_drops_inherited_sandbox_proxy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_env: dict[str, str] = {}

    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return b'{"type":"thread.started","thread_id":"thread-proxy"}\n', b""

        def kill(self) -> None:
            raise AssertionError("successful Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        captured_env.update(kwargs["env"])
        return FakeCodexProcess()

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-proxy",
            agent_id="agent-proxy",
            org_id="org-proxy",
            agent_name="Codex",
            config={"command": "codex-test"},
            on_log=lambda stream, chunk: _noop_log(stream, chunk),
        )
    )

    assert "HTTPS_PROXY" not in captured_env
    assert "HTTP_PROXY" not in captured_env
    assert "ALL_PROXY" not in captured_env


async def test_codex_execute_preserves_explicit_proxy_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_env: dict[str, str] = {}

    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return b'{"type":"thread.started","thread_id":"thread-proxy"}\n', b""

        def kill(self) -> None:
            raise AssertionError("successful Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        captured_env.update(kwargs["env"])
        return FakeCodexProcess()

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-proxy",
            agent_id="agent-proxy",
            org_id="org-proxy",
            agent_name="Codex",
            config={
                "command": "codex-test",
                "env": {"HTTPS_PROXY": "http://127.0.0.1:9"},
            },
            on_log=lambda stream, chunk: _noop_log(stream, chunk),
        )
    )

    assert captured_env["HTTPS_PROXY"] == "http://127.0.0.1:9"


async def test_codex_execute_reports_subprocess_start_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_create_subprocess_exec(*args: str, **kwargs: Any) -> Any:
        raise OSError("spawn failed")

    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    result = await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-subprocess-denied",
            agent_id="agent-subprocess-denied",
            org_id="org-subprocess-denied",
            agent_name="Codex",
            config={"command": "codex-test"},
            on_log=lambda stream, chunk: _noop_log(stream, chunk),
        )
    )

    assert result.exit_code == 1
    assert result.error_message is not None
    assert "Failed to start Codex CLI" in result.error_message
    assert result.result_json is not None
    assert "spawn failed" in str(result.result_json["stderr"])


async def test_codex_execute_falls_back_when_windows_asyncio_spawn_is_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_create_subprocess_exec(*args: str, **kwargs: Any) -> Any:
        raise PermissionError(5, "Access is denied")

    def fake_run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        captured["args"] = args
        captured["input"] = kwargs["input"]
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout=(
                b'{"type":"thread.started","thread_id":"thread-fallback"}\n'
                b'{"type":"item.completed","item":{"type":"agent_message",'
                b'"text":"fallback ok"}}\n'
            ),
            stderr=b"",
        )

    monkeypatch.setattr("packages.runtimes.codex_local.runner.os.name", "nt")
    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr("packages.runtimes.codex_local.runner.subprocess.run", fake_run)

    result = await execute_codex_local(
        RuntimeExecutionContext(
            run_id="run-subprocess-fallback",
            agent_id="agent-subprocess-fallback",
            org_id="org-subprocess-fallback",
            agent_name="Codex",
            config={"command": "codex-test"},
            on_log=lambda stream, chunk: _noop_log(stream, chunk),
        )
    )

    assert result.exit_code == 0
    assert result.session_id_after == "thread-fallback"
    assert result.result_json is not None
    assert result.result_json["summary"] == "fallback ok"
    assert captured["input"] == b""


async def test_claude_and_opencode_execute_inject_runtime_context_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, dict[str, str]] = {}

    class FakeProcess:
        returncode = 0
        pid = 1234

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            return b"", b""

        def kill(self) -> None:
            raise AssertionError("successful local process must not be killed")

    async def fake_create_subprocess_exec(
        command: str, *args: str, **kwargs: Any
    ) -> FakeProcess:
        captured[command] = dict(kwargs["env"])
        return FakeProcess()

    monkeypatch.setattr(
        "packages.runtimes.claude_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    monkeypatch.setattr(
        "packages.runtimes.opencode_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    await execute_claude_local(
        _runtime_context_for_env(
            command="claude-test",
            config={"command": "claude-test"},
        )
    )
    await execute_opencode_local(
        _runtime_context_for_env(
            command="opencode-test",
            config={"command": "opencode-test", "model": "openai/gpt-5"},
        )
    )

    for command in ("claude-test", "opencode-test"):
        env = captured[command]
        assert env["RUDDER_AGENT_ID"] == "agent-14"
        assert env["RUDDER_ORG_ID"] == "org-14"
        assert env["RUDDER_RUN_ID"] == "run-14"
        assert env["RUDDER_TASK_ID"] == "task-1"
        assert env["RUDDER_WORKSPACE_CWD"] == "D:/workspaces/task-1"
        assert env["RUDDER_WORKSPACES_JSON"] == '[{"id":"workspace-1"}]'
        assert env["AGENT_HOME"] == "D:/agents/agent-14"
        assert env["RUDDER_AGENT_SKILLS_DIR"] == "D:/agents/agent-14/skills"
        assert env["RUDDER_RUNTIME_PRIMARY_URL"] == "http://svc"


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


def _runtime_context_for_env(
    *, command: str, config: dict[str, Any]
) -> RuntimeExecutionContext:
    return RuntimeExecutionContext(
        run_id="run-14",
        agent_id="agent-14",
        org_id="org-14",
        agent_name=command,
        config={
            **config,
            "_octopus": {
                "taskId": "task-1",
                "wakeReason": "assignment",
            },
        },
        workspace={
            "rudderWorkspace": {
                "cwd": "D:/workspaces/task-1",
                "source": "workspace",
                "strategy": "worktree",
                "agentHome": "D:/agents/agent-14",
                "skillsDir": "D:/agents/agent-14/skills",
            },
            "rudderRuntimePrimaryUrl": "http://svc",
        },
        env={"RUDDER_WORKSPACES_JSON": '[{"id":"workspace-1"}]'},
        on_log=lambda stream, chunk: _noop_log(stream, chunk),
    )


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
