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
from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.migrations.runner import upgrade_to_head
from packages.database.schema import Agent, Base, Organization
from server.app import create_app


def test_step16_chat_contract_exposes_crud_and_user_state_boundary() -> None:
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
    assert paths.CHAT_USER_STATE_PATH == "/api/chats/{id}/user-state"
    assert constants.CHAT_CONTEXT_ENTITY_TYPES == ("issue", "project", "agent")
    assert constants.CHAT_CONVERSATION_STATUSES == ("active", "resolved", "archived")
    assert validators.validate_update_chat_conversation(
        {"status": "resolved", "title": "  Follow up  "}
    ) == {"status": "resolved", "title": "Follow up"}
    assert validators.validate_update_chat_conversation_user_state(
        {"pinned": True, "unread": False}
    ) == {"pinned": True, "unread": False}


def test_step16_chat_user_state_table_is_registered() -> None:
    schema = importlib.import_module("packages.database.schema")
    assert isinstance(schema.ChatConversation.__table__, Table)
    assert schema.ChatConversationUserState.__tablename__ == (
        "chat_conversation_user_states"
    )
    assert "chat_conversation_user_states" in {
        table.name for table in Base.metadata.sorted_tables
    }


async def test_upgrade_to_head_creates_chat_user_state_table(tmp_path: Path) -> None:
    db_path = tmp_path / "step16-chat-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master where type='table' and name = "
                    "'chat_conversation_user_states'"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()
    assert names == {"chat_conversation_user_states"}


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


async def _seed_org(factory: async_sessionmaker, name: str = "Step 16 Chat") -> str:
    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=name.lower().replace(" ", "-"),
                name=name,
                issue_prefix="CHT",
            )
        )
        await session.commit()
    return org_id


async def test_chat_crud_filters_and_user_state(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)

    alpha_code, alpha = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json={"title": "Alpha plan", "summary": "first"},
    )
    beta_code, beta = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json={"title": "Beta archive", "summary": "second"},
    )
    assert alpha_code == 201
    assert beta_code == 201

    update_code, updated_beta = await _request(
        application,
        "PATCH",
        f"/api/chats/{beta['id']}",
        json={"status": "resolved", "title": "Resolved beta"},
    )
    assert update_code == 200
    assert updated_beta["status"] == "resolved"
    assert updated_beta["title"] == "Resolved beta"
    assert updated_beta["resolvedAt"] is not None

    default_code, default_rows = await _request(
        application, "GET", f"/api/orgs/{org_id}/chats"
    )
    all_code, all_rows = await _request(
        application, "GET", f"/api/orgs/{org_id}/chats?status=all"
    )
    search_code, search_rows = await _request(
        application, "GET", f"/api/orgs/{org_id}/chats?status=all&q=alpha"
    )
    assert default_code == 200
    assert [row["id"] for row in default_rows] == [alpha["id"]]
    assert all_code == 200
    assert {row["id"] for row in all_rows} == {alpha["id"], beta["id"]}
    assert search_code == 200
    assert [row["id"] for row in search_rows] == [alpha["id"]]

    state_code, state = await _request(
        application,
        "PATCH",
        f"/api/chats/{alpha['id']}/user-state",
        json={"pinned": True, "unread": False},
    )
    assert state_code == 200
    assert state["isPinned"] is True
    assert state["isUnread"] is False
    assert state["unreadCount"] == 0

    detail_code, detail = await _request(
        application, "GET", f"/api/chats/{alpha['id']}"
    )
    assert detail_code == 200
    assert detail["isPinned"] is True
    assert detail["isUnread"] is False
    assert detail["lastReadAt"] is not None
    assert detail["latestReplyPreview"] is None


async def test_chat_runtime_descriptor_uses_selected_agent(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    agent_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Codex CEO",
                role="ceo",
                agent_runtime_type="codex_local",
                agent_runtime_config={"model": "gpt-5-codex"},
            )
        )
        await session.commit()

    create_code, chat = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json={"title": "Agent chat", "preferredAgentId": agent_id},
    )

    assert create_code == 201
    assert chat["chatRuntime"] == {
        "sourceType": "agent",
        "sourceLabel": "Codex CEO",
        "runtimeAgentId": agent_id,
        "agentRuntimeType": "codex_local",
        "model": "gpt-5-codex",
        "available": True,
        "error": None,
    }


async def test_chat_create_normalizes_legacy_org_issue_creation_mode(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key="legacy-chat-mode",
                name="Legacy Chat Mode",
                issue_prefix="LCM",
                default_chat_issue_creation_mode="manual",
            )
        )
        await session.commit()

    create_code, chat = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json={"title": "Legacy mode chat"},
    )

    assert create_code == 201
    assert chat["issueCreationMode"] == "manual_approval"
