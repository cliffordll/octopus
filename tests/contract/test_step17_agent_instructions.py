from __future__ import annotations

import importlib
import importlib.util
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import ActivityLog, Agent, Base, Organization
from server.app import create_app
from server.services.workspace_paths import resolve_octopus_instance_root


DEFAULT_INSTRUCTIONS_FILES = [
    "HEARTBEAT.md",
    "HEARTBEAT.zh-CN.md",
    "MEMORY.md",
    "MEMORY.zh-CN.md",
    "SOUL.md",
    "SOUL.zh-CN.md",
    "TOOLS.md",
    "TOOLS.zh-CN.md",
]


def test_step17_agent_instruction_contract_exposes_paths_and_validators() -> None:
    modules = (
        "packages.shared.api_paths.agents",
        "packages.shared.validators.agent",
        "packages.shared.types.agent",
    )
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    paths = importlib.import_module("packages.shared.api_paths.agents")
    validators = importlib.import_module("packages.shared.validators.agent")

    assert paths.AGENT_INSTRUCTIONS_PATH == "/api/agents/{id}/instructions-path"
    assert paths.AGENT_INSTRUCTIONS_BUNDLE_PATH == (
        "/api/agents/{id}/instructions-bundle"
    )
    assert paths.AGENT_INSTRUCTIONS_BUNDLE_FILE_PATH == (
        "/api/agents/{id}/instructions-bundle/file"
    )
    assert validators.validate_update_agent_instructions_path(
        {"path": " docs/AGENTS.md ", "agentRuntimeConfigKey": " instructionsFilePath "}
    ) == {
        "path": "docs/AGENTS.md",
        "agentRuntimeConfigKey": "instructionsFilePath",
    }
    assert validators.validate_update_agent_instructions_bundle(
        {"mode": "managed", "entryFile": " docs/SOUL.md "}
    ) == {"mode": "managed", "entryFile": "docs/SOUL.md"}
    assert validators.validate_upsert_agent_instructions_file(
        {"path": "MEMORY.md", "content": "# Memory"}
    ) == {"path": "MEMORY.md", "content": "# Memory"}


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker, Path]]:
    root = (tmp_path / f"step17-{uuid.uuid4().hex}").resolve()
    root.mkdir(parents=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_HOME", str(root / ".octopus"))
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory
    try:
        yield application, factory, root
    finally:
        await engine.dispose()


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json_body, params=params)
    if response.content:
        return response.status_code, response.json()
    return response.status_code, None


async def _seed_agent(factory: async_sessionmaker, root_path: Path) -> tuple[str, str]:
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    root = (
        root_path
        / ".octopus"
        / "organizations"
        / org_id
        / "workspaces"
        / "agents"
        / "agent"
        / "instructions"
    )
    root.mkdir(parents=True)
    root.joinpath("SOUL.md").write_text("# Soul\nBe useful.", encoding="utf-8")
    root.joinpath("MEMORY.md").write_text("# Memory\n", encoding="utf-8")
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key="instructions-org",
                name="Instructions Org",
                issue_prefix=org_id[:6].upper(),
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Instruction Agent",
                workspace_key="agent",
                role="individual_contributor",
                agent_runtime_type="codex_local",
                agent_runtime_config={
                    "instructionsBundleMode": "managed",
                    "instructionsRootPath": str(root),
                    "instructionsEntryFile": "SOUL.md",
                    "instructionsFilePath": str(root / "SOUL.md"),
                },
            )
        )
        await session.commit()
    return org_id, agent_id


async def test_agent_instructions_bundle_read_write_delete_and_activity(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, root_path = app
    org_id, agent_id = await _seed_agent(factory, root_path)

    bundle_code, bundle = await _request(
        application, "GET", f"/api/agents/{agent_id}/instructions-bundle"
    )
    assert bundle_code == 200
    assert bundle["agentId"] == agent_id
    assert bundle["mode"] == "managed"
    assert bundle["entryFile"] == "SOUL.md"
    assert [file["path"] for file in bundle["files"]] == DEFAULT_INSTRUCTIONS_FILES

    file_code, file_detail = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/instructions-bundle/file",
        params={"path": "SOUL.md"},
    )
    assert file_code == 200
    assert file_detail["content"] == "# Soul\nBe useful."
    assert file_detail["isEntryFile"] is True

    put_code, updated_file = await _request(
        application,
        "PUT",
        f"/api/agents/{agent_id}/instructions-bundle/file",
        json_body={"path": "notes/PLAYBOOK.md", "content": "# Playbook"},
    )
    assert put_code == 200
    assert updated_file["path"] == "notes/PLAYBOOK.md"
    assert updated_file["content"] == "# Playbook"

    delete_code, deleted_bundle = await _request(
        application,
        "DELETE",
        f"/api/agents/{agent_id}/instructions-bundle/file",
        params={"path": "notes/PLAYBOOK.md"},
    )
    assert delete_code == 200
    assert "notes/PLAYBOOK.md" not in [file["path"] for file in deleted_bundle["files"]]

    async with factory() as session:
        actions = [
            row.action
            for row in (
                await session.execute(
                    select(ActivityLog).where(ActivityLog.org_id == org_id)
                )
            )
            .scalars()
            .all()
        ]
    assert actions == [
        "agent.instructions_file_updated",
        "agent.instructions_file_deleted",
    ]


