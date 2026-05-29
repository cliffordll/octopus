from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace

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
from packages.database.schema import Approval, Base, Organization
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


async def _seed_approval(session: AsyncSession, *, status: str = "pending") -> str:
    org_id = str(uuid.uuid4())
    approval_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"u-{org_id[:8]}",
                name="Resolve Org",
                issue_prefix=org_id[:6],
            )
        )
        session.add(
            Approval(
                id=approval_id,
                org_id=org_id,
                type="hire_agent",
                status=status,
                payload={},
            )
        )
    return approval_id


async def _post_json(app: FastAPI, path: str, payload: dict) -> tuple[int, dict]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(path, json=payload)
    return response.status_code, response.json()


async def test_approve_defaults_decided_by_user_id_to_board(
    app: FastAPI, session: AsyncSession
) -> None:
    approval_id = await _seed_approval(session)

    code, body = await _post_json(app, f"/api/approvals/{approval_id}/approve", {})

    assert code == 200
    assert body["status"] == "approved"
    assert body["decidedByUserId"] == "board"


async def test_request_revision_defaults_decided_by_user_id_to_board(
    app: FastAPI, session: AsyncSession
) -> None:
    approval_id = await _seed_approval(session)

    code, body = await _post_json(
        app, f"/api/approvals/{approval_id}/request-revision", {}
    )

    assert code == 200
    assert body["status"] == "revision_requested"
    assert body["decidedByUserId"] == "board"


async def test_approve_already_approved_is_idempotent(
    app: FastAPI, session: AsyncSession
) -> None:
    approval_id = await _seed_approval(session, status="approved")

    code, body = await _post_json(app, f"/api/approvals/{approval_id}/approve", {})

    # Upstream `services/approvals.ts:46-48` treats same-status as no-op 200.
    assert code == 200
    assert body["status"] == "approved"


async def test_approve_rejected_returns_422(
    app: FastAPI, session: AsyncSession
) -> None:
    approval_id = await _seed_approval(session, status="rejected")

    code, body = await _post_json(app, f"/api/approvals/{approval_id}/approve", {})

    assert code == 422
    assert "pending or revision requested" in body["detail"]


async def test_reject_already_approved_returns_422(
    app: FastAPI, session: AsyncSession
) -> None:
    approval_id = await _seed_approval(session, status="approved")

    code, body = await _post_json(app, f"/api/approvals/{approval_id}/reject", {})

    assert code == 422
    assert "pending or revision requested" in body["detail"]


async def test_resolve_from_revision_requested_succeeds(
    app: FastAPI, session: AsyncSession
) -> None:
    approval_id = await _seed_approval(session, status="revision_requested")

    code, body = await _post_json(app, f"/api/approvals/{approval_id}/approve", {})

    assert code == 200
    assert body["status"] == "approved"
    assert body["decidedByUserId"] == "board"
