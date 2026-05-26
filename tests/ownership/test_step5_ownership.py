from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from packages.database.clients import async_transaction
from packages.database.queries.organization_ownership import (
    get_ownership_by_org_id,
    list_ownerships_for_pod,
)
from packages.database.schema import Base, Organization, OrganizationOwnership
from server.dependencies.ownership import require_organization_ownership
from server.services.ownership import OwnershipDecision, OwnershipService

POD_ID = "test-pod"


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
    async with session_factory() as session:
        yield session


async def _seed_org_with_ownership(
    session: AsyncSession,
    *,
    pod_id: str = POD_ID,
    expires_at: datetime | None = None,
) -> str:
    org_id = str(uuid.uuid4())
    if expires_at is None:
        expires_at = datetime.now(UTC) + timedelta(hours=1)
    async with async_transaction(session):
        session.add(Organization(id=org_id, url_key=f"u-{org_id[:8]}", name="X"))
        session.add(
            OrganizationOwnership(
                organization_id=org_id,
                pod_id=pod_id,
                expires_at=expires_at,
            )
        )
    return org_id


async def test_check_organization_owned(session: AsyncSession) -> None:
    org_id = await _seed_org_with_ownership(session)
    service = OwnershipService(session, POD_ID)
    assert await service.check_organization(org_id) == OwnershipDecision.OWNED


async def test_check_organization_foreign(session: AsyncSession) -> None:
    org_id = await _seed_org_with_ownership(session, pod_id="other-pod")
    service = OwnershipService(session, POD_ID)
    assert await service.check_organization(org_id) == OwnershipDecision.FOREIGN


async def test_check_organization_missing(session: AsyncSession) -> None:
    service = OwnershipService(session, POD_ID)
    assert (
        await service.check_organization(str(uuid.uuid4())) == OwnershipDecision.MISSING
    )


async def test_check_organization_expired(session: AsyncSession) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    org_id = await _seed_org_with_ownership(session, expires_at=past)
    service = OwnershipService(session, POD_ID)
    assert await service.check_organization(org_id) == OwnershipDecision.EXPIRED


async def test_get_ownership_by_org_id_present(session: AsyncSession) -> None:
    org_id = await _seed_org_with_ownership(session)
    row = await get_ownership_by_org_id(session, org_id)
    assert row is not None
    assert row.pod_id == POD_ID
    assert row.organization_id == org_id


async def test_get_ownership_by_org_id_missing(session: AsyncSession) -> None:
    row = await get_ownership_by_org_id(session, str(uuid.uuid4()))
    assert row is None


async def test_list_ownerships_for_pod_filters_pod(
    session: AsyncSession,
) -> None:
    owned_id = await _seed_org_with_ownership(session, pod_id=POD_ID)
    _foreign_id = await _seed_org_with_ownership(session, pod_id="other-pod")
    rows = await list_ownerships_for_pod(session, POD_ID)
    assert [row.organization_id for row in rows] == [owned_id]


async def test_list_owned_organization_ids_excludes_foreign_and_expired(
    session: AsyncSession,
) -> None:
    owned_active = await _seed_org_with_ownership(session)
    _owned_expired = await _seed_org_with_ownership(
        session, expires_at=datetime.now(UTC) - timedelta(hours=1)
    )
    _foreign = await _seed_org_with_ownership(session, pod_id="other-pod")
    service = OwnershipService(session, POD_ID)
    result = await service.list_owned_organization_ids()
    assert result == [owned_active]


@pytest.fixture
def guard_app(
    session_factory: async_sessionmaker[AsyncSession],
) -> FastAPI:
    app = FastAPI()
    app.state.session_factory = session_factory
    app.state.settings = SimpleNamespace(pod_id=POD_ID)

    @app.get("/probe/{orgId}")
    async def probe(
        orgId: str,
        _: None = Depends(require_organization_ownership),
    ) -> dict[str, str]:
        return {"orgId": orgId, "decision": "owned"}

    return app


async def _http_get(app: FastAPI, path: str) -> tuple[int, dict[str, str]]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(path)
    return response.status_code, response.json()


async def test_guard_owned_returns_200(
    guard_app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org_with_ownership(session)
    status_code, body = await _http_get(guard_app, f"/probe/{org_id}")
    assert status_code == 200
    assert body == {"orgId": org_id, "decision": "owned"}


async def test_guard_foreign_returns_403(
    guard_app: FastAPI, session: AsyncSession
) -> None:
    org_id = await _seed_org_with_ownership(session, pod_id="other-pod")
    status_code, body = await _http_get(guard_app, f"/probe/{org_id}")
    assert status_code == 403
    assert "another pod" in body["detail"]


async def test_guard_missing_returns_403(guard_app: FastAPI) -> None:
    status_code, body = await _http_get(guard_app, f"/probe/{uuid.uuid4()}")
    assert status_code == 403
    assert "no ownership record" in body["detail"]


async def test_guard_expired_returns_409(
    guard_app: FastAPI, session: AsyncSession
) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    org_id = await _seed_org_with_ownership(session, expires_at=past)
    status_code, body = await _http_get(guard_app, f"/probe/{org_id}")
    assert status_code == 409
    assert "expired" in body["detail"]