async def test_agent_instructions_bundle_edit_records_config_revision(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    """Editing the instructions bundle config must record an agent config
    revision.

    Regression: instruction edits persisted ``agent_runtime_config`` through the
    database-layer ``update_agent`` directly, bypassing the service-layer
    revision recording, so the config version history stayed empty.
    """

    application, factory, root_path = app
    org_id, agent_id = await _seed_agent(factory, root_path)

    before_code, before = await _request(
        application, "GET", f"/api/agents/{agent_id}/config-revisions"
    )
    assert before_code == 200
    assert before == []

    patch_code, _bundle = await _request(
        application,
        "PATCH",
        f"/api/agents/{agent_id}/instructions-bundle",
        json_body={"entryFile": "MEMORY.md"},
    )
    assert patch_code == 200

    after_code, revisions = await _request(
        application, "GET", f"/api/agents/{agent_id}/config-revisions"
    )
    assert after_code == 200
    assert len(revisions) == 1
    assert revisions[0]["source"] == "instructions_bundle_patch"
    assert "agentRuntimeConfig" in revisions[0]["changedKeys"]


async def test_agent_instructions_file_read_reconciles_legacy_prompt_template(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, _ = app
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key="legacy-instructions-org",
                name="Legacy Instructions Org",
                issue_prefix=org_id[:6].upper(),
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Legacy Instructions Agent",
                workspace_key="legacy-agent",
                role="individual_contributor",
                agent_runtime_type="codex_local",
                agent_runtime_config={
                    "instructionsBundleMode": "managed",
                    "promptTemplate": "# Legacy Soul\nKeep context durable.",
                },
            )
        )
        await session.commit()

    file_code, file_detail = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/instructions-bundle/file",
        params={"path": "SOUL.md"},
    )
    bundle_code, bundle = await _request(
        application, "GET", f"/api/agents/{agent_id}/instructions-bundle"
    )

    assert file_code == 200
    assert file_detail["content"] == "# Legacy Soul\nKeep context durable."
    assert bundle_code == 200
    assert bundle["mode"] == "managed"
    assert [file["path"] for file in bundle["files"]] == DEFAULT_INSTRUCTIONS_FILES


async def test_agent_instructions_bundle_rehomes_stale_managed_root(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, root_path = app
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    stale_root = root_path / "old-home" / "agents" / "rehomed-agent" / "instructions"
    stale_root.mkdir(parents=True)
    stale_root.joinpath("SOUL.md").write_text("# Stale Soul\n", encoding="utf-8")
    stale_root.joinpath("MEMORY.md").write_text("Carry this forward.", encoding="utf-8")
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key="rehome-instructions-org",
                name="Rehome Instructions Org",
                issue_prefix=org_id[:6].upper(),
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Rehomed Agent",
                workspace_key="rehomed-agent",
                role="individual_contributor",
                agent_runtime_type="codex_local",
                agent_runtime_config={
                    "instructionsBundleMode": "managed",
                    "instructionsRootPath": str(stale_root),
                    "instructionsEntryFile": "SOUL.md",
                    "instructionsFilePath": str(stale_root / "SOUL.md"),
                },
            )
        )
        await session.commit()

    bundle_code, bundle = await _request(
        application, "GET", f"/api/agents/{agent_id}/instructions-bundle"
    )
    async with factory() as session:
        row = await session.get(Agent, agent_id)
        assert row is not None
        config = row.agent_runtime_config

    expected_root = (
        resolve_octopus_instance_root()
        / "organizations"
        / org_id
        / "workspaces"
        / "agents"
        / "rehomed-agent"
        / "instructions"
    ).resolve()
    assert bundle_code == 200
    assert bundle["rootPath"] == str(expected_root)
    assert config["instructionsRootPath"] == str(expected_root)
    assert config["instructionsFilePath"] == str(expected_root / "SOUL.md")
    assert (expected_root / "SOUL.md").read_text(encoding="utf-8") == "# Stale Soul\n"
    assert (expected_root / "MEMORY.md").read_text(
        encoding="utf-8"
    ) == "Carry this forward."


