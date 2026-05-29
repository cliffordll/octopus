from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Agent, Base, Organization
from packages.runtimes.types import RuntimeExecutionContext, RuntimeExecutionResult
from server.app import create_app


class FailingChatAdapter:
    type = "failing_chat"

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        if context.on_stream_event is not None:
            await context.on_stream_event(
                {"type": "assistant_delta", "delta": "partial reply"}
            )
        return RuntimeExecutionResult(
            exit_code=1,
            error_message="adapter exploded",
            result_json={"summary": ""},
        )


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


async def _request_json(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json_body)
    return response.status_code, response.json()


async def _request_text(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json_body: dict[str, Any] | None = None,
) -> tuple[int, str, str]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json_body)
    return response.status_code, response.headers["content-type"], response.text


async def _seed_org_agent(factory: async_sessionmaker) -> tuple[str, str]:
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"step18-{org_id[:8]}",
                name="Step 18 Chat",
                issue_prefix="C18",
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Failing Chat Agent",
                agent_runtime_type="failing_chat",
                agent_runtime_config={},
            )
        )
        await session.commit()
    return org_id, agent_id


async def _create_chat(
    application: FastAPI, org_id: str, agent_id: str
) -> dict[str, Any]:
    code, chat = await _request_json(
        application,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json_body={"title": "Failure boundary", "preferredAgentId": agent_id},
    )
    assert code == 201
    return chat


async def test_runtime_failure_keeps_user_message(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    monkeypatch.setattr(
        chat_service_module, "get_runtime_adapter", lambda _: FailingChatAdapter()
    )
    chat = await _create_chat(application, org_id, agent_id)

    code, error = await _request_json(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json_body={"body": "please run and fail"},
    )
    assert code == 502
    assert error["detail"] == "adapter exploded"

    list_code, messages = await _request_json(
        application, "GET", f"/api/chats/{chat['id']}/messages"
    )
    assert list_code == 200
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["body"] == "please run and fail"
    assert messages[0]["status"] == "completed"

    detail_code, detail = await _request_json(
        application, "GET", f"/api/chats/{chat['id']}"
    )
    assert detail_code == 200
    assert detail["lastMessageAt"] == messages[0]["createdAt"]


async def test_stream_runtime_failure_keeps_acknowledged_user_message(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    monkeypatch.setattr(
        chat_service_module, "get_runtime_adapter", lambda _: FailingChatAdapter()
    )
    chat = await _create_chat(application, org_id, agent_id)

    code, content_type, body = await _request_text(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages/stream",
        json_body={"body": "stream and fail"},
    )
    assert code == 201
    assert content_type.startswith("application/x-ndjson")
    events = [json.loads(line) for line in body.splitlines()]
    assert events[0]["type"] == "ack"
    assert events[-1]["type"] == "error"
    assert events[-1]["error"] == "adapter exploded"
    user_message_id = events[0]["userMessage"]["id"]

    list_code, messages = await _request_json(
        application, "GET", f"/api/chats/{chat['id']}/messages"
    )
    assert list_code == 200
    assert [message["id"] for message in messages] == [user_message_id]
    assert messages[0]["body"] == "stream and fail"
