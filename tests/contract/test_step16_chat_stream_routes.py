from __future__ import annotations

import importlib
import importlib.util
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


class FakeChatAdapter:
    type = "fake_stream"

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        if context.on_stream_event is not None:
            await context.on_stream_event(
                {"type": "assistant_delta", "delta": "stream fallback reply"}
            )
        return RuntimeExecutionResult(
            exit_code=0, result_json={"summary": "stream fallback reply"}
        )


def test_step16_chat_stream_contract_exposes_paths_and_event_type() -> None:
    modules = ("packages.shared.api_paths.chats", "packages.shared.types.chat")
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    paths = importlib.import_module("packages.shared.api_paths.chats")
    types = importlib.import_module("packages.shared.types.chat")

    assert paths.CHAT_MESSAGES_STREAM_PATH == "/api/chats/{id}/messages/stream"
    assert (
        paths.CHAT_MESSAGES_STREAM_STOP_PATH == "/api/chats/{id}/messages/stream/stop"
    )
    assert types.ChatStreamEvent.__annotations__["type"] is not None


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
                url_key=f"stream-{org_id[:8]}",
                name="Step 16 Stream",
                issue_prefix="STR",
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Stream Agent",
                agent_runtime_type="fake_stream",
                agent_runtime_config={},
            )
        )
        await session.commit()
    return org_id, agent_id


async def test_chat_stream_route_returns_ndjson_delta_and_final(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    monkeypatch.setattr(
        chat_service_module, "get_runtime_adapter", lambda _: FakeChatAdapter()
    )

    create_code, chat = await _request_json(
        application,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json_body={"title": "Stream chat", "preferredAgentId": agent_id},
    )
    assert create_code == 201

    code, content_type, body = await _request_text(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages/stream",
        json_body={"body": "stream this"},
    )

    assert code == 201
    assert content_type.startswith("application/x-ndjson")
    events = [json.loads(line) for line in body.splitlines()]
    assert [event["type"] for event in events] == ["ack", "assistant_delta", "final"]
    assert events[1]["delta"] == "stream fallback reply"
    assert events[2]["messages"][0]["role"] == "user"
    assert events[2]["messages"][1]["body"] == "stream fallback reply"


async def test_chat_stream_stop_route_is_stable_for_existing_conversation(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    create_code, chat = await _request_json(
        application,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json_body={"title": "Stream stop", "preferredAgentId": agent_id},
    )
    assert create_code == 201

    stop_code, stopped = await _request_json(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages/stream/stop",
    )

    assert stop_code == 200
    assert stopped == {"stopped": False}
