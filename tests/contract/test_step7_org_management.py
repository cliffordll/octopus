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
from starlette.responses import Response

from packages.database.clients import async_transaction
from packages.database.schema import (
    ActivityLog,
    Base,
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


async def _http(
    app: FastAPI,
    method: str,
    path: str,
    *,
    actor_type: str | None = None,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    headers: dict[str, str] = {}
    if actor_type:
        headers["x-test-actor-type"] = actor_type
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path, headers=headers, json=json)
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text
    return response.status_code, body


async def test_org_list_board_success(app: FastAPI) -> None:
    code, body = await _http(app, "GET", "/api/orgs", actor_type="board")
    assert code == 200
    assert isinstance(body, list)


async def test_org_list_missing_actor_returns_503(app: FastAPI) -> None:
    code, body = await _http(app, "GET", "/api/orgs")
    assert code == 503
    assert "Actor context" in body["detail"]


async def test_org_list_non_board_returns_403(app: FastAPI) -> None:
    code, body = await _http(app, "GET", "/api/orgs", actor_type="agent")
    assert code == 403
    assert "Board access required" in body["detail"]


async def test_org_detail_returns_200(app: FastAPI, session: AsyncSession) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(app, "GET", f"/api/orgs/{org_id}", actor_type="board")
    assert code == 200
    assert body["id"] == org_id
    assert "urlKey" in body
    assert "issuePrefix" in body


async def test_org_create_board_returns_200(
    app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    code, body = await _http(
        app,
        "POST",
        "/api/orgs",
        actor_type="board",
        json={"name": "New Org", "description": "seeded", "budgetMonthlyCents": 1234},
    )
    assert code == 200
    assert body["name"] == "New Org"
    assert body["description"] == "seeded"
    assert body["budgetMonthlyCents"] == 1234
    assert body["status"] == "active"
    assert body["issueCounter"] == 0
    assert body["spentMonthlyCents"] == 0
    assert body["issuePrefix"]
    assert body["urlKey"]

    async with session_factory() as verify:
        row = await verify.get(Organization, body["id"])
    assert row is not None
    assert row.name == "New Org"


async def test_org_create_missing_actor_returns_503(app: FastAPI) -> None:
    code, body = await _http(app, "POST", "/api/orgs", json={"name": "New Org"})
    assert code == 503
    assert "Actor context" in body["detail"]


async def test_org_create_non_board_returns_403(app: FastAPI) -> None:
    code, body = await _http(
        app,
        "POST",
        "/api/orgs",
        actor_type="agent",
        json={"name": "New Org"},
    )
    assert code == 403
    assert "Board access required" in body["detail"]


async def test_org_create_invalid_payload_returns_422(app: FastAPI) -> None:
    code, body = await _http(
        app,
        "POST",
        "/api/orgs",
        actor_type="board",
        json={"name": "   "},
    )
    assert code == 422
    assert "name" in body["detail"]


async def test_org_create_writes_activity_record(
    app: FastAPI,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    code, body = await _http(
        app,
        "POST",
        "/api/orgs",
        actor_type="board",
        json={"name": "Activity Org"},
    )
    assert code == 200

    async with session_factory() as verify:
        result = await verify.execute(
            select(ActivityLog).where(ActivityLog.org_id == body["id"])
        )
        rows = result.scalars().all()
    assert len(rows) == 1
    record = rows[0]
    assert record.action == "organization.created"
    assert record.entity_type == "organization"
    assert record.entity_id == body["id"]
    assert record.details == {"name": "Activity Org"}
    assert record.actor_type == "board"


async def test_org_detail_missing_actor_returns_503(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(app, "GET", f"/api/orgs/{org_id}")
    assert code == 503
    assert "Actor context" in body["detail"]


async def test_org_detail_non_board_returns_403(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(app, "GET", f"/api/orgs/{org_id}", actor_type="agent")
    assert code == 403
    assert "Board access required" in body["detail"]


async def test_org_detail_missing_returns_404(app: FastAPI) -> None:
    code, body = await _http(
        app, "GET", f"/api/orgs/{uuid.uuid4()}", actor_type="board"
    )
    assert code == 404
    assert body["detail"] == "Organization not found"


async def test_org_update_board_returns_200(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"name": "Renamed Co", "description": "new desc"},
    )
    assert code == 200
    assert body["name"] == "Renamed Co"
    assert body["description"] == "new desc"
    assert body["id"] == org_id


async def test_org_update_changes_config_fields(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"brandColor": "#ff0000", "budgetMonthlyCents": 50000},
    )
    assert code == 200
    assert body["brandColor"] == "#ff0000"
    assert body["budgetMonthlyCents"] == 50000


async def test_org_update_partial_does_not_touch_other_fields(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code1, before = await _http(app, "GET", f"/api/orgs/{org_id}", actor_type="board")
    assert code1 == 200
    code2, after = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"name": "Just renamed"},
    )
    assert code2 == 200
    assert after["name"] == "Just renamed"
    assert after["description"] == before["description"]
    assert after["budgetMonthlyCents"] == before["budgetMonthlyCents"]
    assert after["brandColor"] == before["brandColor"]


async def test_org_update_non_board_returns_403(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="agent",
        json={"name": "X"},
    )
    assert code == 403
    assert "Board access required" in body["detail"]


async def test_org_update_missing_actor_returns_503(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(app, "PATCH", f"/api/orgs/{org_id}", json={"name": "X"})
    assert code == 503
    assert "Actor context" in body["detail"]


async def test_org_update_invalid_payload_returns_422(
    app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org(session)
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"budgetMonthlyCents": -100},
    )
    assert code == 422
    assert "budgetMonthlyCents" in body["detail"]


async def test_org_update_missing_org_returns_404(app: FastAPI) -> None:
    code, body = await _http(
        app,
        "PATCH",
        f"/api/orgs/{uuid.uuid4()}",
        actor_type="board",
        json={"name": "X"},
    )
    assert code == 404
    assert body["detail"] == "Organization not found"


async def test_org_update_writes_activity_record(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    code, _ = await _http(
        app,
        "PATCH",
        f"/api/orgs/{org_id}",
        actor_type="board",
        json={"name": "Activity Test"},
    )
    assert code == 200

    async with session_factory() as verify:
        result = await verify.execute(
            select(ActivityLog).where(ActivityLog.org_id == org_id)
        )
        rows = result.scalars().all()
    assert len(rows) == 1
    record = rows[0]
    assert record.action == "organization.updated"
    assert record.entity_type == "organization"
    assert record.entity_id == org_id
    assert record.details == {"name": "Activity Test"}
    assert record.actor_type == "board"


async def test_org_update_empty_payload_no_activity(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session)
    code, _ = await _http(
        app, "PATCH", f"/api/orgs/{org_id}", actor_type="board", json={}
    )
    assert code == 200

    async with session_factory() as verify:
        result = await verify.execute(
            select(ActivityLog).where(ActivityLog.org_id == org_id)
        )
        rows = result.scalars().all()
    assert rows == []
