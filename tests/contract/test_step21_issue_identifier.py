from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace

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
from packages.database.schema import Base, Organization
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


async def _seed_org(session: AsyncSession, *, prefix: str) -> str:
    org_id = str(uuid.uuid4())
    async with async_transaction(session):
        session.add(
            Organization(
                id=org_id,
                url_key=f"u-{org_id[:8]}",
                name="Identifier Org",
                issue_prefix=prefix,
            )
        )
    return org_id


async def _create_issue(app: FastAPI, org_id: str, title: str) -> dict:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            f"/api/orgs/{org_id}/issues", json={"title": title}
        )
    return response.json()


async def test_issue_identifier_uses_org_prefix_and_counter(
    app: FastAPI,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    org_id = await _seed_org(session, prefix="PAP")

    first = await _create_issue(app, org_id, "First task")
    second = await _create_issue(app, org_id, "Second task")
    third = await _create_issue(app, org_id, "Third task")

    assert first["identifier"] == "PAP-1"
    assert first["issueNumber"] == 1
    assert second["identifier"] == "PAP-2"
    assert second["issueNumber"] == 2
    assert third["identifier"] == "PAP-3"
    assert third["issueNumber"] == 3

    async with session_factory() as verify:
        org = (
            await verify.execute(select(Organization).where(Organization.id == org_id))
        ).scalar_one()
    assert org.issue_counter == 3


async def test_issue_identifier_isolated_per_org(
    app: FastAPI, session: AsyncSession
) -> None:
    org_a = await _seed_org(session, prefix="AAA")
    org_b = await _seed_org(session, prefix="BBB")

    a1 = await _create_issue(app, org_a, "A1")
    b1 = await _create_issue(app, org_b, "B1")
    a2 = await _create_issue(app, org_a, "A2")

    assert a1["identifier"] == "AAA-1"
    assert b1["identifier"] == "BBB-1"
    assert a2["identifier"] == "AAA-2"
