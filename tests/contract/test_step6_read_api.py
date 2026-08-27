from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from dataclasses import replace
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from starlette.responses import Response

from packages.database.clients import async_transaction
from packages.database.schema import (
    Approval,
    Base,
    Issue,
    Organization,
)
from server.app import app as fastapi_app


@fastapi_app.middleware("http")
async def _inject_test_actor(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    actor_type = request.headers.get("x-test-actor-type")
    if actor_type:
        request.state.actor = {
            "type": actor_type,
            "id": request.headers.get("x-test-actor-id", "test-actor"),
            "orgId": request.headers.get("x-test-org-id"),
        }
    return await call_next(request)


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
    async with session_factory() as s:
        yield s


@pytest.fixture
def app(session_factory: async_sessionmaker[AsyncSession]) -> FastAPI:
    fastapi_app.state.session_factory = session_factory
    fastapi_app.state.settings = replace(
        fastapi_app.state.settings, local_trusted=False
    )
    return fastapi_app


async def _seed_org(
    session: AsyncSession,
) -> str:
    org_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"u-{org_id[:8]}",
                name="Test Org",
                issue_prefix=org_id[:6],
            )
        )
    return org_id


async def _seed_issue(
    session: AsyncSession,
    org_id: str,
    *,
    title: str = "Demo issue",
    status: str = "todo",
    assignee_agent_id: str | None = None,
) -> str:
    issue_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title=title,
                status=status,
                assignee_agent_id=assignee_agent_id,
            )
        )
    return issue_id


async def _seed_approval(
    session: AsyncSession,
    org_id: str,
    *,
    approval_type: str = "hire_agent",
    status: str = "pending",
    payload: dict[str, Any] | None = None,
) -> str:
    approval_id = str(uuid.uuid4())
    if payload is None:
        payload = {"reason": "demo"}
    async with async_transaction(session):
        session.add(
            Approval(
                id=approval_id,
                org_id=org_id,
                type=approval_type,
                status=status,
                payload=payload,
            )
        )
    return approval_id


async def _http_get(
    app: FastAPI, path: str, *, actor_type: str | None = None
) -> tuple[int, Any]:
    headers: dict[str, str] = {}
    if actor_type is not None:
        headers["x-test-actor-type"] = actor_type
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path, headers=headers)
    return response.status_code, response.json()


async def test_org_detail_returns_200(app: FastAPI, session: AsyncSession) -> None:
    org_id = await _seed_org(session)
    code, body = await _http_get(app, f"/api/orgs/{org_id}", actor_type="board")
    assert code == 200
    assert body["id"] == org_id
    assert body["status"] == "active"
    assert body["issuePrefix"] == org_id[:6]
    assert body["defaultChatIssueCreationMode"] == "manual_approval"
    assert "urlKey" in body
    assert "createdAt" in body


async def test_org_archive_route_sets_archived_status(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/orgs/{org_id}/archive",
            headers={"x-test-actor-type": "board"},
        )

    assert response.status_code == 200
    archived = response.json()
    assert archived["id"] == org_id
    assert archived["status"] == "archived"


