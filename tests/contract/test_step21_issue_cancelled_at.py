from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime

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
from packages.database.schema import Base, Issue, Organization
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


async def _seed_issue(session: AsyncSession, **overrides) -> tuple[str, str]:
    org_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"u-{org_id[:8]}",
                name="Cancelled Org",
                issue_prefix=org_id[:6],
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Issue with cancellation",
                status="cancelled",
                origin_kind="manual",
                cancelled_at=overrides.get("cancelled_at"),
            )
        )
    return org_id, issue_id


async def _get(app: FastAPI, path: str) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code, response.json()


async def test_issue_detail_includes_cancelled_at_when_set(
    app: FastAPI, session: AsyncSession
) -> None:
    cancelled_at = datetime(2026, 5, 1, 12, 30, 45, tzinfo=UTC)
    _, issue_id = await _seed_issue(session, cancelled_at=cancelled_at)

    code, body = await _get(app, f"/api/issues/{issue_id}")

    assert code == 200
    assert "cancelledAt" in body
    assert isinstance(body["cancelledAt"], str)
    assert body["cancelledAt"].startswith("2026-05-01T12:30:45")


async def test_issue_detail_includes_cancelled_at_key_when_null(
    app: FastAPI, session: AsyncSession
) -> None:
    _, issue_id = await _seed_issue(session)

    code, body = await _get(app, f"/api/issues/{issue_id}")

    assert code == 200
    assert "cancelledAt" in body
    assert body["cancelledAt"] is None
