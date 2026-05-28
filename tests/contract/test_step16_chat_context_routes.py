from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.migrations.runner import upgrade_to_head
from packages.database.schema import Agent, Base, Issue, Organization, Project
from server.app import create_app


def test_step16_chat_context_table_is_registered() -> None:
    from packages.database import schema

    assert isinstance(schema.ChatContextLink.__table__, Table)
    assert schema.ChatContextLink.__tablename__ == "chat_context_links"
    assert "chat_context_links" in {table.name for table in Base.metadata.sorted_tables}


async def test_upgrade_to_head_creates_chat_context_links_table(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "step16-chat-context-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")
    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master where type='table' and name = "
                    "'chat_context_links'"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()
    assert names == {"chat_context_links"}


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker]]:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    application = create_app()
    application.state.session_factory = factory
    try:
        yield application, factory
    finally:
        await engine.dispose()


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, json=json)
    return response.status_code, response.json()


async def _seed_context(factory: async_sessionmaker) -> dict[str, str]:
    org_id = str(uuid.uuid4())
    other_org_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    other_issue_id = str(uuid.uuid4())
    async with factory() as session:
        session.add_all(
            [
                Organization(
                    id=org_id,
                    url_key="step-16-context",
                    name="Step 16 Context",
                    issue_prefix="CTX",
                ),
                Organization(
                    id=other_org_id,
                    url_key="step-16-context-other",
                    name="Step 16 Context Other",
                    issue_prefix="OCX",
                ),
                Issue(
                    id=issue_id,
                    org_id=org_id,
                    title="Context issue",
                    identifier="CTX-1",
                    description="Issue context body",
                ),
                Issue(
                    id=other_issue_id,
                    org_id=other_org_id,
                    title="Other issue",
                    identifier="OCX-1",
                ),
                Project(
                    id=project_id,
                    org_id=org_id,
                    name="Context project",
                    description="Project context body",
                ),
                Agent(
                    id=agent_id,
                    org_id=org_id,
                    name="Context agent",
                    title="Agent title",
                ),
            ]
        )
        await session.commit()
    return {
        "org_id": org_id,
        "issue_id": issue_id,
        "project_id": project_id,
        "agent_id": agent_id,
        "other_issue_id": other_issue_id,
    }


async def test_create_and_append_context_links(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    seeded = await _seed_context(factory)

    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{seeded['org_id']}/chats",
        json={
            "title": "Context chat",
            "contextLinks": [
                {
                    "entityType": "issue",
                    "entityId": seeded["issue_id"],
                    "metadata": {"source": "test"},
                }
            ],
        },
    )
    assert create_code == 201
    assert created["contextLinks"][0]["entityType"] == "issue"
    assert created["contextLinks"][0]["entity"]["label"] == "Context issue"
    assert created["contextLinks"][0]["entity"]["identifier"] == "CTX-1"
    assert created["contextLinks"][0]["metadata"] == {"source": "test"}

    link_code, linked = await _request(
        application,
        "POST",
        f"/api/chats/{created['id']}/context-links",
        json={"entityType": "agent", "entityId": seeded["agent_id"]},
    )
    assert link_code == 201
    assert linked["entityType"] == "agent"
    assert linked["entity"]["label"] == "Context agent"

    detail_code, detail = await _request(
        application, "GET", f"/api/chats/{created['id']}"
    )
    assert detail_code == 200
    assert {
        (link["entityType"], link["entityId"]) for link in detail["contextLinks"]
    } == {
        ("issue", seeded["issue_id"]),
        ("agent", seeded["agent_id"]),
    }

    cross_code, cross = await _request(
        application,
        "POST",
        f"/api/chats/{created['id']}/context-links",
        json={"entityType": "issue", "entityId": seeded["other_issue_id"]},
    )
    assert cross_code == 422
    assert "same organization" in cross["detail"]


async def test_project_context_replaces_project_link_before_messages(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    seeded = await _seed_context(factory)
    create_code, created = await _request(
        application,
        "POST",
        f"/api/orgs/{seeded['org_id']}/chats",
        json={"title": "Project context"},
    )
    assert create_code == 201

    project_code, updated = await _request(
        application,
        "POST",
        f"/api/chats/{created['id']}/project-context",
        json={"projectId": seeded["project_id"]},
    )
    assert project_code == 200
    assert [
        (link["entityType"], link["entityId"]) for link in updated["contextLinks"]
    ] == [("project", seeded["project_id"])]
    assert updated["contextLinks"][0]["entity"]["label"] == "Context project"

    clear_code, cleared = await _request(
        application,
        "POST",
        f"/api/chats/{created['id']}/project-context",
        json={"projectId": None},
    )
    assert clear_code == 200
    assert cleared["contextLinks"] == []
