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


async def test_work_product_capture_is_idempotent_on_external_id(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    """A re-scan (backfill after a transient failure such as ENOSPC) must not
    duplicate a work product already registered for the issue."""
    _, factory = app
    org_id, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    product = {
        "title": "report.md",
        "type": "document",
        "provider": "rudder",
        "externalId": "organization_artifacts_scan:org:report.md",
        "content": b"hello world",
        "contentType": "text/markdown",
        "filename": "report.md",
    }
    snapshot = {"issueId": issue_id}

    async with factory() as session:
        first = await WorkspaceService(session).persist_run_work_products(
            run_id="run-1", context_snapshot=snapshot, products=[dict(product)]
        )
        await session.commit()
    async with factory() as session:
        second = await WorkspaceService(session).persist_run_work_products(
            run_id="run-2", context_snapshot=snapshot, products=[dict(product)]
        )
        await session.commit()
    async with factory() as session:
        listed = await WorkspaceService(session).list_work_products_for_issue(issue_id)

    assert len(first) == 1
    assert len(second) == 0  # deduped on externalId
    assert len(listed) == 1


async def test_work_product_archive_reuses_asset_for_identical_content(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    """Byte-identical captures must reuse one asset, not mint a new asset id each
    time (avoids the 'same product, different assetId' duplication + storage bloat)."""
    _, factory = app
    _, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    def _product(external_id: str) -> dict:
        return {
            "title": external_id,
            "type": "document",
            "provider": "rudder",
            "externalId": external_id,
            "content": b"identical deliverable bytes",
            "contentType": "text/markdown",
            "filename": "deliverable.md",
        }

    async with factory() as session:
        rows = await WorkspaceService(session).persist_run_work_products(
            run_id="run-1",
            context_snapshot={"issueId": issue_id},
            products=[_product("scanA:foo"), _product("scanB:foo")],
        )
        await session.commit()

    assert len(rows) == 2  # distinct external ids -> two work products
    asset_ids = {row.get("assetId") for row in rows}
    urls = {row["url"] for row in rows}
    assert len(asset_ids) == 1  # ...but one shared asset for identical content
    assert len(urls) == 1


async def test_generated_work_product_primary_prefers_run_worktree(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    """Primary must be this run's own (newest worktree) deliverable, not the
    oldest file lingering in the shared org artifacts dir."""
    import os

    _, factory = app
    _, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    worktree = tmp_path / "wt"
    worktree.mkdir()
    artifacts = tmp_path / "art"
    artifacts.mkdir()
    shared_old = artifacts / "old_shared_from_another_task.md"
    shared_old.write_text("stale shared file")
    deliverable = worktree / "this_run_deliverable.md"
    deliverable.write_text("the real output of this run")
    os.utime(shared_old, (1_000_000, 1_000_000))
    os.utime(deliverable, (2_000_000, 2_000_000))

    snapshot = {
        "issueId": issue_id,
        "workspace": {
            "rudderWorkspace": {
                "id": "ws-1",
                "cwd": str(worktree),
                "orgArtifactsDir": str(artifacts),
            }
        },
    }

    async with factory() as session:
        rows = await WorkspaceService(session).persist_generated_workspace_files(
            run_id="run-1", context_snapshot=snapshot, since=None
        )
        await session.commit()

    primary = [row for row in rows if row["isPrimary"]]
    assert len(primary) == 1
    assert "this_run_deliverable.md" in primary[0]["title"]


async def test_generated_work_product_captures_binary_document(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    """A generated .docx deliverable must be captured as a work product, not
    silently skipped by the extension whitelist (then only seen as an attachment)."""
    _, factory = app
    _, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / "静夜思.docx").write_bytes(b"PK\x03\x04 fake docx bytes")

    snapshot = {
        "issueId": issue_id,
        "workspace": {"rudderWorkspace": {"id": "ws-1", "cwd": str(worktree)}},
    }

    async with factory() as session:
        rows = await WorkspaceService(session).persist_generated_workspace_files(
            run_id="run-1", context_snapshot=snapshot, since=None
        )
        await session.commit()

    titles = [row["title"] for row in rows]
    assert any(title.endswith(".docx") for title in titles)


async def test_shared_workspace_generated_scan_ignores_unscoped_cwd_files(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    _, factory = app
    _, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    shared_cwd = tmp_path / "shared"
    shared_cwd.mkdir()
    (shared_cwd / "other-task.md").write_text("belongs to another task")

    snapshot = {
        "issueId": issue_id,
        "workspace": {
            "rudderWorkspace": {
                "id": "ws-shared",
                "mode": "shared_workspace",
                "cwd": str(shared_cwd),
            }
        },
    }

    async with factory() as session:
        rows = await WorkspaceService(session).persist_generated_workspace_files(
            run_id="run-1", context_snapshot=snapshot, since=None
        )
        await session.commit()

    assert rows == []


async def test_shared_workspace_generated_scan_captures_root_artifacts_from_run(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    _, factory = app
    _, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    shared_cwd = tmp_path / "shared"
    artifacts = shared_cwd / "artifacts"
    artifacts.mkdir(parents=True)
    (artifacts / "report.md").write_text("belongs to this run")
    other_issue_artifacts = artifacts / "issues" / "other-issue"
    other_issue_artifacts.mkdir(parents=True)
    (other_issue_artifacts / "other.md").write_text("belongs to another issue")

    snapshot = {
        "issueId": issue_id,
        "workspace": {
            "rudderWorkspace": {
                "id": "ws-shared",
                "mode": "shared_workspace",
                "cwd": str(shared_cwd),
            }
        },
    }

    async with factory() as session:
        rows = await WorkspaceService(session).persist_generated_workspace_files(
            run_id="run-1", context_snapshot=snapshot, since=None
        )
        await session.commit()

    assert len(rows) == 1
    metadata = rows[0]["metadata"]
    assert metadata is not None
    assert metadata["source"] == "shared_artifacts_scan"
    assert metadata["workspacePath"] == "report.md"


async def test_shared_workspace_generated_scan_captures_issue_scoped_files(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    _, factory = app
    _, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    shared_cwd = tmp_path / "shared"
    issue_artifacts = shared_cwd / "artifacts" / "issues" / issue_id
    issue_artifacts.mkdir(parents=True)
    (shared_cwd / "other-task.md").write_text("belongs to another task")
    (issue_artifacts / "deliverable.md").write_text("belongs to this issue")

    snapshot = {
        "issueId": issue_id,
        "workspace": {
            "rudderWorkspace": {
                "id": "ws-shared",
                "mode": "shared_workspace",
                "cwd": str(shared_cwd),
            }
        },
    }

    async with factory() as session:
        rows = await WorkspaceService(session).persist_generated_workspace_files(
            run_id="run-1", context_snapshot=snapshot, since=None
        )
        await session.commit()

    assert len(rows) == 1
    md = rows[0]["metadata"]
    assert md
    assert md["workspacePath"] == "deliverable.md"
    assert md["source"] == "issue_artifacts_scan"


async def test_generated_scan_ignores_organization_artifacts_root(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    _, factory = app
    _, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    worktree = tmp_path / "wt"
    worktree.mkdir()
    artifacts = tmp_path / "org-artifacts"
    artifacts.mkdir()
    (artifacts / "other-task.md").write_text("belongs to another task")

    snapshot = {
        "issueId": issue_id,
        "workspace": {
            "rudderWorkspace": {
                "id": "ws-1",
                "mode": "isolated_workspace",
                "cwd": str(worktree),
                "orgArtifactsDir": str(artifacts),
            }
        },
    }

    async with factory() as session:
        rows = await WorkspaceService(session).persist_generated_workspace_files(
            run_id="run-1", context_snapshot=snapshot, since=None
        )
        await session.commit()

    assert rows == []


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
