from __future__ import annotations

import inspect
import sqlite3
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.pool.impl import AsyncAdaptedQueuePool

from packages.database.clients import (
    async_transaction,
    create_database_engine,
    create_session_factory,
)
from packages.database.clients.base import _apply_sqlite_pragmas
from packages.database.queries import activity_log as activity_log_queries
from packages.database.queries import issue_comments as issue_comment_queries
from packages.database.queries.approvals import (
    create_approval,
    list_org_approvals,
    update_approval,
)
from packages.database.queries.issue_comments import (
    insert_issue_comment,
    list_issue_comments,
)
from packages.database.queries.issues import (
    create_issue,
    list_org_issues,
    recover_blocked_linked_issues_for_approval,
    update_issue,
)
from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.organizations import (
    list_organizations,
    update_organization,
)
from packages.database.migrations.runner import upgrade_to_head
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


def test_issue_indexes_match_upstream() -> None:
    actual = {index.name for index in cast(Table, Issue.__table__).indexes}
    assert actual == {
        "issues_company_status_idx",
        "issues_company_status_board_order_idx",
        "issues_company_assignee_status_idx",
        "issues_company_assignee_user_status_idx",
        "issues_company_reviewer_agent_status_idx",
        "issues_company_reviewer_user_status_idx",
        "issues_company_parent_idx",
        "issues_company_project_idx",
        "issues_company_origin_idx",
        "issues_company_project_workspace_idx",
        "issues_company_execution_workspace_idx",
        "issues_identifier_idx",
        "issues_open_automation_execution_uq",
    }


def test_org_route_does_not_define_database_dependencies() -> None:
    source = inspect.getsource(org_routes)
    assert "AsyncSession" not in source
    assert "session_factory" not in source
    assert get_org_service.__module__ == "server.dependencies.orgs"


@pytest.mark.asyncio
async def test_upgrade_to_head_creates_first_batch_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "alembic-upgrade.db"

    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")

    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master "
                    "where type='table' and name in ("
                    "'organizations',"
                    "'issues',"
                    "'approvals',"
                    "'issue_comments',"
                    "'issue_approvals',"
                    "'activity_log',"
                    "'alembic_version'"
                    ")"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()

    assert names == {
        "organizations",
        "issues",
        "approvals",
        "issue_comments",
        "issue_approvals",
        "activity_log",
        "alembic_version",
    }


@pytest.mark.asyncio
async def test_sqlite_file_engine_uses_wal_journal_and_busy_timeout(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "journal-mode.db"
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text("PRAGMA journal_mode"))
            assert result.scalar_one() == "wal"
            timeout = await conn.execute(text("PRAGMA busy_timeout"))
            assert timeout.scalar_one() == 30000
            synchronous = await conn.execute(text("PRAGMA synchronous"))
            assert synchronous.scalar_one() == 1
            await conn.execute(
                text(
                    "create table write_check "
                    "(id integer primary key, value text not null)"
                )
            )
            await conn.execute(text("insert into write_check(value) values ('ok')"))
    finally:
        await engine.dispose()


def test_sqlite_pragmas_tolerate_locked_journal_mode() -> None:
    class Cursor:
        def __init__(self) -> None:
            self.closed = False
            self.statements: list[str] = []

        def execute(self, statement: str) -> None:
            self.statements.append(statement)
            if statement == "PRAGMA journal_mode=WAL":
                raise sqlite3.OperationalError("database is locked")

        def close(self) -> None:
            self.closed = True

    class Connection:
        def __init__(self) -> None:
            self.cursor_obj = Cursor()

        def cursor(self) -> Cursor:
            return self.cursor_obj

    connection = Connection()

    _apply_sqlite_pragmas(connection)

    assert connection.cursor_obj.closed is True
    assert connection.cursor_obj.statements == [
        "PRAGMA busy_timeout=30000",
        "PRAGMA journal_mode=WAL",
        "PRAGMA synchronous=NORMAL",
    ]


def test_sqlite_pragmas_raise_unexpected_journal_errors() -> None:
    class Cursor:
        def execute(self, statement: str) -> None:
            if statement == "PRAGMA journal_mode=WAL":
                raise sqlite3.OperationalError("disk I/O error")

        def close(self) -> None:
            pass

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        _apply_sqlite_pragmas(Connection())


