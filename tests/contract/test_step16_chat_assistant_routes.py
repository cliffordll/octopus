from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Agent, Approval, Base, Organization
from packages.runtimes.types import RuntimeExecutionContext, RuntimeExecutionResult
from server.app import create_app


class FakeChatAdapter:
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


def test_add_chat_message_accepts_edit_user_message_id() -> None:
    from packages.shared.validators.chat import validate_add_chat_message

    edit_id = str(uuid.uuid4())
    assert validate_add_chat_message(
        {"body": "  revise this  ", "editUserMessageId": edit_id}
    ) == {"body": "revise this", "editUserMessageId": edit_id}


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
        session.add(
            Organization(
                id=org_id,
                url_key="step-16-assistant",
                name="Step 16 Assistant",
                issue_prefix="AST",
            )
        )
        session.add(
            Agent(
                id=agent_id,
                org_id=org_id,
                name="Assistant Agent",
                agent_runtime_type="fake_chat",
                agent_runtime_config={},
            )
        )
        await session.commit()
    return org_id, agent_id


async def _create_chat(
    application: FastAPI,
    org_id: str,
    agent_id: str,
    *,
    issue_creation_mode: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"title": "Assistant chat", "preferredAgentId": agent_id}
    if issue_creation_mode is not None:
        payload["issueCreationMode"] = issue_creation_mode
    code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{org_id}/chats",
        json=payload,
    )
    assert code == 201
    return created


async def test_assistant_reply_persists_kind_structured_payload_and_approval(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    adapter = FakeChatAdapter(
        [
            {
                "summary": "Create the issue?",
                "kind": "issue_proposal",
                "structuredPayload": {
                    "issueProposal": {
                        "title": "Generated issue",
                        "description": "Generated from chat",
                    }
                },
            }
        ]
    )
    monkeypatch.setattr(chat_service_module, "get_runtime_adapter", lambda _: adapter)
    chat = await _create_chat(application, org_id, agent_id)

    code, result = await _request(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json={"body": "please create an issue"},
    )

    assert code == 201
    user_message, assistant_message = result["messages"]
    assert user_message["role"] == "user"
    assert assistant_message["role"] == "assistant"
    assert assistant_message["kind"] == "issue_proposal"
    assert assistant_message["structuredPayload"]["issueProposal"]["title"] == (
        "Generated issue"
    )
    assert assistant_message["approvalId"] is not None
    async with factory() as session:
        approval = await session.scalar(
            select(Approval).where(Approval.id == assistant_message["approvalId"])
        )
    assert approval is not None
    assert approval.type == "chat_issue_creation"
    assert approval.payload["chatConversationId"] == chat["id"]
    prompt = adapter.captured_prompts[0]
    assert "issue_proposal" in prompt
    assert "issueProposal" in prompt
    assert "convert-to-issue" in prompt


async def test_assistant_json_text_issue_proposal_is_persisted(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    adapter = FakeChatAdapter(
        [
            {
                "summary": (
                    '{"summary":"我可以为你创建这个任务。",'
                    '"kind":"issue_proposal",'
                    '"structuredPayload":{"issueProposal":{'
                    '"title":"分析 rudder 源码",'
                    '"description":"分析 rudder 源码并整理核心架构。",'
                    '"priority":"medium"}}}'
                )
            }
        ]
    )
    monkeypatch.setattr(chat_service_module, "get_runtime_adapter", lambda _: adapter)
    chat = await _create_chat(application, org_id, agent_id)

    code, result = await _request(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json={"body": "我想分析一下rudder源码，你能帮我创建一个任务吗？"},
    )

    assert code == 201
    assistant_message = result["messages"][1]
    assert assistant_message["kind"] == "issue_proposal"
    assert assistant_message["body"] == "我可以为你创建这个任务。"
    assert assistant_message["structuredPayload"]["issueProposal"] == {
        "title": "分析 rudder 源码",
        "description": "分析 rudder 源码并整理核心架构。",
        "priority": "medium",
    }
    assert assistant_message["approvalId"] is not None


async def test_auto_create_chat_issue_proposal_creates_issue(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    adapter = FakeChatAdapter(
        [
            {
                "summary": "我会创建任务。",
                "kind": "issue_proposal",
                "structuredPayload": {
                    "issueProposal": {
                        "title": "输出 hello world",
                        "description": "创建一个简单的任务，输出 hello world",
                        "priority": "low",
                    }
                },
            }
        ]
    )
    monkeypatch.setattr(chat_service_module, "get_runtime_adapter", lambda _: adapter)
    chat = await _create_chat(
        application, org_id, agent_id, issue_creation_mode="auto_create"
    )

    code, result = await _request(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json={"body": "请帮我创建一个任务输出hello world"},
    )

    assert code == 201
    assert len(result["messages"]) == 3
    assistant_message = result["messages"][1]
    system_message = result["messages"][2]
    assert assistant_message["kind"] == "issue_proposal"
    assert assistant_message["approvalId"] is None
    assert system_message["kind"] == "system_event"
    assert system_message["structuredPayload"]["eventType"] == "issue_created"

    issue_id = system_message["structuredPayload"]["issueId"]
    issues_code, issues = await _request(
        application, "GET", f"/api/orgs/{org_id}/issues"
    )
    assert issues_code == 200
    assert [row["id"] for row in issues] == [issue_id]
    assert issues[0]["title"] == "输出 hello world"


async def test_edit_user_message_supersedes_previous_turn_variant(
    app: tuple[FastAPI, async_sessionmaker],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.services import chats as chat_service_module

    application, factory = app
    org_id, agent_id = await _seed_org_agent(factory)
    adapter = FakeChatAdapter(
        [
            {"summary": "First reply"},
            {"summary": "Second reply", "kind": "ask_user", "structuredPayload": {}},
        ]
    )
    monkeypatch.setattr(chat_service_module, "get_runtime_adapter", lambda _: adapter)
    chat = await _create_chat(application, org_id, agent_id)

    first_code, first = await _request(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json={"body": "first"},
    )
    assert first_code == 201
    first_user, first_assistant = first["messages"]

    second_code, second = await _request(
        application,
        "POST",
        f"/api/chats/{chat['id']}/messages",
        json={"body": "second", "editUserMessageId": first_user["id"]},
    )
    assert second_code == 201
    second_user, second_assistant = second["messages"]
    assert second_user["chatTurnId"] == first_user["chatTurnId"]
    assert second_user["turnVariant"] == 1
    assert second_assistant["chatTurnId"] == first_user["chatTurnId"]
    assert second_assistant["turnVariant"] == 1

    list_code, rows = await _request(
        application, "GET", f"/api/chats/{chat['id']}/messages"
    )
    assert list_code == 200
    by_id = {row["id"]: row for row in rows}
    assert by_id[first_user["id"]]["supersededAt"] is not None
    assert by_id[first_assistant["id"]]["supersededAt"] is not None
    assert by_id[second_user["id"]]["supersededAt"] is None
    assert by_id[second_assistant["id"]]["supersededAt"] is None
