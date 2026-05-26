from __future__ import annotations

import inspect
from collections.abc import AsyncIterator
from typing import cast

import pytest
from sqlalchemy import Table
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from packages.database.clients import (
    async_transaction,
    create_database_engine,
    create_session_factory,
)
from packages.database.queries.approvals import list_org_approvals
from packages.database.queries.issues import list_org_issues
from packages.database.queries.organizations import list_organizations
from packages.database.schema import (
    ActivityLog,
    Approval,
    Base,
    Issue,
    IssueApproval,
    IssueComment,
    Organization,
)
from server.dependencies.orgs import get_org_service
from server.routes import orgs as org_routes
from server.services.orgs import OrgService


def test_metadata_contains_first_batch_tables() -> None:
    expected = {
        "organizations",
        "issues",
        "approvals",
        "issue_comments",
        "issue_approvals",
        "activity_log",
    }
    actual = {table.name for table in Base.metadata.sorted_tables}
    assert expected.issubset(actual)


def test_schema_models_exported() -> None:
    assert Organization.__tablename__ == "organizations"
    assert Issue.__tablename__ == "issues"
    assert Approval.__tablename__ == "approvals"
    assert IssueComment.__tablename__ == "issue_comments"
    assert IssueApproval.__tablename__ == "issue_approvals"
    assert ActivityLog.__tablename__ == "activity_log"


def test_issue_indexes_match_step4_scope() -> None:
    actual = {index.name for index in cast(Table, Issue.__table__).indexes}
    assert actual == {
        "issues_company_status_idx",
        "issues_company_status_board_order_idx",
        "issues_identifier_idx",
    }


def test_org_route_does_not_define_database_dependencies() -> None:
    source = inspect.getsource(org_routes)
    assert "AsyncSession" not in source
    assert "session_factory" not in source
    assert get_org_service.__module__ == "server.dependencies.orgs"


@pytest.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_database_engine("sqlite+aiosqlite:///:memory:")
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
    return create_session_factory(engine)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def test_engine_creates_session(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        assert isinstance(session, AsyncSession)


async def test_async_transaction_commits(session: AsyncSession) -> None:
    org = Organization(url_key="acme", name="Acme Co")
    async with async_transaction(session):
        session.add(org)
    fetched = await session.get(Organization, org.id)
    assert fetched is not None
    assert fetched.url_key == "acme"
    assert fetched.status == "active"
    assert fetched.issue_prefix == "PAP"


async def test_list_organizations_empty(session: AsyncSession) -> None:
    rows = await list_organizations(session)
    assert list(rows) == []


async def test_list_organizations_returns_seeded(session: AsyncSession) -> None:
    org = Organization(url_key="acme", name="Acme Co")
    async with async_transaction(session):
        session.add(org)
    rows = await list_organizations(session)
    assert len(rows) == 1
    assert rows[0].url_key == "acme"


async def test_list_org_issues_filters_by_org(session: AsyncSession) -> None:
    org_a = Organization(url_key="a", name="A")
    org_b = Organization(url_key="b", name="B")
    async with async_transaction(session):
        session.add_all([org_a, org_b])
    issue_a = Issue(org_id=org_a.id, title="A issue")
    issue_b = Issue(org_id=org_b.id, title="B issue")
    async with async_transaction(session):
        session.add_all([issue_a, issue_b])
    rows = await list_org_issues(session, org_a.id)
    assert len(rows) == 1
    assert rows[0].org_id == org_a.id
    assert rows[0].title == "A issue"


async def test_list_org_approvals_filters_by_org(session: AsyncSession) -> None:
    org = Organization(url_key="acme", name="Acme")
    async with async_transaction(session):
        session.add(org)
    approval = Approval(org_id=org.id, type="hire_agent", payload={})
    async with async_transaction(session):
        session.add(approval)
    rows = await list_org_approvals(session, org.id)
    assert len(rows) == 1
    assert rows[0].type == "hire_agent"
    assert rows[0].status == "pending"


async def test_org_service_list_chains_through_query(
    session: AsyncSession,
) -> None:
    org = Organization(url_key="acme", name="Acme Co")
    async with async_transaction(session):
        session.add(org)
    service = OrgService(session)
    summaries = await service.list()
    assert len(summaries) == 1
    assert summaries[0]["urlKey"] == "acme"
    assert summaries[0]["name"] == "Acme Co"
    assert summaries[0]["status"] == "active"