@pytest.mark.asyncio
async def test_sqlite_file_engine_uses_default_async_queue_pool(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "cancel-safe.db"
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        assert isinstance(engine.sync_engine.pool, AsyncAdaptedQueuePool)
    finally:
        await engine.dispose()


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


async def test_list_organizations_orders_newest_first(session: AsyncSession) -> None:
    older = Organization(
        url_key="older",
        name="Older",
        issue_prefix="OLD",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    newer = Organization(
        url_key="newer",
        name="Newer",
        issue_prefix="NEW",
        created_at=datetime(2026, 6, 1, tzinfo=UTC),
    )
    async with async_transaction(session):
        session.add_all([older, newer])
    rows = await list_organizations(session)
    assert [row.url_key for row in rows] == ["newer", "older"]


async def test_list_org_issues_filters_by_org(session: AsyncSession) -> None:
    org_a = Organization(url_key="a", name="A", issue_prefix="AAA")
    org_b = Organization(url_key="b", name="B", issue_prefix="BBB")
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


async def test_create_issue_persists_row(session: AsyncSession) -> None:
    org = Organization(url_key="issue-org", name="Issue Org", issue_prefix="IOR")
    async with async_transaction(session):
        session.add(org)

    async with async_transaction(session):
        created = await create_issue(
            session,
            {
                "org_id": org.id,
                "title": "Created issue",
                "status": "todo",
                "project_id": "proj-1",
                "goal_id": "goal-1",
                "assignee_agent_id": "agent-1",
                "origin_kind": "manual",
                "origin_id": "origin-1",
            },
        )

    assert created.org_id == org.id
    assert created.title == "Created issue"
    assert created.status == "todo"
    assert created.project_id == "proj-1"
    assert created.goal_id == "goal-1"
    assert created.assignee_agent_id == "agent-1"


async def test_update_issue_returns_updated_row(session: AsyncSession) -> None:
    org = Organization(
        url_key="upd-issue-org", name="Upd Issue Org", issue_prefix="UIO"
    )
    async with async_transaction(session):
        session.add(org)
    async with async_transaction(session):
        issue = await create_issue(
            session,
            {
                "org_id": org.id,
                "title": "Old title",
                "status": "todo",
                "origin_kind": "manual",
            },
        )

    async with async_transaction(session):
        updated = await update_issue(
            session,
            issue.id,
            {"title": "New title", "status": "in_progress"},
        )

    assert updated is not None
    assert updated.title == "New title"
    assert updated.status == "in_progress"
    assert updated.updated_at is not None


async def test_list_org_issues_supports_first_batch_filters(
    session: AsyncSession,
) -> None:
    org = Organization(url_key="filter-org", name="Filter Org", issue_prefix="FIL")
    async with async_transaction(session):
        session.add(org)
    async with async_transaction(session):
        await create_issue(
            session,
            {
                "org_id": org.id,
                "title": "Match me",
                "status": "todo",
                "project_id": "proj-1",
                "goal_id": "goal-1",
                "assignee_agent_id": "agent-1",
                "origin_kind": "manual",
                "origin_id": "origin-1",
            },
        )
        await create_issue(
            session,
            {
                "org_id": org.id,
                "title": "Skip me",
                "status": "done",
                "project_id": "proj-2",
                "goal_id": "goal-2",
                "assignee_agent_id": "agent-2",
                "origin_kind": "automation_execution",
                "origin_id": "origin-2",
            },
        )

    rows = await list_org_issues(
        session,
        org.id,
        status="todo",
        assignee_agent_id="agent-1",
        project_id="proj-1",
        goal_id="goal-1",
        origin_kind="manual",
        origin_id="origin-1",
    )

    assert [row.title for row in rows] == ["Match me"]


async def test_insert_and_list_issue_comments(session: AsyncSession) -> None:
    org = Organization(url_key="comment-org", name="Comment Org", issue_prefix="COM")
    async with async_transaction(session):
        session.add(org)
    async with async_transaction(session):
        issue = await create_issue(
            session,
            {"org_id": org.id, "title": "Commented", "origin_kind": "manual"},
        )
    async with async_transaction(session):
        first = await insert_issue_comment(
            session,
            {
                "org_id": org.id,
                "issue_id": issue.id,
                "author_user_id": "user-1",
                "body": "first",
            },
        )
        second = await insert_issue_comment(
            session,
            {
                "org_id": org.id,
                "issue_id": issue.id,
                "author_user_id": "user-2",
                "body": "second",
            },
        )

    rows = await list_issue_comments(session, issue.id)

    assert [row.id for row in rows] == [first.id, second.id]
    assert [row.body for row in rows] == ["first", "second"]
    assert rows[0].author_user_id == "user-1"


async def test_issue_comments_monotonically_increment_created_at(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_now = datetime(2026, 5, 27, 12, 0, 0, tzinfo=UTC)

    class FrozenDateTime:
        @classmethod
        def now(cls, tz: object | None = None) -> datetime:
            assert tz is UTC
            return fixed_now

    monkeypatch.setattr(issue_comment_queries, "datetime", FrozenDateTime)

    async with async_transaction(session):
        org = Organization(
            url_key="ordered-comment-org", name="Comments", issue_prefix="OCM"
        )
        session.add(org)
    async with async_transaction(session):
        issue = await create_issue(
            session, {"org_id": org.id, "title": "Ordered", "origin_kind": "manual"}
        )
    async with async_transaction(session):
        first = await insert_issue_comment(
            session, {"org_id": org.id, "issue_id": issue.id, "body": "first"}
        )
        second = await insert_issue_comment(
            session, {"org_id": org.id, "issue_id": issue.id, "body": "second"}
        )

    assert second.created_at > first.created_at


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


async def test_create_approval_persists_row(session: AsyncSession) -> None:
    org = Organization(url_key="approval-org", name="Approval Org", issue_prefix="APR")
    async with async_transaction(session):
        session.add(org)

    async with async_transaction(session):
        created = await create_approval(
            session,
            {
                "org_id": org.id,
                "type": "hire_agent",
                "status": "pending",
                "requested_by_agent_id": "agent-1",
                "payload": {"agentId": "agent-1"},
            },
        )

    assert created.org_id == org.id
    assert created.type == "hire_agent"
    assert created.status == "pending"
    assert created.requested_by_agent_id == "agent-1"
    assert created.payload == {"agentId": "agent-1"}


async def test_update_approval_sets_decision_fields(session: AsyncSession) -> None:
    async with async_transaction(session):
        org = Organization(
            url_key="approval-upd-org",
            name="Approval Upd Org",
            issue_prefix="APU",
        )
        session.add(org)
    async with async_transaction(session):
        approval = Approval(org_id=org.id, type="hire_agent", payload={})
        session.add(approval)

    before_updated_at = approval.updated_at

    async with async_transaction(session):
        updated = await update_approval(
            session,
            approval.id,
            {
                "status": "approved",
                "decision_note": "looks good",
                "decided_by_user_id": "user-1",
            },
        )

    assert updated is not None
    assert updated.status == "approved"
    assert updated.decision_note == "looks good"
    assert updated.decided_by_user_id == "user-1"
    assert updated.decided_at is not None
    assert updated.updated_at is not None
    assert updated.updated_at != before_updated_at


async def test_list_org_approvals_filters_by_status(session: AsyncSession) -> None:
    async with async_transaction(session):
        org = Organization(
            url_key="approval-filter-org",
            name="Approval Filter Org",
            issue_prefix="APF",
        )
        session.add(org)
    async with async_transaction(session):
        session.add_all(
            [
                Approval(
                    org_id=org.id,
                    type="hire_agent",
                    status="pending",
                    payload={},
                ),
                Approval(
                    org_id=org.id,
                    type="hire_agent",
                    status="approved",
                    payload={},
                ),
            ]
        )

    rows = await list_org_approvals(session, org.id, status="approved")

    assert [row.status for row in rows] == ["approved"]


async def test_recover_blocked_linked_issues_for_approval_updates_target_statuses(
    session: AsyncSession,
) -> None:
    async with async_transaction(session):
        org = Organization(
            url_key="approval-link-org",
            name="Approval Link Org",
            issue_prefix="APL",
        )
        session.add(org)
    async with async_transaction(session):
        issue_with_assignee = Issue(
            org_id=org.id,
            title="Blocked with assignee",
            status="blocked",
            assignee_agent_id="agent-1",
            origin_kind="manual",
        )
        issue_without_assignee = Issue(
            org_id=org.id,
            title="Blocked without assignee",
            status="blocked",
            origin_kind="manual",
        )
        issue_not_blocked = Issue(
            org_id=org.id,
            title="Already todo",
            status="todo",
            origin_kind="manual",
        )
        approval = Approval(org_id=org.id, type="hire_agent", payload={})
        session.add_all(
            [issue_with_assignee, issue_without_assignee, issue_not_blocked, approval]
        )

    async with async_transaction(session):
        session.add_all(
            [
                IssueApproval(
                    org_id=org.id,
                    issue_id=issue_with_assignee.id,
                    approval_id=approval.id,
                ),
                IssueApproval(
                    org_id=org.id,
                    issue_id=issue_without_assignee.id,
                    approval_id=approval.id,
                ),
                IssueApproval(
                    org_id=org.id,
                    issue_id=issue_not_blocked.id,
                    approval_id=approval.id,
                ),
            ]
        )

    async with async_transaction(session):
        recovered = await recover_blocked_linked_issues_for_approval(
            session, approval.id
        )

    assert {row.id: row.status for row in recovered} == {
        issue_with_assignee.id: "in_progress",
        issue_without_assignee.id: "todo",
    }


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


async def test_update_organization_returns_updated_row(session: AsyncSession) -> None:
    async with async_transaction(session):
        session.add(
            Organization(
                id="org-upd-1",
                url_key="o-upd-1",
                name="Old Name",
                issue_prefix="OUP",
                description="old desc",
            )
        )

    async with async_transaction(session):
        updated = await update_organization(
            session,
            "org-upd-1",
            {"name": "New Name", "description": None},
        )

    assert updated is not None
    assert updated.name == "New Name"
    assert updated.description is None
    assert updated.updated_at is not None


async def test_update_organization_missing_returns_none(session: AsyncSession) -> None:
    async with async_transaction(session):
        result = await update_organization(session, "no-such-org", {"name": "x"})
    assert result is None


async def test_update_organization_empty_fields_returns_current(
    session: AsyncSession,
) -> None:
    async with async_transaction(session):
        session.add(
            Organization(
                id="org-upd-2",
                url_key="o-upd-2",
                name="Keep",
                issue_prefix="OK1",
            )
        )

    result = await update_organization(session, "org-upd-2", {})
    assert result is not None
    assert result.name == "Keep"


async def test_insert_activity_log_persists_row(session: AsyncSession) -> None:
    async with async_transaction(session):
        session.add(
            Organization(id="org-act", url_key="o-act", name="A", issue_prefix="AAA")
        )

    async with async_transaction(session):
        row = await insert_activity_log(
            session,
            org_id="org-act",
            actor_type="board",
            actor_id="user-1",
            action="organization.updated",
            entity_type="organization",
            entity_id="org-act",
            details={"name": "renamed"},
        )

    assert row.id is not None
    assert row.org_id == "org-act"
    assert row.action == "organization.updated"
    assert row.entity_type == "organization"
    assert row.entity_id == "org-act"
    assert row.details == {"name": "renamed"}
    assert row.created_at is not None


async def test_insert_activity_log_monotonically_increments_created_at(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_now = datetime(2026, 5, 26, 12, 0, 0, tzinfo=UTC)

    class FrozenDateTime:
        @classmethod
        def now(cls, tz: object | None = None) -> datetime:
            assert tz is UTC
            return fixed_now

    monkeypatch.setattr(activity_log_queries, "datetime", FrozenDateTime)

    async with async_transaction(session):
        session.add(
            Organization(
                id="org-act-2", url_key="o-act-2", name="B", issue_prefix="BBB"
            )
        )

    async with async_transaction(session):
        first = await insert_activity_log(
            session,
            org_id="org-act-2",
            actor_type="board",
            actor_id="user-1",
            action="approval.created",
            entity_type="approval",
            entity_id="approval-1",
        )
        second = await insert_activity_log(
            session,
            org_id="org-act-2",
            actor_type="board",
            actor_id="user-1",
            action="approval.approved",
            entity_type="approval",
            entity_id="approval-1",
        )

    assert second.created_at > first.created_at
