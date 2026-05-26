from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
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
from starlette.responses import Response

from packages.database.clients import async_transaction
from packages.database.schema import (
    ActivityLog,
    Approval,
    Base,
    Issue,
    IssueApproval,
    Organization,
    OrganizationOwnership,
)
from packages.shared.validators.approval import (
    validate_create_approval,
    validate_request_approval_revision,
    validate_resolve_approval,
    validate_resubmit_approval,
)
from server.app import app as fastapi_app

POD_ID = "test-pod"


@fastapi_app.middleware("http")
async def _inject_test_actor(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    actor_type = request.headers.get("x-test-actor-type")
    if actor_type:
        request.state.actor = {
            "type": actor_type,
            "id": request.headers.get("x-test-actor-id", "test-actor"),
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
    fastapi_app.state.settings = SimpleNamespace(pod_id=POD_ID)
    return fastapi_app


async def _seed_org(
    session: AsyncSession,
    *,
    owned: bool = True,
    pod_id: str = POD_ID,
    expires_at: datetime | None = None,
) -> str:
    org_id = str(uuid.uuid4())
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(hours=1)
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"u-{org_id[:8]}",
                name="Step9 Org",
                issue_prefix=org_id[:6],
            )
        )
        if owned:
            session.add(
                OrganizationOwnership(
                    organization_id=org_id,
                    pod_id=pod_id,
                    expires_at=expires_at,
                )
            )
    return org_id


async def _seed_issue(
    session: AsyncSession,
    org_id: str,
    *,
    status: str = "blocked",
    assignee_agent_id: str | None = None,
) -> str:
    issue_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                title="Linked issue",
                status=status,
                assignee_agent_id=assignee_agent_id,
                origin_kind="manual",
            )
        )
    return issue_id


async def _seed_approval(
    session: AsyncSession,
    org_id: str,
    *,
    status: str = "pending",
    requested_by_agent_id: str | None = None,
) -> str:
    approval_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Approval(
                id=approval_id,
                org_id=org_id,
                type="hire_agent",
                status=status,
                requested_by_agent_id=requested_by_agent_id,
                payload={"reason": "demo"},
            )
        )
    return approval_id


async def _link_issue_to_approval(
    session: AsyncSession, org_id: str, issue_id: str, approval_id: str
) -> None:
    async with async_transaction(session):
        session.add(
            IssueApproval(org_id=org_id, issue_id=issue_id, approval_id=approval_id)
        )


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    actor_type: str | None = None,
    actor_id: str | None = None,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    headers: dict[str, str] = {}
    if actor_type is not None:
        headers["x-test-actor-type"] = actor_type
    if actor_id is not None:
        headers["x-test-actor-id"] = actor_id
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path, json=json, headers=headers)
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body


def test_create_approval_unsupported_field_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported field"):
        validate_create_approval(
            {
                "type": "hire_agent",
                "payload": {"agentId": "a1"},
                "workspaceConfig": {"danger": True},
            }
        )


def test_create_approval_invalid_linked_issue_ids_raises() -> None:
    with pytest.raises(ValueError, match="issueIds"):
        validate_create_approval(
            {
                "type": "hire_agent",
                "payload": {"agentId": "a1"},
                "issueIds": ["ok", 3],
            }
        )


def test_resolve_approval_unsupported_field_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported field"):
        validate_resolve_approval({"decisionNote": "ship it", "status": "approved"})


def test_request_revision_invalid_decision_note_type_raises() -> None:
    with pytest.raises(ValueError, match="decisionNote"):
        validate_request_approval_revision({"decisionNote": 42})


def test_request_revision_unsupported_field_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported field"):
        validate_request_approval_revision({"decisionNote": "revise", "foo": "bar"})


def test_resubmit_approval_invalid_linked_issue_ids_raises() -> None:
    with pytest.raises(ValueError, match="issueIds"):
        validate_resubmit_approval({"payload": {}, "issueIds": [1]})


def test_resubmit_approval_unsupported_field_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported field"):
        validate_resubmit_approval({"payload": {}, "requestedByUserId": "u1"})


