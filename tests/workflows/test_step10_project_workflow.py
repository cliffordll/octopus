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
async def session(
    engine: AsyncEngine,
) -> AsyncIterator[AsyncSession]:
    factory: async_sessionmaker[AsyncSession] = create_session_factory(engine)
    async with factory() as session:
        yield session


async def _seed_org(session: AsyncSession) -> Organization:
    org = Organization(url_key="project-workflow", name="Projects", issue_prefix="PRJ")
    async with async_transaction(session):
        session.add(org)
    return org


async def test_create_project_with_inline_resource_writes_activity(
    session: AsyncSession,
) -> None:
    from server.services.projects import ProjectService

    org = await _seed_org(session)
    service = ProjectService(session)

    async with async_transaction(session):
        created = await service.create_project(
            org.id,
            {
                "name": "Agent Workspace",
                "newResources": [
                    {
                        "name": "Repository",
                        "kind": "directory",
                        "locator": "D:/coding/octopus",
                        "role": "working_set",
                    }
                ],
            },
            actor_type="board",
            actor_id="user-1",
        )

    assert created["status"] == "backlog"
    assert created["resources"][0]["resource"]["name"] == "Repository"
    assert created["resources"][0]["role"] == "working_set"

    result = await session.execute(
        select(ActivityLog).where(ActivityLog.org_id == org.id)
    )
    assert [row.action for row in result.scalars().all()] == ["project.created"]


async def test_project_resource_attachment_lifecycle_writes_activity(
    session: AsyncSession,
) -> None:
    from server.services.projects import ProjectService

    org = await _seed_org(session)
    service = ProjectService(session)

    async with async_transaction(session):
        created = await service.create_project(
            org.id,
            {
                "name": "Resource Target",
                "newResources": [
                    {"name": "Spec", "kind": "file", "locator": "docs/spec.md"}
                ],
            },
            actor_type="board",
            actor_id="user-1",
        )
    attachment = created["resources"][0]

    async with async_transaction(session):
        updated = await service.update_resource_attachment(
            created["id"],
            attachment["id"],
            {"role": "reference", "note": "Read first"},
            actor_type="board",
            actor_id="user-2",
        )
    assert updated is not None
    assert updated["note"] == "Read first"

    async with async_transaction(session):
        removed = await service.remove_resource_attachment(
            created["id"],
            attachment["id"],
            actor_type="board",
            actor_id="user-3",
        )
    assert removed is not None

    result = await session.execute(
        select(ActivityLog)
        .where(ActivityLog.org_id == org.id)
        .order_by(ActivityLog.created_at, ActivityLog.id)
    )
    assert [row.action for row in result.scalars().all()] == [
        "project.created",
        "project.resource.updated",
        "project.resource.detached",
    ]


async def test_adding_existing_resource_updates_attachment_in_place(
    session: AsyncSession,
) -> None:
    from server.services.projects import ProjectService

    org = await _seed_org(session)
    service = ProjectService(session)
    async with async_transaction(session):
        created = await service.create_project(
            org.id,
            {
                "name": "Attachment Target",
                "newResources": [
                    {
                        "name": "Repo",
                        "kind": "directory",
                        "locator": "D:/coding/upstream-reference",
                    }
                ],
            },
            actor_type="board",
            actor_id="user-1",
        )
    original = created["resources"][0]

    async with async_transaction(session):
        attached = await service.add_resource_attachment(
            created["id"],
            {"resourceId": original["resourceId"], "role": "working_set"},
            actor_type="board",
            actor_id="user-2",
        )

    assert attached is not None
    assert attached["id"] == original["id"]
    assert attached["role"] == "working_set"
    assert len(await service.list_resources(created["id"])) == 1


async def test_update_project_replaces_existing_resource_attachment_set(
    session: AsyncSession,
) -> None:
    from server.services.projects import ProjectService

    org = await _seed_org(session)
    service = ProjectService(session)
    async with async_transaction(session):
        created = await service.create_project(
            org.id,
            {
                "name": "Resource Replacement",
                "newResources": [
                    {"name": "First", "kind": "file", "locator": "docs/first.md"},
                    {"name": "Second", "kind": "file", "locator": "docs/second.md"},
                ],
            },
            actor_type="board",
            actor_id="user-1",
        )
    second = created["resources"][1]

    async with async_transaction(session):
        updated = await service.update_project(
            created["id"],
            {
                "resourceAttachments": [
                    {"resourceId": second["resourceId"], "role": "deliverable"}
                ]
            },
            actor_type="board",
            actor_id="user-2",
        )

    assert updated is not None
    assert len(updated["resources"]) == 1
    assert updated["resources"][0]["resourceId"] == second["resourceId"]
    assert updated["resources"][0]["role"] == "deliverable"