async def test_org_detail_missing_actor_returns_503(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http_get(app, f"/api/orgs/{org_id}")
    assert code == 503
    assert "Actor context" in body["detail"]


async def test_org_detail_non_board_returns_403(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http_get(app, f"/api/orgs/{org_id}", actor_type="agent")
    assert code == 403
    assert "Board access required" in body["detail"]


async def test_org_detail_missing_returns_404(app: FastAPI) -> None:
    code, body = await _http_get(app, f"/api/orgs/{uuid.uuid4()}", actor_type="board")
    assert code == 404
    assert body["detail"] == "Organization not found"


async def test_org_issues_list_empty(app: FastAPI, session: AsyncSession) -> None:
    org_id = await _seed_org(session)
    code, body = await _http_get(app, f"/api/orgs/{org_id}/issues", actor_type="board")
    assert code == 200
    assert body == []


async def test_org_issues_list_seeded(app: FastAPI, session: AsyncSession) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id, title="Hello", status="todo")
    code, body = await _http_get(app, f"/api/orgs/{org_id}/issues", actor_type="board")
    assert code == 200
    assert len(body) == 1
    assert body[0]["id"] == issue_id
    assert body[0]["orgId"] == org_id
    assert body[0]["title"] == "Hello"
    assert body[0]["status"] == "todo"


async def test_org_issues_list_invalid_status_returns_422(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http_get(
        app, f"/api/orgs/{org_id}/issues?status=invalid", actor_type="board"
    )
    assert code == 422
    assert "status" in body["detail"]


async def test_org_issues_list_filters_by_status_and_assignee(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    agent_a = str(uuid.uuid4())
    await _seed_issue(
        session, org_id, title="A todo", status="todo", assignee_agent_id=agent_a
    )
    await _seed_issue(session, org_id, title="A done", status="done")
    code, body = await _http_get(
        app,
        f"/api/orgs/{org_id}/issues?status=todo&assigneeAgentId={agent_a}",
        actor_type="board",
    )
    assert code == 200
    assert len(body) == 1
    assert body[0]["title"] == "A todo"


async def test_org_approvals_list_empty(app: FastAPI, session: AsyncSession) -> None:
    org_id = await _seed_org(session)
    code, body = await _http_get(
        app, f"/api/orgs/{org_id}/approvals", actor_type="board"
    )
    assert code == 200
    assert body == []


async def test_org_approvals_list_seeded(app: FastAPI, session: AsyncSession) -> None:
    org_id = await _seed_org(session)
    approval_id = await _seed_approval(session, org_id)
    code, body = await _http_get(
        app, f"/api/orgs/{org_id}/approvals", actor_type="board"
    )
    assert code == 200
    assert len(body) == 1
    assert body[0]["id"] == approval_id
    assert body[0]["type"] == "hire_agent"
    assert body[0]["status"] == "pending"
    assert body[0]["orgId"] == org_id


async def test_org_approvals_list_invalid_status_returns_422(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http_get(
        app, f"/api/orgs/{org_id}/approvals?status=draft", actor_type="board"
    )
    assert code == 422
    assert "status" in body["detail"]


async def test_issue_detail_missing_returns_404(
    app: FastAPI, session: AsyncSession
) -> None:
    code, body = await _http_get(app, f"/api/issues/{uuid.uuid4()}")
    assert code == 404
    assert body["detail"] == "Issue not found"


async def test_issue_detail_returns_200(app: FastAPI, session: AsyncSession) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id, title="Detail")
    code, body = await _http_get(app, f"/api/issues/{issue_id}", actor_type="board")
    assert code == 200
    assert body["id"] == issue_id
    assert body["orgId"] == org_id
    assert body["title"] == "Detail"
    assert "createdAt" in body
    assert "description" in body  # detail-only field


async def test_issues_error_entry_returns_400(app: FastAPI) -> None:
    code, body = await _http_get(app, "/api/issues")
    assert code == 400
    assert "Missing orgId" in body["detail"]


async def test_approval_detail_missing_returns_404(app: FastAPI) -> None:
    code, body = await _http_get(app, f"/api/approvals/{uuid.uuid4()}")
    assert code == 404
    assert body["detail"] == "Approval not found"


async def test_approval_detail_returns_200(app: FastAPI, session: AsyncSession) -> None:
    org_id = await _seed_org(session)
    approval_id = await _seed_approval(
        session,
        org_id,
        payload={
            "reason": "demo",
            "apiKey": "secret-key",
            "nested": {"clientSecret": "very-secret", "safe": "value"},
        },
    )
    code, body = await _http_get(
        app, f"/api/approvals/{approval_id}", actor_type="board"
    )
    assert code == 200
    assert body["id"] == approval_id
    assert body["orgId"] == org_id
    assert body["type"] == "hire_agent"
    assert "payload" in body
    assert body["payload"]["apiKey"] == "[REDACTED]"
    assert body["payload"]["nested"]["clientSecret"] == "[REDACTED]"
    assert body["payload"]["nested"]["safe"] == "value"
    assert "decisionNote" in body  # detail-only field
