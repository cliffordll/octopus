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
from packages.database.schema import (
    Agent,
    Base,
    ChatConversation,
    ChatMessage,
    Organization,
)
from server.app import create_app


def test_step16_chat_proposal_validators() -> None:
    from packages.shared.validators.chat import (
        validate_convert_chat_to_issue,
        validate_resolve_chat_operation_proposal,
    )

    message_id = str(uuid.uuid4())
    assert validate_convert_chat_to_issue(
        {
            "messageId": message_id,
            "proposal": {
                "title": "  Ship it  ",
                "description": "from chat",
                "priority": "high",
            },
        }
    ) == {
        "messageId": message_id,
        "proposal": {
            "title": "Ship it",
            "description": "from chat",
            "priority": "high",
        },
    }
    assert validate_resolve_chat_operation_proposal(
        {"action": "requestRevision", "decisionNote": "  more detail  "}
    ) == {"action": "requestRevision", "decisionNote": "more detail"}


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


async def _seed_chat(
    factory: async_sessionmaker,
    *,
    message_kind: str,
    structured_payload: dict[str, Any],
    replying_agent_id: str | None = None,
    delegate_agent_id: str | None = None,
) -> tuple[str, str, str]:
    org_id = str(uuid.uuid4())
    conversation_id = str(uuid.uuid4())
    message_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"chat-proposal-{org_id[:8]}",
                name="Chat Proposal",
                issue_prefix="CPR",
            )
        )
        if replying_agent_id is not None:
            session.add(
                Agent(
                    id=replying_agent_id,
                    org_id=org_id,
                    name="Proposal Agent",
                    role="ceo",
                    status="idle",
                )
            )
        if delegate_agent_id is not None:
            session.add(
                Agent(
                    id=delegate_agent_id,
                    org_id=org_id,
                    name="Delegate Agent",
                    role="engineer",
                    status="idle",
                    reports_to=replying_agent_id,
                )
            )
        session.add(
            ChatConversation(
                id=conversation_id,
                org_id=org_id,
                title="Proposal chat",
                created_by_user_id="local-board",
            )
        )
        session.add(
            ChatMessage(
                id=message_id,
                org_id=org_id,
                conversation_id=conversation_id,
                role="assistant",
                kind=message_kind,
                status="completed",
                body="Proposal body",
                structured_payload=structured_payload,
                replying_agent_id=replying_agent_id,
            )
        )
        await session.commit()
    return org_id, conversation_id, message_id


async def test_convert_chat_issue_proposal_creates_issue_and_system_message(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    _, conversation_id, message_id = await _seed_chat(
        factory,
        message_kind="issue_proposal",
        structured_payload={
            "issueProposal": {
                "title": "Generated issue",
                "description": "From proposal",
                "priority": "high",
            }
        },
    )

    code, result = await _request(
        application,
        "POST",
        f"/api/chats/{conversation_id}/convert-to-issue",
        json={"messageId": message_id},
    )

    assert code == 201
    assert result["issue"]["title"] == "Generated issue"
    assert result["issue"]["description"] == "From proposal"
    assert result["issue"]["priority"] == "high"
    assert result["systemMessage"]["kind"] == "system_event"
    assert result["systemMessage"]["structuredPayload"]["eventType"] == "issue_created"
    async with factory() as session:
        conversation = await session.get(ChatConversation, conversation_id)
        assert conversation is not None
        assert conversation.primary_issue_id == result["issue"]["id"]


async def test_convert_chat_issue_proposal_defaults_assignee_to_replying_agent(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    _, conversation_id, message_id = await _seed_chat(
        factory,
        message_kind="issue_proposal",
        replying_agent_id="agent-ceo",
        structured_payload={
            "issueProposal": {
                "title": "Assigned issue",
                "description": "From assistant proposal",
                "priority": "medium",
            }
        },
    )

    code, result = await _request(
        application,
        "POST",
        f"/api/chats/{conversation_id}/convert-to-issue",
        json={"messageId": message_id},
    )

    assert code == 201
    assert result["issue"]["assigneeAgentId"] == "agent-ceo"


async def test_convert_chat_issue_proposal_delegates_ceo_issue_to_direct_report(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    _, conversation_id, message_id = await _seed_chat(
        factory,
        message_kind="issue_proposal",
        replying_agent_id="agent-ceo",
        delegate_agent_id="agent-engineer",
        structured_payload={
            "issueProposal": {
                "title": "Delegate issue",
                "description": "CEO should delegate this task.",
                "priority": "medium",
            }
        },
    )

    code, result = await _request(
        application,
        "POST",
        f"/api/chats/{conversation_id}/convert-to-issue",
        json={"messageId": message_id},
    )

    assert code == 201
    assert result["issue"]["assigneeAgentId"] == "agent-engineer"


async def test_convert_chat_issue_proposal_keeps_explicit_assignee(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    _, conversation_id, message_id = await _seed_chat(
        factory,
        message_kind="issue_proposal",
        replying_agent_id="agent-ceo",
        delegate_agent_id="agent-engineer",
        structured_payload={
            "issueProposal": {
                "title": "Explicit issue",
                "description": "CEO explicitly selected an assignee.",
                "priority": "medium",
                "assigneeAgentId": "agent-ceo",
            }
        },
    )

    code, result = await _request(
        application,
        "POST",
        f"/api/chats/{conversation_id}/convert-to-issue",
        json={"messageId": message_id},
    )

    assert code == 201
    assert result["issue"]["assigneeAgentId"] == "agent-ceo"


async def test_resolve_operation_proposal_updates_message_state(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    _, conversation_id, message_id = await _seed_chat(
        factory,
        message_kind="operation_proposal",
        structured_payload={
            "operationProposal": {
                "targetType": "organization",
                "targetId": "ignored-for-reject",
                "summary": "Change brand",
                "patch": {"brandColor": "#fff"},
            },
            "operationProposalState": {
                "status": "pending",
                "decisionNote": None,
                "decidedByUserId": None,
                "decidedAt": None,
            },
        },
    )

    code, result = await _request(
        application,
        "POST",
        f"/api/chats/{conversation_id}/messages/{message_id}/operation-proposal/resolve",
        json={"action": "reject", "decisionNote": "Not now"},
    )

    assert code == 201
    assert (
        result["message"]["structuredPayload"]["operationProposalState"]["status"]
        == "rejected"
    )
    assert (
        result["message"]["structuredPayload"]["operationProposalState"]["decisionNote"]
        == "Not now"
    )
    assert result["systemMessage"]["kind"] == "system_event"
    assert result["systemMessage"]["structuredPayload"]["eventType"] == (
        "operation_rejected"
    )
    async with factory() as session:
        stored = await session.scalar(
            select(ChatMessage).where(ChatMessage.id == message_id)
        )
        assert stored is not None
        assert stored.structured_payload["operationProposalState"]["status"] == (
            "rejected"
        )
