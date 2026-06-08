from __future__ import annotations

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
from packages.database.schema import ActivityLog, Base, Organization
from packages.runtimes.context_env import apply_runtime_context_env
from packages.runtimes.instructions import runtime_prompt_from_config
from packages.runtimes.types import RuntimeExecutionContext
from server.app import create_app


def test_step24_agent_memory_api_paths_are_exported() -> None:
    from packages.shared.api_paths import agents

    assert agents.AGENT_MEMORY_FILES_PATH == "/api/agents/{id}/memory/files"
    assert agents.AGENT_MEMORY_FILE_PATH == "/api/agents/{id}/memory/file"


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker]]:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "octopus-home"))
    monkeypatch.setenv("OCTOPUS_INSTANCE_ID", "test")
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
    json: dict | None = None,
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json)
    return response.status_code, response.json()


async def _noop_on_log(stream: str, chunk: str) -> None:
    return None


async def _seed_org_and_agent(factory: async_sessionmaker) -> tuple[str, str]:
    from server.services.agents import AgentService

    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"step24-{uuid.uuid4().hex[:8]}",
                name="Step 24",
                issue_prefix="MRY",
            )
        )
        await session.flush()
        agent = await AgentService(session).create_agent(
            org_id,
            {"name": "Memory Agent", "agentRuntimeType": "codex_local"},
            actor_type="board",
            actor_id="local-board",
        )
        await session.commit()
    return org_id, agent["id"]


def test_runtime_prompt_loads_sibling_tacit_memory(tmp_path: Path) -> None:
    instructions_root = tmp_path / "agent-home" / "instructions"
    instructions_root.mkdir(parents=True)
    soul = instructions_root / "SOUL.md"
    soul.write_text("Base operating instructions.", encoding="utf-8")
    memory = instructions_root / "MEMORY.md"
    memory.write_text("Prefer concise status updates.", encoding="utf-8")

    prompt = runtime_prompt_from_config(
        {
            "instructionsFilePath": str(soul),
            "_octopus": {"agentHome": str(tmp_path / "agent-home")},
        }
    )

    assert "Base operating instructions." in prompt
    assert "## Tacit Agent Memory" in prompt
    assert "Prefer concise status updates." in prompt
    assert "## Agent Memory Contract" in prompt
    assert "$AGENT_HOME/memory/YYYY-MM-DD.md" in prompt
    assert "$AGENT_HOME/life/" in prompt
    assert "Do not assume `$HOME` is long-term memory" in prompt


def test_runtime_prompt_does_not_auto_load_daily_or_life_memory(
    tmp_path: Path,
) -> None:
    agent_home = tmp_path / "agent-home"
    instructions_root = agent_home / "instructions"
    daily_root = agent_home / "memory"
    life_root = agent_home / "life"
    instructions_root.mkdir(parents=True)
    daily_root.mkdir()
    life_root.mkdir()
    soul = instructions_root / "SOUL.md"
    soul.write_text("Base instructions.", encoding="utf-8")
    instructions_root.joinpath("MEMORY.md").write_text(
        "Stable memory.", encoding="utf-8"
    )
    daily_root.joinpath("2026-06-08.md").write_text(
        "Daily note should stay lazy.", encoding="utf-8"
    )
    life_root.joinpath("profile.md").write_text(
        "Life note should stay lazy.", encoding="utf-8"
    )

    prompt = runtime_prompt_from_config(
        {
            "instructionsFilePath": str(soul),
            "_octopus": {"agentHome": str(agent_home)},
        }
    )

    assert "Stable memory." in prompt
    assert "Daily note should stay lazy." not in prompt
    assert "Life note should stay lazy." not in prompt


def test_runtime_prompt_can_load_tacit_memory_from_octopus_instructions_dir(
    tmp_path: Path,
) -> None:
    instructions_root = tmp_path / "agent-home" / "instructions"
    instructions_root.mkdir(parents=True)
    instructions_root.joinpath("MEMORY.md").write_text(
        "Fallback memory path works.", encoding="utf-8"
    )

    prompt = runtime_prompt_from_config(
        {
            "_octopus": {
                "agentHome": str(tmp_path / "agent-home"),
                "agentInstructionsDir": str(instructions_root),
            }
        }
    )

    assert "Fallback memory path works." in prompt