async def test_agent_instructions_managed_root_preserves_workspace_key(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, _ = app
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key="workspace-key-org",
                name="Workspace Key Org",
                issue_prefix=org_id[:6].upper(),
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="CEO 1",
                workspace_key="ceo-1--623d0e91",
                role="individual_contributor",
                agent_runtime_type="codex_local",
                agent_runtime_config={
                    "instructionsBundleMode": "managed",
                    "promptTemplate": "# Soul",
                },
            )
        )
        await session.commit()

    bundle_code, bundle = await _request(
        application, "GET", f"/api/agents/{agent_id}/instructions-bundle"
    )

    assert bundle_code == 200
    assert "/agents/ceo-1--623d0e91/instructions" in bundle["rootPath"].replace(
        "\\", "/"
    )


async def test_agent_instructions_bundle_reconciles_empty_default_files(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, root_path = app
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    root = (
        root_path
        / ".octopus"
        / "organizations"
        / org_id
        / "workspaces"
        / "agents"
        / "ceo"
        / "instructions"
    )
    root.mkdir(parents=True)
    root.joinpath("SOUL.md").write_text("", encoding="utf-8")
    root.joinpath("MEMORY.md").write_text("Keep this custom memory.", encoding="utf-8")
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key="empty-instructions-org",
                name="Empty Instructions Org",
                issue_prefix=org_id[:6].upper(),
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="CEO",
                workspace_key="ceo",
                role="ceo",
                agent_runtime_type="codex_local",
                agent_runtime_config={
                    "instructionsBundleMode": "managed",
                    "instructionsRootPath": str(root),
                    "instructionsEntryFile": "SOUL.md",
                    "instructionsFilePath": str(root / "SOUL.md"),
                },
            )
        )
        await session.commit()

    soul_code, soul_detail = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/instructions-bundle/file",
        params={"path": "SOUL.md"},
    )
    memory_code, memory_detail = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/instructions-bundle/file",
        params={"path": "MEMORY.md"},
    )
    bundle_code, bundle = await _request(
        application, "GET", f"/api/agents/{agent_id}/instructions-bundle"
    )

    assert soul_code == 200
    assert "# SOUL.md -- CEO Persona" in soul_detail["content"]
    assert memory_code == 200
    assert memory_detail["content"] == "Keep this custom memory."
    assert bundle_code == 200
    assert [file["path"] for file in bundle["files"]] == DEFAULT_INSTRUCTIONS_FILES


async def test_agent_instructions_bundle_materializes_for_process_agent_on_first_read(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, _root_path = app
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key="process-instructions-org",
                name="Process Instructions Org",
                issue_prefix=org_id[:6].upper(),
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="CEO",
                workspace_key="ceo",
                role="ceo",
                agent_runtime_type="process",
                agent_runtime_config={},
            )
        )
        await session.commit()

    bundle_code, bundle = await _request(
        application, "GET", f"/api/agents/{agent_id}/instructions-bundle"
    )
    soul_code, soul_detail = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/instructions-bundle/file",
        params={"path": "SOUL.md"},
    )

    assert bundle_code == 200
    assert bundle["mode"] == "managed"
    assert [file["path"] for file in bundle["files"]] == DEFAULT_INSTRUCTIONS_FILES
    assert soul_code == 200
    assert "# SOUL.md -- CEO Persona" in soul_detail["content"]


async def test_agent_instructions_path_update_and_path_guard(
    app: tuple[FastAPI, async_sessionmaker, Path],
) -> None:
    application, factory, root_path = app
    _, agent_id = await _seed_agent(factory, root_path)
    cwd = root_path / "workspace"
    cwd.mkdir()
    cwd.joinpath("AGENTS.md").write_text("# Agents", encoding="utf-8")

    patch_code, result = await _request(
        application,
        "PATCH",
        f"/api/agents/{agent_id}/instructions-path",
        json_body={
            "path": "AGENTS.md",
            "agentRuntimeConfigKey": "instructionsFilePath",
        },
    )
    assert patch_code == 422
    assert "cwd" in result["detail"]

    async with factory() as session:
        agent = await session.get(Agent, agent_id)
        assert agent is not None
        agent.agent_runtime_config = {**agent.agent_runtime_config, "cwd": str(cwd)}
        await session.commit()

    patch_code, result = await _request(
        application,
        "PATCH",
        f"/api/agents/{agent_id}/instructions-path",
        json_body={
            "path": "AGENTS.md",
            "agentRuntimeConfigKey": "instructionsFilePath",
        },
    )
    assert patch_code == 200
    assert result["path"] == str((cwd / "AGENTS.md").resolve())

    bad_file_code, bad_file = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/instructions-bundle/file",
        params={"path": "../secret.md"},
    )
    assert bad_file_code == 422
    assert "path" in bad_file["detail"]
