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
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker]]:
    monkeypatch.chdir(tmp_path)
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


async def _seed_agent(factory: async_sessionmaker, tmp_path: Path) -> tuple[str, str]:
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    root = (
        tmp_path
        / ".octopus"
        / "workspaces"
        / f"org_{org_id}"
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
    app: tuple[FastAPI, async_sessionmaker], tmp_path: Path
) -> None:
    application, factory = app
    org_id, agent_id = await _seed_agent(factory, tmp_path)

    bundle_code, bundle = await _request(
        application, "GET", f"/api/agents/{agent_id}/instructions-bundle"
    )
    assert bundle_code == 200
    assert bundle["agentId"] == agent_id
    assert bundle["mode"] == "managed"
    assert bundle["entryFile"] == "SOUL.md"
    assert [file["path"] for file in bundle["files"]] == ["MEMORY.md", "SOUL.md"]

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


async def test_agent_instructions_path_update_and_path_guard(
    app: tuple[FastAPI, async_sessionmaker], tmp_path: Path
) -> None:
    application, factory = app
    _, agent_id = await _seed_agent(factory, tmp_path)
    cwd = tmp_path / "workspace"
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