def test_runtime_context_env_falls_back_to_agent_memory_paths_from_octopus() -> None:
    env: dict[str, str] = {}
    apply_runtime_context_env(
        env,
        RuntimeExecutionContext(
            run_id="run-24",
            agent_id="agent-24",
            org_id="org-24",
            agent_name="Memory Agent",
            config={
                "_octopus": {
                    "agentHome": "D:/agents/agent-24",
                    "agentInstructionsDir": "D:/agents/agent-24/instructions",
                    "agentMemoryDir": "D:/agents/agent-24/memory",
                    "agentLifeDir": "D:/agents/agent-24/life",
                    "agentSkillsRootPath": "D:/agents/agent-24/skills",
                }
            },
            workspace={"rudderWorkspace": {"cwd": "D:/workspaces/task-24"}},
            on_log=_noop_on_log,
        ),
    )

    assert env["AGENT_HOME"] == "D:/agents/agent-24"
    assert env["RUDDER_AGENT_ROOT"] == "D:/agents/agent-24"
    assert env["RUDDER_AGENT_INSTRUCTIONS_DIR"] == "D:/agents/agent-24/instructions"
    assert env["RUDDER_AGENT_MEMORY_DIR"] == "D:/agents/agent-24/memory"
    assert env["RUDDER_AGENT_LIFE_DIR"] == "D:/agents/agent-24/life"
    assert env["RUDDER_AGENT_SKILLS_DIR"] == "D:/agents/agent-24/skills"


async def test_agent_memory_routes_write_read_list_and_delete_files(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    _, agent_id = await _seed_org_and_agent(factory)

    write_code, written = await _request(
        application,
        "PUT",
        f"/api/agents/{agent_id}/memory/file",
        json={
            "layer": "memory",
            "path": "2026-06-08.md",
            "content": "Remember the API contract.",
        },
    )
    list_code, listed = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/memory/files?layer=memory",
    )
    read_code, read = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/memory/file?layer=memory&path=2026-06-08.md",
    )
    delete_code, deleted = await _request(
        application,
        "DELETE",
        f"/api/agents/{agent_id}/memory/file?layer=memory&path=2026-06-08.md",
    )

    assert write_code == 200
    assert written["layer"] == "memory"
    assert written["filePath"] == "2026-06-08.md"
    assert written["content"] == "Remember the API contract."
    assert list_code == 200
    assert listed["entries"][0]["path"] == "2026-06-08.md"
    assert read_code == 200
    assert read["content"] == "Remember the API contract."
    assert delete_code == 200
    assert deleted["entries"] == []

    async with factory() as session:
        actions = [
            row.action for row in (await session.execute(select(ActivityLog))).scalars()
        ]
    assert "agent.memory_file_updated" in actions
    assert "agent.memory_file_deleted" in actions


async def test_agent_life_routes_support_nested_files(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    _, agent_id = await _seed_org_and_agent(factory)

    write_code, written = await _request(
        application,
        "PUT",
        f"/api/agents/{agent_id}/memory/file",
        json={
            "layer": "life",
            "path": "projects/octopus.md",
            "content": "Octopus context lives here.",
        },
    )
    root_code, root = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/memory/files?layer=life",
    )
    nested_code, nested = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/memory/files?layer=life&path=projects",
    )

    assert write_code == 200
    assert written["layer"] == "life"
    assert written["filePath"] == "projects/octopus.md"
    assert root_code == 200
    assert root["entries"][0]["isDirectory"] is True
    assert root["entries"][0]["path"] == "projects"
    assert nested_code == 200
    assert nested["entries"][0]["path"] == "projects/octopus.md"


async def test_agent_memory_routes_reject_path_escape_and_unknown_layer(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    _, agent_id = await _seed_org_and_agent(factory)

    escape_code, escape = await _request(
        application,
        "PUT",
        f"/api/agents/{agent_id}/memory/file",
        json={"layer": "memory", "path": "../escape.md", "content": "bad"},
    )
    layer_code, layer = await _request(
        application,
        "GET",
        f"/api/agents/{agent_id}/memory/files?layer=secrets",
    )

    assert escape_code == 422
    assert "stay within" in escape["detail"]
    assert layer_code == 422
    assert "layer" in layer["detail"]
