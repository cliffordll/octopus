from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import Agent, Base, Issue, Organization
from server.app import create_app
from server.services.documents import DocumentService
from server.services.heartbeat import HeartbeatService


@pytest.fixture
async def app(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[tuple[FastAPI, async_sessionmaker]]:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    monkeypatch.setenv("OCTOPUS_STORAGE_DIR", str(tmp_path / "storage"))
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


async def _seed_issue(factory: async_sessionmaker) -> tuple[str, str]:
    org_id = str(uuid.uuid4())
    issue_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"docs-{org_id[:8]}",
                name="Documents",
                issue_prefix="DOC",
            )
        )
        session.add(
            Issue(
                id=issue_id,
                org_id=org_id,
                project_id=str(uuid.uuid4()),
                title="Document issue",
                status="todo",
                priority="medium",
            )
        )
        await session.commit()
    return org_id, issue_id


async def test_issue_documents_are_versioned_and_listed_on_detail(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    _, issue_id = await _seed_issue(factory)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.put(
            f"/api/issues/{issue_id}/documents/Plan",
            json={
                "title": "Plan",
                "format": "markdown",
                "body": "# Plan\n\nFirst draft.",
                "changeSummary": "initial",
            },
        )
        assert created.status_code == 201
        document = created.json()
        assert document["key"] == "plan"
        assert document["latestRevisionNumber"] == 1
        assert document["body"] == "# Plan\n\nFirst draft."

        updated = await client.put(
            f"/api/issues/{issue_id}/documents/plan",
            json={
                "title": "Plan",
                "format": "markdown",
                "body": "# Plan\n\nSecond draft.",
                "baseRevisionId": document["latestRevisionId"],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["latestRevisionNumber"] == 2

        listed = await client.get(f"/api/issues/{issue_id}/documents")
        fetched = await client.get(f"/api/issues/{issue_id}/documents/plan")
        revisions = await client.get(f"/api/issues/{issue_id}/documents/plan/revisions")
        detail = await client.get(f"/api/issues/{issue_id}")

    assert listed.status_code == 200
    assert [item["key"] for item in listed.json()] == ["plan"]
    assert "body" not in listed.json()[0]
    assert fetched.status_code == 200
    assert fetched.json()["body"] == "# Plan\n\nSecond draft."
    assert revisions.status_code == 200
    assert [item["revisionNumber"] for item in revisions.json()] == [2, 1]
    assert detail.status_code == 200
    assert detail.json()["documentSummaries"][0]["key"] == "plan"


async def test_issue_work_products_have_independent_crud_routes(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    _, issue_id = await _seed_issue(factory)

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post(
            f"/api/issues/{issue_id}/work-products",
            json={
                "type": "artifact",
                "provider": "octopus",
                "title": "Report",
                "summary": "first",
                "isPrimary": True,
            },
        )
        assert created.status_code == 201
        product = created.json()
        assert product["issueId"] == issue_id
        assert product["status"] == "active"
        assert product["isPrimary"] is True

        patched = await client.patch(
            f"/api/work-products/{product['id']}",
            json={"status": "ready_for_review", "summary": "ready"},
        )
        listed = await client.get(f"/api/issues/{issue_id}/work-products")
        removed = await client.delete(f"/api/work-products/{product['id']}")
        listed_after_delete = await client.get(f"/api/issues/{issue_id}/work-products")

    assert patched.status_code == 200
    assert patched.json()["status"] == "ready_for_review"
    assert patched.json()["summary"] == "ready"
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == product["id"]
    assert removed.status_code == 200
    assert removed.json()["id"] == product["id"]
    assert listed_after_delete.status_code == 200
    assert listed_after_delete.json() == []


async def test_issue_documents_are_injected_into_heartbeat_context() -> None:
    engine: AsyncEngine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = create_session_factory(engine)
    try:
        async with factory() as session:
            org_id = str(uuid.uuid4())
            agent_id = str(uuid.uuid4())
            issue_id = str(uuid.uuid4())
            org = Organization(
                id=org_id,
                url_key="issue-doc-context",
                name="Issue Document Context",
                issue_prefix="IDC",
            )
            agent = Agent(
                id=agent_id,
                org_id=org_id,
                name="Document-aware Agent",
                status="idle",
            )
            issue = Issue(
                id=issue_id,
                org_id=org_id,
                title="Use issue docs",
                status="todo",
                priority="medium",
                assignee_agent_id=agent_id,
            )
            session.add_all([org, agent, issue])
            await session.flush()
            documents = DocumentService(session)
            await documents.upsert_issue_document(
                org_id=org_id,
                issue_id=issue_id,
                key="plan",
                payload={
                    "title": "Execution Plan",
                    "format": "markdown",
                    "body": "# Plan\n\nUse the documented requirement.",
                },
                actor_type="user",
                actor_id="dev",
            )
            await documents.upsert_issue_document(
                org_id=org_id,
                issue_id=issue_id,
                key="design",
                payload={
                    "title": "Design Notes",
                    "format": "markdown",
                    "body": "# Design\n\nReference only.",
                },
                actor_type="user",
                actor_id="dev",
            )
            run = await HeartbeatService(session).wakeup(
                agent_id,
                {
                    "source": "assignment",
                    "triggerDetail": "system",
                    "reason": "issue_execute",
                    "payload": {"issueId": issue_id, "mutation": "execute"},
                },
                actor_type="user",
                actor_id="dev",
                execute_immediately=False,
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert run is not None
    context = run["contextSnapshot"]
    assert context is not None
    assert context["planDocument"]["key"] == "plan"
    assert [item["key"] for item in context["documentSummaries"]] == [
        "design",
        "plan",
    ]
    assert "## Issue Documents" in context["issueDocumentsPrompt"]
    assert "Use the documented requirement." in context["issueDocumentsPrompt"]
    assert (
        f"control-plane issue documents get {issue_id} design --json"
        in context["issueDocumentsPrompt"]
    )
