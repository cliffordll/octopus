from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
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


async def _seed_issue(
    session: AsyncSession, *, status: str = "todo"
) -> tuple[str, str]:
    org_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"u-{org_id[:8]}",
                name="Timestamp Org",
                issue_prefix=org_id[:6],
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Status timestamp probe",
                status=status,
                origin_kind="manual",
            )
        )
    return org_id, issue_id


async def _patch_status(app: FastAPI, issue_id: str, status: str) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            f"/api/issues/{issue_id}", json={"status": status}
        )
    return response.status_code, response.json()


async def test_status_in_progress_sets_started_at(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, issue_id = await _seed_issue(session)

    code, body = await _patch_status(app, issue_id, "in_progress")

    assert code == 200
    assert body["status"] == "in_progress"
    assert body["startedAt"] is not None
    assert body["completedAt"] is None
    assert body["cancelledAt"] is None

    async with session_factory() as verify:
        row = (
            await verify.execute(select(Issue).where(Issue.id == issue_id))
        ).scalar_one()
    assert row.started_at is not None


async def test_status_done_sets_completed_at(
    app: FastAPI, session: AsyncSession
) -> None:
    _, issue_id = await _seed_issue(session, status="in_progress")

    code, body = await _patch_status(app, issue_id, "done")

    assert code == 200
    assert body["status"] == "done"
    assert body["completedAt"] is not None


async def test_status_cancelled_sets_cancelled_at(
    app: FastAPI, session: AsyncSession
) -> None:
    _, issue_id = await _seed_issue(session, status="todo")

    code, body = await _patch_status(app, issue_id, "cancelled")

    assert code == 200
    assert body["status"] == "cancelled"
    assert body["cancelledAt"] is not None


async def test_status_unchanged_does_not_stamp_timestamps(
    app: FastAPI, session: AsyncSession
) -> None:
    _, issue_id = await _seed_issue(session, status="todo")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.patch(
            f"/api/issues/{issue_id}", json={"title": "Just a rename"}
        )
    body = response.json()

    assert response.status_code == 200
    assert body["startedAt"] is None
    assert body["completedAt"] is None
    assert body["cancelledAt"] is None


async def test_reopening_done_issue_clears_completed_at(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _, issue_id = await _seed_issue(session, status="done")
    async with async_transaction(session):
        row = (
            await session.execute(select(Issue).where(Issue.id == issue_id))
        ).scalar_one()
        row.completed_at = datetime.now(UTC)

    code, body = await _patch_status(app, issue_id, "in_progress")

    assert code == 200
    assert body["status"] == "in_progress"
    assert body["completedAt"] is None
    assert body["startedAt"] is not None

    async with session_factory() as verify:
        row = (
            await verify.execute(select(Issue).where(Issue.id == issue_id))
        ).scalar_one()
    assert row.completed_at is None
