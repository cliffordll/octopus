from __future__ import annotations

import importlib
import importlib.util
from collections.abc import AsyncIterator
from datetime import UTC, datetime
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
from packages.database.schema import (
    Agent,
    Approval,
    Base,
    ChatConversation,
    ChatMessage,
    Issue,
    Organization,
)
from server.app import create_app


def test_step16_messenger_contract_exposes_thread_boundary() -> None:
    modules = (
        "packages.shared.api_paths.messenger",
        "packages.shared.constants.messenger",
        "packages.shared.types.messenger",
    )
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    paths = importlib.import_module("packages.shared.api_paths.messenger")
    constants = importlib.import_module("packages.shared.constants.messenger")

    assert paths.ORG_MESSENGER_THREADS_PATH == "/api/orgs/{orgId}/messenger/threads"
    assert (
        paths.ORG_MESSENGER_THREAD_READ_PATH
        == "/api/orgs/{orgId}/messenger/threads/{threadKey}/read"
    )
    assert constants.MESSENGER_THREAD_KINDS == (
        "chat",
        "issues",
        "approvals",
        "failed-runs",
        "budget-alerts",
        "join-requests",
    )
    assert constants.MESSENGER_SYSTEM_THREAD_KINDS == (
        "failed-runs",
        "budget-alerts",
        "join-requests",
    )


def test_step16_messenger_thread_user_state_table_is_registered() -> None:
    schema = importlib.import_module("packages.database.schema")
    assert isinstance(schema.MessengerThreadUserState.__table__, Table)
    assert schema.MessengerThreadUserState.__tablename__ == (
        "messenger_thread_user_states"
    )
    assert "messenger_thread_user_states" in {
        table.name for table in Base.metadata.sorted_tables
    }


async def test_upgrade_to_head_creates_messenger_thread_user_state_table(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "step16-messenger-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master where type='table' and name = "
                    "'messenger_thread_user_states'"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()
    assert names == {"messenger_thread_user_states"}


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
                id=org_id,
                url_key=f"messenger-{org_id[:8]}",
                name="Step 16 Messenger",
                issue_prefix="MSG",
            )
        )
        await session.commit()
    return org_id


async def test_messenger_threads_chat_detail_and_read_state(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    conversation_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            ChatConversation(
                id=conversation_id,
                org_id=org_id,
                title="Chat preview",
                status="active",
                summary="Fallback summary",
                created_by_user_id="local-board",
            )
        )
        session.add(
            ChatMessage(
                org_id=org_id,
                conversation_id=conversation_id,
                role="assistant",
                kind="message",
                status="completed",
                body="## 需求\n把 Agent 的处理流程规范化",
            )
        )
        await session.commit()

    list_code, threads = await _request(
        application, "GET", f"/api/orgs/{org_id}/messenger/threads"
    )
    chat_thread = next(
        item for item in threads if item["threadKey"] == f"chat:{conversation_id}"
    )
    assert list_code == 200
    assert chat_thread["kind"] == "chat"
    assert chat_thread["preview"] == "需求: 把 Agent 的处理流程规范化"
    assert chat_thread["href"] == f"/messenger/chat/{conversation_id}"

    detail_code, detail = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/messenger/chat/{conversation_id}",
    )
    assert detail_code == 200
    assert detail["conversation"]["id"] == conversation_id
    assert detail["messages"][0]["body"].startswith("## 需求")

    read_code, read_state = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/messenger/threads/chat:{conversation_id}/read",
    )
    assert read_code == 200
    assert read_state["threadKey"] == f"chat:{conversation_id}"
    assert read_state["lastReadAt"] is not None


async def test_mark_chat_thread_read_with_routed_agent_and_last_message(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    """Marking a chat thread read must not crash when the conversation carries a
    routed agent and a ``last_message_at`` timestamp.

    Regression: SQLite returns naive datetimes for ``last_message_at`` while the
    user state ``last_read_at`` is set to ``datetime.now(UTC)`` (aware). The
    unread check compared the two directly and raised ``TypeError`` (HTTP 500).
    """

    application, factory = app
    org_id = await _seed_org(factory)
    agent_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(Agent(id=agent_id, org_id=org_id, name="Worker"))
        session.add(
            ChatConversation(
                id=conversation_id,
                org_id=org_id,
                title="Routed chat",
                status="active",
                routed_agent_id=agent_id,
                preferred_agent_id=agent_id,
                last_message_at=datetime.now(UTC),
                created_by_user_id="local-board",
            )
        )
        session.add(
            ChatMessage(
                org_id=org_id,
                conversation_id=conversation_id,
                role="assistant",
                kind="message",
                status="completed",
                body="hello",
            )
        )
        await session.commit()

    read_code, read_state = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/messenger/threads/chat:{conversation_id}/read",
    )
    assert read_code == 200
    assert read_state["threadKey"] == f"chat:{conversation_id}"
    assert read_state["lastReadAt"] is not None


async def test_messenger_issue_approval_and_system_threads(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = await _seed_org(factory)
    issue_id = str(uuid.uuid4())
    approval_id = str(uuid.uuid4())

    async with factory() as session:
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Assigned issue",
                status="todo",
                priority="high",
                assignee_user_id="local-board",
                identifier="MSG-1",
            )
        )
        session.add(
            Approval(
                id=approval_id,
                org_id=org_id,
                type="chat_issue_creation",
                status="pending",
                requested_by_user_id="local-board",
                payload={
                    "proposedIssue": {
                        "title": "Fix approval copy",
                        "description": "Render readable labels.",
                    }
                },
            )
        )
        await session.commit()

    list_code, threads = await _request(
        application, "GET", f"/api/orgs/{org_id}/messenger/threads"
    )
    assert list_code == 200
    assert {thread["threadKey"] for thread in threads} >= {"issues", "approvals"}

    issues_code, issues = await _request(
        application, "GET", f"/api/orgs/{org_id}/messenger/issues"
    )
    assert issues_code == 200
    assert issues["summary"]["threadKey"] == "issues"
    assert issues["detail"]["items"][0]["issueId"] == issue_id
    assert issues["detail"]["items"][0]["issueIdentifier"] == "MSG-1"

    approvals_code, approvals = await _request(
        application, "GET", f"/api/orgs/{org_id}/messenger/approvals"
    )
    assert approvals_code == 200
    assert approvals["summary"]["threadKey"] == "approvals"
    assert approvals["detail"]["items"][0]["approval"]["id"] == approval_id
    assert "Fix approval copy" in approvals["detail"]["items"][0]["preview"]

    read_code, read_state = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/messenger/threads/issues/read",
        json={"lastReadAt": "2026-05-29T00:00:00+00:00"},
    )
    assert read_code == 200
    assert read_state["threadKey"] == "issues"
    assert read_state["lastReadAt"].startswith("2026-05-29T00:00:00")

    system_code, system = await _request(
        application,
        "GET",
        f"/api/orgs/{org_id}/messenger/system/failed-runs",
    )
    assert system_code == 200
    assert system["summary"]["threadKey"] == "failed-runs"
    assert system["detail"]["items"] == []
