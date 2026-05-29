from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Agent, Base, Organization
from packages.runtimes.types import RuntimeExecutionContext, RuntimeExecutionResult
from server.app import create_app


class CapturingChatAdapter:
    """Adapter stub that records the ``promptTemplate`` it receives."""

    type = "fake_chat"

    def __init__(self, replies: list[dict[str, Any]]) -> None:
        self._replies = replies
        self.captured_prompts: list[str] = []

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        prompt = context.config.get("promptTemplate")
        if isinstance(prompt, str):
            self.captured_prompts.append(prompt)
        reply = self._replies.pop(0)
        return RuntimeExecutionResult(exit_code=0, result_json=reply)


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


async def _seed_org_agent(factory: async_sessionmaker) -> tuple[str, str]:
    org_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    async with factory() as session:
        async with session.begin():
            session.add(
                Organization(
                    id=org_id,
                    url_key=f"u-{org_id[:8]}",
                    name="History Org",
                    issue_prefix=org_id[:6],
                )
            )
            session.add(
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="Bot",
                    role="engineer",
                    status="idle",
                    agent_runtime_type="codex_local",
                    agent_runtime_config={},
                    runtime_config={},
                )
            )
    return org_id, agent_id


async def _create_chat(app: FastAPI, org_id: str, agent_id: str) -> dict:
    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json={"title": "History chat", "preferredAgentId": agent_id},
    )
    assert code == 201
    return body


async def test_first_message_prompt_contains_only_user_turn(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    adapter = CapturingChatAdapter([{"summary": "ack-1"}])
    monkeypatch.setattr(chat_service_module, "get_runtime_adapter", lambda _: adapter)
    chat = await _create_chat(application, org_id, agent_id)

    code, _ = await _request(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json={"body": "first user turn"},
    )
    assert code == 201
    assert len(adapter.captured_prompts) == 1
    envelope = json.loads(adapter.captured_prompts[0])
    assert envelope["conversation"]["id"] == chat["id"]
    assert envelope["recentMessages"][-1]["role"] == "user"
    assert envelope["recentMessages"][-1]["body"] == "first user turn"
    assert len(envelope["recentMessages"]) == 1


async def test_second_message_prompt_includes_prior_turn(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    adapter = CapturingChatAdapter(
        [{"summary": "assistant reply 1"}, {"summary": "assistant reply 2"}]
    )
    monkeypatch.setattr(chat_service_module, "get_runtime_adapter", lambda _: adapter)
    chat = await _create_chat(application, org_id, agent_id)

    await _request(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json={"body": "first user turn"},
    )
    code, _ = await _request(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json={"body": "second user turn"},
    )
    assert code == 201

    envelope = json.loads(adapter.captured_prompts[-1])
    bodies = [(entry["role"], entry["body"]) for entry in envelope["recentMessages"]]
    assert ("user", "first user turn") in bodies
    assert ("assistant", "assistant reply 1") in bodies
    assert ("user", "second user turn") in bodies
    # latest turn must be last so the LLM treats it as the new prompt
    assert bodies[-1] == ("user", "second user turn")


async def test_prompt_envelope_caps_recent_messages_at_twelve(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    replies = [{"summary": f"ack-{i}"} for i in range(20)]
    adapter = CapturingChatAdapter(replies)
    monkeypatch.setattr(chat_service_module, "get_runtime_adapter", lambda _: adapter)
    chat = await _create_chat(application, org_id, agent_id)

    for index in range(15):
        await _request(
            application,
            "POST",
            f"/api/chats/{chat['id']}/messages",
            json={"body": f"msg {index}"},
        )

    envelope = json.loads(adapter.captured_prompts[-1])
    assert len(envelope["recentMessages"]) == 12
    # last entry must still be the freshest user message
    assert envelope["recentMessages"][-1]["body"] == "msg 14"