async def test_create_approval_route_returns_200_and_persists(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/approvals",
        actor_type="board",
        actor_id="board-1",
        json={
            "type": "hire_agent",
            "payload": {"accessToken": "secret-token"},
            "issueIds": [],
        },
    )

    assert code == 200
    assert body["orgId"] == org_id
    assert body["status"] == "pending"
    assert body["payload"]["accessToken"] == "[REDACTED]"

    async with session_factory() as verify:
        result = await verify.execute(select(Approval).where(Approval.org_id == org_id))
        rows = result.scalars().all()
    assert len(rows) == 1


async def test_create_approval_route_invalid_payload_returns_422(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/approvals",
        actor_type="board",
        json={"type": "hire_agent", "payload": {}, "workspaceConfig": {}},
    )

    assert code == 422
    assert "Unsupported field" in body["detail"]


async def test_approve_approval_route_recovers_linked_issue(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id, assignee_agent_id="agent-1")
    approval_id = await _seed_approval(session, org_id)
    await _link_issue_to_approval(session, org_id, issue_id, approval_id)

    code, body = await _request(
        app,
        "POST",
        f"/api/approvals/{approval_id}/approve",
        actor_type="board",
        actor_id="board-1",
        json={"decisionNote": "approved", "decidedByUserId": "board-1"},
    )

    assert code == 200
    assert body["status"] == "approved"

    refreshed_issue = await session.get(Issue, issue_id)
    assert refreshed_issue is not None
    assert refreshed_issue.status == "in_progress"


async def test_reject_approval_route_returns_200(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    approval_id = await _seed_approval(session, org_id)

    code, body = await _request(
        app,
        "POST",
        f"/api/approvals/{approval_id}/reject",
        actor_type="board",
        actor_id="board-2",
        json={"decisionNote": "rejected", "decidedByUserId": "board-2"},
    )

    assert code == 200
    assert body["status"] == "rejected"


async def test_request_revision_route_returns_200(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    approval_id = await _seed_approval(session, org_id)

    code, body = await _request(
        app,
        "POST",
        f"/api/approvals/{approval_id}/request-revision",
        actor_type="board",
        actor_id="board-3",
        json={"decisionNote": "revise", "decidedByUserId": "board-3"},
    )

    assert code == 200
    assert body["status"] == "revision_requested"


async def test_resubmit_route_returns_200_for_requesting_agent(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    approval_id = await _seed_approval(
        session, org_id, status="revision_requested", requested_by_agent_id="agent-7"
    )

    code, body = await _request(
        app,
        "POST",
        f"/api/approvals/{approval_id}/resubmit",
        actor_type="agent",
        actor_id="agent-7",
        json={"payload": {"accessToken": "new-token"}},
    )

    assert code == 200
    assert body["status"] == "pending"
    assert body["payload"]["accessToken"] == "[REDACTED]"


async def test_approve_route_non_board_returns_403(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    approval_id = await _seed_approval(session, org_id)

    code, body = await _request(
        app,
        "POST",
        f"/api/approvals/{approval_id}/approve",
        actor_type="agent",
        actor_id="agent-1",
        json={"decisionNote": "nope"},
    )

    assert code == 403
    assert "Board access required" in body["detail"]


async def test_approve_route_missing_actor_context_returns_503(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    approval_id = await _seed_approval(session, org_id)

    code, body = await _request(
        app,
        "POST",
        f"/api/approvals/{approval_id}/approve",
        json={"decisionNote": "no actor"},
    )

    assert code == 503
    assert "Actor context is not configured" in body["detail"]


async def test_create_approval_route_foreign_ownership_returns_403(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session, pod_id="other-pod")

    code, body = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/approvals",
        actor_type="board",
        actor_id="board-1",
        json={"type": "hire_agent", "payload": {}},
    )

    assert code == 403
    assert "another pod" in body["detail"]


async def test_approve_approval_route_writes_activity_names(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    issue_id = await _seed_issue(session, org_id, assignee_agent_id="agent-1")
    approval_id = await _seed_approval(session, org_id)
    await _link_issue_to_approval(session, org_id, issue_id, approval_id)

    code, _ = await _request(
        app,
        "POST",
        f"/api/approvals/{approval_id}/approve",
        actor_type="board",
        actor_id="board-9",
        json={"decisionNote": "ok", "decidedByUserId": "board-9"},
    )

    assert code == 200

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org_id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    actions = [row.action for row in result.scalars().all()]
    assert actions == [
        "approval.approved",
        "approval.linked_issue_assignee_wakeup_queued",
    ]
