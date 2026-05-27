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
from packages.database.schema import ActivityLog, Base, Organization
from server.services.agents import AgentService
from server.services.goals import GoalConflictError, GoalService
from server.services.issues import IssueService
from server.services.projects import ProjectService


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
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    async with factory() as active_session:
        yield active_session


async def _seed_org(session: AsyncSession, key: str) -> Organization:
    org = Organization(url_key=key, name=key, issue_prefix=key[:6].upper())
    async with async_transaction(session):
        session.add(org)
    return org


async def test_goal_hierarchy_owner_scope_and_activity(session: AsyncSession) -> None:
    org = await _seed_org(session, "goal-flow")
    foreign_org = await _seed_org(session, "foreign-goal")
    org_id = org.id
    foreign_org_id = foreign_org.id
    agent_service = AgentService(session)
    goal_service = GoalService(session)
    async with async_transaction(session):
        owner = await agent_service.create_agent(
            org_id, {"name": "Owner"}, actor_type="board", actor_id="board"
        )
        foreign_owner = await agent_service.create_agent(
            foreign_org_id,
            {"name": "Foreign"},
            actor_type="board",
            actor_id="board",
        )
        root = await goal_service.create(
            org_id,
            {
                "title": "Root",
                "level": "organization",
                "status": "active",
                "ownerAgentId": owner["id"],
            },
            actor_type="board",
            actor_id="board",
        )
        child = await goal_service.create(
            org_id,
            {"title": "Child", "parentId": root["id"]},
            actor_type="board",
            actor_id="board",
        )

    with pytest.raises(ValueError, match="owner"):
        async with async_transaction(session):
            await goal_service.update(
                child["id"],
                {"ownerAgentId": foreign_owner["id"]},
                actor_type="board",
                actor_id="board",
            )
    with pytest.raises(ValueError, match="cycle"):
        async with async_transaction(session):
            await goal_service.update(
                root["id"],
                {"parentId": child["id"]},
                actor_type="board",
                actor_id="board",
            )

    dependencies = await goal_service.dependencies(root)
    assert dependencies["blockers"] == ["last_root_organization_goal", "child_goals"]

    rows = (
        (
            await session.execute(
                select(ActivityLog)
                .where(ActivityLog.org_id == org_id)
                .order_by(ActivityLog.created_at, ActivityLog.id)
            )
        )
        .scalars()
        .all()
    )
    assert [row.action for row in rows] == [
        "agent.created",
        "goal.created",
        "goal.created",
    ]


async def test_project_goal_links_issue_fallback_and_delete_blocker(
    session: AsyncSession,
) -> None:
    org = await _seed_org(session, "goal-links")
    goal_service = GoalService(session)
    project_service = ProjectService(session)
    issue_service = IssueService(session)
    async with async_transaction(session):
        root = await goal_service.create(
            org.id,
            {"title": "Root", "level": "organization", "status": "active"},
            actor_type="board",
            actor_id="board",
        )
        task = await goal_service.create(
            org.id,
            {"title": "Standalone"},
            actor_type="board",
            actor_id="board",
        )
        project = await project_service.create_project(
            org.id,
            {"name": "Delivery", "goalIds": [root["id"]]},
            actor_type="board",
            actor_id="board",
        )
        issue = await issue_service.create_issue(
            org.id,
            {"title": "Default Goal Issue"},
            actor_type="board",
            actor_id="board",
        )

    assert project["goalId"] == root["id"]
    assert project["goalIds"] == [root["id"]]
    assert issue["goalId"] == root["id"]
    dependencies = await goal_service.dependencies(root)
    assert dependencies["counts"]["linkedProjects"] == 1
    assert dependencies["counts"]["linkedIssues"] == 1
    await session.rollback()

    with pytest.raises(GoalConflictError):
        async with async_transaction(session):
            await goal_service.remove(root["id"], actor_type="board", actor_id="board")

    async with async_transaction(session):
        deleted = await goal_service.remove(
            task["id"], actor_type="board", actor_id="board"
        )
    assert deleted is not None
    assert deleted["id"] == task["id"]
