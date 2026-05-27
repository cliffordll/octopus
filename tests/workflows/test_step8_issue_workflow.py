from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from packages.database.clients import (
    async_transaction,
    create_database_engine,
    create_session_factory,
)
from packages.database.schema import ActivityLog, Base, IssueComment, Organization
from server.services.issues import IssueService


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


async def _seed_org(session: AsyncSession) -> Organization:
    org = Organization(url_key="workflow-org", name="Workflow Org", issue_prefix="WFO")
    async with async_transaction(session):
        session.add(org)
    return org


async def test_create_issue_writes_activity(session: AsyncSession) -> None:
    org = await _seed_org(session)
    service = IssueService(session)

    async with async_transaction(session):
        created = await service.create_issue(
            org.id,
            {"title": "Created in workflow", "status": "todo", "originKind": "manual"},
            actor_type="board",
            actor_id="user-1",
        )

    assert created["orgId"] == org.id
    assert created["title"] == "Created in workflow"
    assert created["status"] == "todo"

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert len(rows) == 1
    assert rows[0].action == "issue.created"
    assert rows[0].entity_id == created["id"]
    assert rows[0].actor_type == "board"


async def test_update_issue_writes_activity(session: AsyncSession) -> None:
    org = await _seed_org(session)
    service = IssueService(session)

    async with async_transaction(session):
        created = await service.create_issue(
            org.id,
            {"title": "Before update", "status": "todo", "originKind": "manual"},
            actor_type="board",
            actor_id="user-1",
        )

    async with async_transaction(session):
        updated = await service.update_issue(
            created["id"],
            {"title": "After update", "status": "in_progress"},
            actor_type="board",
            actor_id="user-2",
        )

    assert updated is not None
    assert updated["title"] == "After update"
    assert updated["status"] == "in_progress"

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == ["issue.created", "issue.updated"]
    assert rows[-1].actor_id == "user-2"


async def test_add_comment_writes_activity(session: AsyncSession) -> None:
    org = await _seed_org(session)
    service = IssueService(session)

    async with async_transaction(session):
        created = await service.create_issue(
            org.id,
            {"title": "Comment target", "status": "todo", "originKind": "manual"},
            actor_type="board",
            actor_id="user-1",
        )

    async with async_transaction(session):
        comment = await service.add_comment(
            created["id"],
            {"body": "Looks good"},
            actor_type="board",
            actor_id="user-3",
        )

    assert comment.body == "Looks good"

    comment_row = await session.get(IssueComment, comment.id)
    assert comment_row is not None
    assert comment_row.issue_id == created["id"]

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == ["issue.created", "issue.comment_added"]
    assert rows[-1].entity_id == created["id"]


async def test_empty_update_does_not_write_activity(session: AsyncSession) -> None:
    org = await _seed_org(session)
    service = IssueService(session)

    async with async_transaction(session):
        created = await service.create_issue(
            org.id,
            {"title": "No-op target", "status": "todo", "originKind": "manual"},
            actor_type="board",
            actor_id="user-1",
        )

    async with async_transaction(session):
        updated = await service.update_issue(
            created["id"],
            {},
            actor_type="board",
            actor_id="user-4",
        )

    assert updated is not None
    assert updated["id"] == created["id"]

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == ["issue.created"]


async def test_review_approve_moves_issue_to_done(session: AsyncSession) -> None:
    org = await _seed_org(session)
    service = IssueService(session)

    async with async_transaction(session):
        created = await service.create_issue(
            org.id,
            {"title": "Review approve", "status": "in_review", "originKind": "manual"},
            actor_type="board",
            actor_id="user-1",
        )

    async with async_transaction(session):
        updated = await service.update_issue(
            created["id"],
            {"reviewDecision": {"decision": "approve"}},
            actor_type="board",
            actor_id="reviewer-1",
        )

    assert updated is not None
    assert updated["status"] == "done"

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == [
        "issue.created",
        "issue.review_decision_recorded",
    ]


async def test_review_request_changes_moves_issue_back_to_in_progress(
    session: AsyncSession,
) -> None:
    org = await _seed_org(session)
    service = IssueService(session)

    async with async_transaction(session):
        created = await service.create_issue(
            org.id,
            {
                "title": "Review changes",
                "status": "in_review",
                "originKind": "manual",
            },
            actor_type="board",
            actor_id="user-1",
        )

    async with async_transaction(session):
        updated = await service.update_issue(
            created["id"],
            {"reviewDecision": {"decision": "request_changes"}},
            actor_type="board",
            actor_id="reviewer-2",
        )

    assert updated is not None
    assert updated["status"] == "in_progress"


async def test_review_needs_followup_keeps_status_and_writes_intervention_activity(
    session: AsyncSession,
) -> None:
    org = await _seed_org(session)
    service = IssueService(session)

    async with async_transaction(session):
        created = await service.create_issue(
            org.id,
            {
                "title": "Needs followup",
                "status": "in_review",
                "originKind": "manual",
            },
            actor_type="board",
            actor_id="user-1",
        )

    async with async_transaction(session):
        updated = await service.update_issue(
            created["id"],
            {"reviewDecision": {"decision": "needs_followup"}},
            actor_type="board",
            actor_id="reviewer-3",
        )

    assert updated is not None
    assert updated["status"] == "in_review"

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == [
        "issue.created",
        "issue.review_decision_recorded",
        "issue.human_intervention_required",
    ]


async def test_review_decision_rejected_outside_reviewable_status(
    session: AsyncSession,
) -> None:
    org = await _seed_org(session)
    service = IssueService(session)

    async with async_transaction(session):
        created = await service.create_issue(
            org.id,
            {"title": "Wrong status", "status": "todo", "originKind": "manual"},
            actor_type="board",
            actor_id="user-1",
        )

    with pytest.raises(ValueError, match="review decision"):
        async with async_transaction(session):
            await service.update_issue(
                created["id"],
                {"reviewDecision": {"decision": "approve"}},
                actor_type="board",
                actor_id="reviewer-4",
            )


async def test_reopen_without_explicit_status_returns_to_todo(
    session: AsyncSession,
) -> None:
    org = await _seed_org(session)
    service = IssueService(session)

    async with async_transaction(session):
        created = await service.create_issue(
            org.id,
            {"title": "Reopen me", "status": "done", "originKind": "manual"},
            actor_type="board",
            actor_id="user-1",
        )

    async with async_transaction(session):
        reopened = await service.update_issue(
            created["id"],
            {"reopen": True},
            actor_type="board",
            actor_id="user-5",
        )

    assert reopened is not None
    assert reopened["status"] == "todo"
