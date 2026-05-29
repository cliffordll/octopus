from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from packages.database.clients import async_transaction
from packages.database.schema import (
    Base,
    ChatConversation,
    ChatMessage,
    Organization,
)
from server.app import app as fastapi_app


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest.fixture
def app(session_factory: async_sessionmaker[AsyncSession]) -> Iterator[FastAPI]:
    original_settings = fastapi_app.state.settings
    fastapi_app.state.session_factory = session_factory
    fastapi_app.state.settings = replace(original_settings, local_trusted=True)
    try:
        yield fastapi_app
    finally:
        fastapi_app.state.settings = original_settings


async def _seed_chat(
    session: AsyncSession,
    *,
    messages: list[tuple[str, str, datetime]],
) -> tuple[str, str]:
    org_id = str(uuid.uuid4())
    chat_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"u-{org_id[:8]}",
                name="Preview Org",
                issue_prefix=org_id[:6],
            )
        )
        session.add(
            ChatConversation(
                id=chat_id,
                org_id=org_id,
                title="Preview chat",
            )
        )
        for role, body, created_at in messages:
            session.add(
                ChatMessage(
                    id=str(uuid.uuid4()),
                    org_id=org_id,
                    conversation_id=chat_id,
                    role=role,
                    kind="message",
                    status="completed",
                    body=body,
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
    return org_id, chat_id


async def _get_chat(app: FastAPI, chat_id: str) -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/chats/{chat_id}")
    assert response.status_code == 200
    return response.json()


async def test_latest_reply_preview_uses_latest_assistant_body(
    app: FastAPI, session: AsyncSession
) -> None:
    base = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    _, chat_id = await _seed_chat(
        session,
        messages=[
            ("user", "first user message", base),
            ("assistant", "First assistant reply", base + timedelta(seconds=10)),
            ("user", "follow up", base + timedelta(seconds=20)),
            ("assistant", "Second assistant reply", base + timedelta(seconds=30)),
        ],
    )

    body = await _get_chat(app, chat_id)

    assert body["latestReplyPreview"] == "Second assistant reply"


async def test_latest_reply_preview_ignores_user_role(
    app: FastAPI, session: AsyncSession
) -> None:
    base = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    _, chat_id = await _seed_chat(
        session,
        messages=[
            ("assistant", "Old assistant body", base),
            (
                "user",
                "newer user message that should not preview",
                base + timedelta(seconds=10),
            ),
        ],
    )

    body = await _get_chat(app, chat_id)

    assert body["latestReplyPreview"] == "Old assistant body"


async def test_latest_reply_preview_truncated_to_140(
    app: FastAPI, session: AsyncSession
) -> None:
    base = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    long_body = "x" * 200
    _, chat_id = await _seed_chat(session, messages=[("assistant", long_body, base)])

    body = await _get_chat(app, chat_id)

    assert body["latestReplyPreview"] is not None
    assert len(body["latestReplyPreview"]) == 140


async def test_latest_reply_preview_null_when_no_incoming_messages(
    app: FastAPI, session: AsyncSession
) -> None:
    base = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    _, chat_id = await _seed_chat(
        session, messages=[("user", "only user messages here", base)]
    )

    body = await _get_chat(app, chat_id)

    assert body["latestReplyPreview"] is None
