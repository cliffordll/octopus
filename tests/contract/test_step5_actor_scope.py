from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from packages.database.clients import async_transaction
from packages.database.schema import ActivityLog, Approval, Base, Issue, Organization
from server.app import create_app
from server.middleware import ActorContextMiddleware


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
async def session_factory(
    engine: AsyncEngine,
) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as value:
        yield value


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> FastAPI:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    application = create_app()
    application.state.session_factory = session_factory

    @application.middleware("http")
    async def inject_agent_actor(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        actor_id = request.headers.get("x-test-agent-id")
        if actor_id:
            request.state.actor = {
                "type": "agent",
                "id": actor_id,
                "agentId": actor_id,
                "orgId": request.headers["x-test-org-id"],
            }
        return await call_next(request)

    return application


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path, headers=headers, json=json)
    return response.status_code, response.json()


async def _seed_org(session: AsyncSession, name: str) -> str:
    org_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"org-{org_id[:8]}",
                name=name,
                issue_prefix=org_id[:6],
            )
        )
    return org_id


def test_default_actor_context_middleware_avoids_base_http_middleware(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    application = create_app()

    middleware_classes = [middleware.cls for middleware in application.user_middleware]
    assert ActorContextMiddleware in middleware_classes
    assert BaseHTTPMiddleware not in middleware_classes


async def test_local_trusted_actor_enables_org_creation(
    app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    code, body = await _request(app, "POST", "/api/orgs", json={"name": "Local Org"})

    assert code == 200
    async with session_factory() as verify:
        result = await verify.execute(
            select(ActivityLog).where(ActivityLog.org_id == body["id"])
        )
        activity = result.scalar_one()
    assert activity.actor_type == "board"
    assert activity.actor_id == "local-board"


async def test_issue_activity_uses_local_actor(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session, "Issue Org")

    code, _ = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/issues",
        json={"title": "Scoped issue"},
    )

    assert code == 200
    async with session_factory() as verify:
        result = await verify.execute(
            select(ActivityLog).where(ActivityLog.org_id == org_id)
        )
        activity = result.scalar_one()
    assert activity.actor_type == "board"
    assert activity.actor_id == "local-board"


async def test_agent_cannot_read_issue_from_another_organization(
    app: FastAPI, session: AsyncSession
) -> None:
    own_org_id = await _seed_org(session, "Own Org")
    foreign_org_id = await _seed_org(session, "Foreign Org")
    issue_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(Issue(id=issue_id, org_id=foreign_org_id, title="Hidden issue"))

    code, body = await _request(
        app,
        "GET",
        f"/api/issues/{issue_id}",
        headers={"x-test-agent-id": "agent-1", "x-test-org-id": own_org_id},
    )

    assert code == 403
    assert "organization" in body["detail"].lower()


async def test_agent_cannot_read_approval_from_another_organization(
    app: FastAPI, session: AsyncSession
) -> None:
    own_org_id = await _seed_org(session, "Own Org")
    foreign_org_id = await _seed_org(session, "Foreign Org")
    approval_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Approval(
                id=approval_id,
                org_id=foreign_org_id,
                type="hire_agent",
                status="pending",
                payload={},
            )
        )

    code, body = await _request(
        app,
        "GET",
        f"/api/approvals/{approval_id}",
        headers={"x-test-agent-id": "agent-1", "x-test-org-id": own_org_id},
    )

    assert code == 403
    assert "organization" in body["detail"].lower()


async def test_malformed_org_issue_path_returns_scope_hint(app: FastAPI) -> None:
    code, body = await _request(app, "GET", "/api/orgs/issues")

    assert code == 400
    assert "Missing orgId" in body["detail"]
