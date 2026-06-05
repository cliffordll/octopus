from __future__ import annotations

import importlib
import importlib.util
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.migrations.runner import upgrade_to_head
from packages.database.schema import Base, Organization
from server.app import create_app


def test_chat_contract_modules_define_agent_conversation_boundary() -> None:
    modules = (
        "packages.shared.api_paths.chats",
        "packages.shared.constants.chat",
        "packages.shared.types.chat",
        "packages.shared.validators.chat",
    )
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    paths = importlib.import_module("packages.shared.api_paths.chats")
    constants = importlib.import_module("packages.shared.constants.chat")
    validators = importlib.import_module("packages.shared.validators.chat")

    assert paths.ORG_CHAT_LIST_PATH == "/api/orgs/{orgId}/chats"
    assert paths.CHAT_DETAIL_PATH == "/api/chats/{id}"
    assert paths.CHAT_MESSAGES_PATH == "/api/chats/{id}/messages"
    assert constants.CHAT_CONVERSATION_STATUSES == ("active", "resolved", "archived")
    assert constants.CHAT_MESSAGE_ROLES == ("user", "assistant", "system")
    assert constants.CHAT_MESSAGE_STATUSES == (
        "streaming",
        "completed",
        "stopped",
        "failed",
        "interrupted",
    )
    assert validators.validate_add_chat_message({"body": "  Execute task  "}) == {
        "body": "Execute task"
    }


def test_chat_tables_match_step11f_boundary() -> None:
    schema = importlib.import_module("packages.database.schema")
    assert isinstance(schema.ChatConversation.__table__, Table)
    assert schema.ChatConversation.__tablename__ == "chat_conversations"
    assert schema.ChatMessage.__tablename__ == "chat_messages"
    assert {"chat_conversations", "chat_messages"}.issubset(
        {table.name for table in Base.metadata.sorted_tables}
    )


async def test_upgrade_to_head_creates_chat_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "step11f-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master where type='table' and name in "
                    "('chat_conversations', 'chat_messages')"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()
    assert names == {"chat_conversations", "chat_messages"}


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
    monkeypatch: pytest.MonkeyPatch, session_factory: async_sessionmaker
) -> FastAPI:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    application = create_app()
    application.state.session_factory = session_factory
    return application


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path, json=json)
    return response.status_code, response.json()


async def _seed_org(session_factory: async_sessionmaker) -> str:
    async with session_factory() as session:
        org = Organization(
            id=str(uuid.uuid4()),
            url_key="chat-loop",
            name="Chat Loop",
            issue_prefix="CHT",
        )
        session.add(org)
        await session.commit()
        return org.id


async def test_chat_message_invokes_selected_codex_agent_and_persists_reply(
    app: FastAPI,
    session_factory: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}
    org_root = tmp_path / "org-workspace"
    monkeypatch.setattr(
        "server.services.workspaces.organization_workspace_root",
        lambda org_id: org_root,
    )

    class FakeCodexProcess:
        returncode = 0

        async def communicate(
            self, payload: bytes | None = None
        ) -> tuple[bytes, bytes]:
            captured["prompt"] = payload
            return (
                (
                    '{"type":"thread.started","thread_id":"chat-thread"}\n'
                    '{"type":"item.completed","item":{"type":"agent_message",'
                    '"text":"Reply from Codex"}}\n'
                    '{"type":"turn.completed","usage":{"input_tokens":1,'
                    '"cached_input_tokens":0,"output_tokens":2}}\n'
                ).encode(),
                b"",
            )

        def kill(self) -> None:
            raise AssertionError("successful Codex process must not be killed")

    async def fake_create_subprocess_exec(
        *args: str, **kwargs: Any
    ) -> FakeCodexProcess:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeCodexProcess()

    monkeypatch.setattr(
        "packages.runtimes.codex_local.runner.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    org_id = await _seed_org(session_factory)
    _, agent = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/agents",
        json={
            "name": "Chat Codex",
            "agentRuntimeType": "codex_local",
            "agentRuntimeConfig": {"command": "codex-test"},
        },
    )
    create_code, conversation = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json={"title": "Implement feature", "preferredAgentId": agent["id"]},
    )
    assert create_code == 201
    assert conversation["preferredAgentId"] == agent["id"]

    send_code, created = await _request(
        app,
        "POST",
        f"/api/chats/{conversation['id']}/messages",
        json={"body": "Implement the next task."},
    )
    assert send_code == 201
    # Prompt now mirrors upstream `chat-assistant.helpers.ts:154-208 buildPrompt`:
    # JSON envelope including conversation metadata and recent message history
    # so multi-turn context is preserved. The latest user body must still be
    # carried in `recentMessages` for the LLM to act on.
    prompt_bytes = captured["prompt"]
    assert isinstance(prompt_bytes, bytes)
    prompt = prompt_bytes.decode("utf-8")
    assert "Reply to the latest user message only" in prompt
    assert "## Runtime Tool Capability" in prompt
    marker = "Conversation input:"
    assert marker in prompt
    envelope_payload = prompt.split(marker, 1)[1].split(
        "## Runtime Tool Capability", 1
    )[0]
    envelope = json.loads(envelope_payload.strip())
    assert envelope["conversation"]["id"] == conversation["id"]
    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["cwd"] == str(org_root)
    env = kwargs["env"]
    assert isinstance(env, dict)
    assert env["RUDDER_ORG_ARTIFACTS_DIR"] == str(org_root / "artifacts")
    assert "RUDDER_CONVERSATION_ARTIFACTS_DIR" not in env
    assert "RUDDER_ISSUE_ARTIFACTS_DIR" not in env
    assert "RUDDER_RUN_ARTIFACTS_DIR" not in env
    assert envelope["recentMessages"][-1] == {
        "id": envelope["recentMessages"][-1]["id"],
        "role": "user",
        "kind": "message",
        "status": "completed",
        "body": "Implement the next task.",
        "structuredPayload": None,
    }
    assert [(message["role"], message["body"]) for message in created["messages"]] == [
        ("user", "Implement the next task."),
        ("assistant", "Reply from Codex"),
    ]
    assert created["messages"][1]["replyingAgentId"] == agent["id"]

    list_code, messages = await _request(
        app, "GET", f"/api/chats/{conversation['id']}/messages"
    )
    assert list_code == 200
    assert [message["id"] for message in messages] == [
        message["id"] for message in created["messages"]
    ]
