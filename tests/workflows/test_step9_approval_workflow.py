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
from packages.database.schema import (
    ActivityLog,
    Approval,
    Base,
    Issue,
    IssueApproval,
    Organization,
)
from server.services.approvals import ApprovalService


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
    org = Organization(
        url_key="approval-workflow-org",
        name="Approval Workflow Org",
        issue_prefix="AWF",
    )
    async with async_transaction(session):
        session.add(org)
    return org


async def _seed_approval(
    session: AsyncSession,
    org_id: str,
    *,
    status: str = "pending",
    payload: dict[str, object] | None = None,
    requested_by_agent_id: str | None = None,
) -> Approval:
    approval = Approval(
        org_id=org_id,
        type="hire_agent",
        status=status,
        requested_by_agent_id=requested_by_agent_id,
        payload=payload or {"reason": "demo"},
    )
    async with async_transaction(session):
        session.add(approval)
    return approval


async def test_create_approval_writes_activity(session: AsyncSession) -> None:
    org = await _seed_org(session)
    service = ApprovalService(session)

    async with async_transaction(session):
        created = await service.create_approval(
            org.id,
            {"type": "hire_agent", "payload": {"agentId": "agent-1"}},
            actor_type="board",
            actor_id="user-1",
        )

    assert created["orgId"] == org.id
    assert created["status"] == "pending"
    assert created["type"] == "hire_agent"

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == ["approval.created"]
    assert rows[0].entity_id == created["id"]


async def test_create_approval_rejects_issue_from_another_organization(
    session: AsyncSession,
) -> None:
    org = await _seed_org(session)
    other_org = Organization(
        url_key="other-approval-workflow-org",
        name="Other Approval Workflow Org",
        issue_prefix="OAW",
    )
    async with async_transaction(session):
        session.add(other_org)
    async with async_transaction(session):
        issue = Issue(
            org_id=other_org.id,
            title="Foreign issue",
            status="todo",
            origin_kind="manual",
        )
        session.add(issue)

    service = ApprovalService(session)
    with pytest.raises(ValueError, match="same organization"):
        async with async_transaction(session):
            await service.create_approval(
                org.id,
                {
                    "type": "hire_agent",
                    "payload": {},
                    "issueIds": [issue.id],
                },
                actor_type="board",
                actor_id="user-1",
            )


async def test_approve_approval_writes_activity(session: AsyncSession) -> None:
    org = await _seed_org(session)
    approval = await _seed_approval(session, org.id)
    service = ApprovalService(session)

    async with async_transaction(session):
        updated = await service.approve_approval(
            approval.id,
            {"decisionNote": "ship it", "decidedByUserId": "board-1"},
            actor_type="board",
            actor_id="board-1",
        )

    assert updated is not None
    assert updated["status"] == "approved"
    assert updated["decisionNote"] == "ship it"
    assert updated["decidedByUserId"] == "board-1"

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == ["approval.approved"]


async def test_reject_approval_writes_activity(session: AsyncSession) -> None:
    org = await _seed_org(session)
    approval = await _seed_approval(session, org.id)
    service = ApprovalService(session)

    async with async_transaction(session):
        updated = await service.reject_approval(
            approval.id,
            {"decisionNote": "not now", "decidedByUserId": "board-2"},
            actor_type="board",
            actor_id="board-2",
        )

    assert updated is not None
    assert updated["status"] == "rejected"

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == ["approval.rejected"]


async def test_request_revision_writes_activity(session: AsyncSession) -> None:
    org = await _seed_org(session)
    approval = await _seed_approval(session, org.id)
    service = ApprovalService(session)

    async with async_transaction(session):
        updated = await service.request_revision(
            approval.id,
            {"decisionNote": "revise", "decidedByUserId": "board-3"},
            actor_type="board",
            actor_id="board-3",
        )

    assert updated is not None
    assert updated["status"] == "revision_requested"
    assert updated["decisionNote"] == "revise"

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == ["approval.revision_requested"]


async def test_resubmit_approval_writes_activity(session: AsyncSession) -> None:
    org = await _seed_org(session)
    approval = await _seed_approval(
        session,
        org.id,
        status="revision_requested",
        payload={"agentToken": "secret-token"},
        requested_by_agent_id="agent-9",
    )
    service = ApprovalService(session)

    async with async_transaction(session):
        updated = await service.resubmit_approval(
            approval.id,
            {"payload": {"agentToken": "new-secret"}},
            actor_type="agent",
            actor_id="agent-9",
        )

    assert updated is not None
    assert updated["status"] == "pending"
    assert updated["decisionNote"] is None
    assert updated["decidedByUserId"] is None

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == ["approval.resubmitted"]


async def test_approval_detail_redacts_sensitive_payload(session: AsyncSession) -> None:
    org = await _seed_org(session)
    approval = await _seed_approval(
        session,
        org.id,
        payload={
            "accessToken": "secret",
            "nested": {"apiKey": "hidden"},
            "reason": "visible",
        },
    )
    service = ApprovalService(session)

    detail = await service.get_by_id(approval.id)

    assert detail is not None
    assert detail["payload"]["accessToken"] == "[REDACTED]"
    assert detail["payload"]["nested"]["apiKey"] == "[REDACTED]"
    assert detail["payload"]["reason"] == "visible"


async def test_approve_linked_blocked_issue_with_assignee_recovers_in_progress(
    session: AsyncSession,
) -> None:
    org = await _seed_org(session)
    approval = await _seed_approval(session, org.id)
    async with async_transaction(session):
        issue = Issue(
            org_id=org.id,
            title="Blocked linked",
            status="blocked",
            assignee_agent_id="agent-1",
            origin_kind="manual",
        )
        session.add(issue)
    async with async_transaction(session):
        session.add(
            IssueApproval(org_id=org.id, issue_id=issue.id, approval_id=approval.id)
        )

    service = ApprovalService(session)
    async with async_transaction(session):
        updated = await service.approve_approval(
            approval.id,
            {"decisionNote": "go", "decidedByUserId": "board-1"},
            actor_type="board",
            actor_id="board-1",
        )

    assert updated is not None
    refreshed_issue = await session.get(Issue, issue.id)
    assert refreshed_issue is not None
    assert refreshed_issue.status == "in_progress"

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    rows = result.scalars().all()
    assert [row.action for row in rows] == [
        "approval.approved",
        "approval.linked_issue_assignee_wakeup_queued",
    ]


async def test_approve_linked_blocked_issue_without_assignee_recovers_todo(
    session: AsyncSession,
) -> None:
    org = await _seed_org(session)
    approval = await _seed_approval(session, org.id)
    async with async_transaction(session):
        issue = Issue(
            org_id=org.id,
            title="Blocked linked no assignee",
            status="blocked",
            origin_kind="manual",
        )
        session.add(issue)
    async with async_transaction(session):
        session.add(
            IssueApproval(org_id=org.id, issue_id=issue.id, approval_id=approval.id)
        )

    service = ApprovalService(session)
    async with async_transaction(session):
        updated = await service.approve_approval(
            approval.id,
            {"decisionNote": "go", "decidedByUserId": "board-2"},
            actor_type="board",
            actor_id="board-2",
        )

    assert updated is not None
    refreshed_issue = await session.get(Issue, issue.id)
    assert refreshed_issue is not None
    assert refreshed_issue.status == "todo"
