from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace
from typing import Any

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
    Approval,
    Base,
    Issue,
    IssueApproval,
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


async def _seed_approval(
    session: AsyncSession, *, with_issues: int = 0
) -> tuple[str, str, list[str]]:
    org_id = str(uuid.uuid4())
    approval_id = str(uuid.uuid4())
    issue_ids: list[str] = []
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"u-{org_id[:8]}",
                name="Comments Org",
                issue_prefix=org_id[:6],
            )
        )
        session.add(
            Approval(
                id=approval_id,
                org_id=org_id,
                type="hire_agent",
                status="pending",
                payload={},
            )
        )
        for index in range(with_issues):
            issue_id = str(uuid.uuid4())
            issue_ids.append(issue_id)
            session.add(
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    title=f"Linked issue {index + 1}",
                    status="todo",
                    origin_kind="manual",
                )
            )
            session.add(
                IssueApproval(
                    org_id=org_id,
                    issue_id=issue_id,
                    approval_id=approval_id,
                )
            )
    return org_id, approval_id, issue_ids


async def _request(
    app: FastAPI, method: str, path: str, *, json: dict[str, Any] | None = None
) -> tuple[int, Any]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path, json=json)
    return response.status_code, response.json()


async def test_list_approval_comments_starts_empty(
    app: FastAPI, session: AsyncSession
) -> None:
    _, approval_id, _ = await _seed_approval(session)

    code, body = await _request(app, "GET", f"/api/approvals/{approval_id}/comments")

    assert code == 200
    assert body == []


async def test_add_approval_comment_and_list(
    app: FastAPI, session: AsyncSession
) -> None:
    _, approval_id, _ = await _seed_approval(session)

    create_code, created = await _request(
        app, "POST", f"/api/approvals/{approval_id}/comments", json={"body": "hi"}
    )

    assert create_code == 201
    assert created["body"] == "hi"
    assert created["approvalId"] == approval_id
    # local_trusted board actor: not an agent
    assert created["authorAgentId"] is None
    assert created["authorUserId"] == "local-board"

    list_code, comments = await _request(
        app, "GET", f"/api/approvals/{approval_id}/comments"
    )
    assert list_code == 200
    assert len(comments) == 1
    assert comments[0]["body"] == "hi"


async def test_add_approval_comment_rejects_empty(
    app: FastAPI, session: AsyncSession
) -> None:
    _, approval_id, _ = await _seed_approval(session)

    code, body = await _request(
        app, "POST", f"/api/approvals/{approval_id}/comments", json={"body": "   "}
    )

    assert code == 422
    assert "body" in body["detail"]


async def test_list_approval_issues_returns_linked_issues(
    app: FastAPI, session: AsyncSession
) -> None:
    _, approval_id, issue_ids = await _seed_approval(session, with_issues=2)

    code, body = await _request(app, "GET", f"/api/approvals/{approval_id}/issues")

    assert code == 200
    assert {row["id"] for row in body} == set(issue_ids)


async def test_missing_approval_returns_404_for_comments_and_issues(
    app: FastAPI,
) -> None:
    missing = str(uuid.uuid4())

    comments_code, _ = await _request(app, "GET", f"/api/approvals/{missing}/comments")
    issues_code, _ = await _request(app, "GET", f"/api/approvals/{missing}/issues")

    assert comments_code == 404
    assert issues_code == 404
