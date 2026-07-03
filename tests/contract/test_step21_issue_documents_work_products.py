from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.schema import (
    ActivityLog,
    Agent,
    Base,
    Issue,
    IssueWorkProduct,
    Organization,
)
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
        "provider": "octopus",
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
            "provider": "octopus",
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


async def test_work_product_listing_hides_historical_duplicate_content_path_rows(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    _, factory = app
    org_id, issue_id = await _seed_issue(factory)
    metadata = {
        "assetId": "asset-1",
        "sha256": "abc123",
        "workspacePath": "artifacts/issues/issue-1/final.md",
        "workspaceBrowserPath": "artifacts/issues/issue-1/final.md",
    }
    async with factory() as session:
        session.add_all(
            [
                IssueWorkProduct(
                    org_id=org_id,
                    issue_id=issue_id,
                    type="document",
                    provider="octopus",
                    external_id="scan:final.md",
                    title="final.md",
                    status="active",
                    review_state="none",
                    is_primary=True,
                    health_status="unknown",
                    metadata_json=metadata,
                    created_by_run_id="run-1",
                ),
                IssueWorkProduct(
                    org_id=org_id,
                    issue_id=issue_id,
                    type="document",
                    provider="octopus",
                    external_id="opencode:final.md",
                    title="artifacts/issues/issue-1/final.md",
                    status="active",
                    review_state="none",
                    is_primary=False,
                    health_status="unknown",
                    metadata_json=metadata,
                    created_by_run_id="run-1",
                ),
            ]
        )
        await session.commit()
    async with factory() as session:
        from server.services.workspaces import WorkspaceService

        listed = await WorkspaceService(session).list_work_products_for_issue(issue_id)

    assert len(listed) == 1
    assert listed[0]["title"] == "final.md"
    assert listed[0]["isPrimary"] is True


async def test_work_product_capture_merges_same_archived_path_from_runtime_and_scan(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    _, factory = app
    _, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    body = b"# Final report\n"
    runtime_product = {
        "title": "artifacts/issues/issue-1/final.md",
        "type": "document",
        "provider": "octopus",
        "externalId": "opencode_write:run-1:artifacts/issues/issue-1/final.md",
        "isPrimary": False,
        "summary": "File written by OpenCode during this run.",
        "content": body,
        "contentType": "text/markdown",
        "filename": "final.md",
        "metadata": {
            "source": "opencode_write_event",
            "workspacePath": "artifacts/issues/issue-1/final.md",
        },
    }
    scanned_product = {
        "title": "final.md",
        "type": "document",
        "provider": "octopus",
        "externalId": "issue_artifacts_scan:organization_workspace:org:final.md",
        "isPrimary": True,
        "summary": "Generated file captured from managed workspace storage.",
        "content": body,
        "contentType": "text/markdown",
        "filename": "final.md",
        "metadata": {
            "source": "issue_artifacts_scan",
            "workspacePath": "final.md",
            "workspaceBrowserPath": "artifacts/issues/issue-1/final.md",
        },
    }

    async with factory() as session:
        first = await WorkspaceService(session).persist_run_work_products(
            run_id="run-1",
            context_snapshot={"issueId": issue_id},
            products=[runtime_product, scanned_product],
        )
        await session.commit()
    async with factory() as session:
        listed = await WorkspaceService(session).list_work_products_for_issue(issue_id)

    assert len(first) == 2
    assert len(listed) == 1
    assert listed[0]["isPrimary"] is True
    metadata = listed[0]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["sources"] == [
        "issue_artifacts_scan",
        "opencode_write_event",
    ]
    assert metadata["workspaceBrowserPath"] == "artifacts/issues/issue-1/final.md"


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
            "octopusWorkspace": {
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
        "workspace": {"octopusWorkspace": {"id": "ws-1", "cwd": str(worktree)}},
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
            "octopusWorkspace": {
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


async def test_shared_workspace_generated_scan_ignores_root_artifacts(
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
            "octopusWorkspace": {
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


async def test_shared_workspace_generated_scan_captures_declared_recent_shared_files(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    _, factory = app
    _, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    shared_cwd = tmp_path / "shared"
    shared_cwd.mkdir()
    report = shared_cwd / "reports" / "deliverable.md"
    report.parent.mkdir(parents=True)
    since = datetime.now(UTC)
    report.write_text("belongs to this run")

    snapshot = {
        "issueId": issue_id,
        "workspace": {
            "octopusWorkspace": {
                "id": "ws-shared",
                "mode": "shared_workspace",
                "cwd": str(shared_cwd),
            }
        },
    }

    async with factory() as session:
        issue = await session.get(Issue, issue_id)
        assert issue is not None
        issue.description = "Write the deliverable to reports/deliverable.md"
        await session.commit()

    async with factory() as session:
        rows = await WorkspaceService(session).persist_generated_workspace_files(
            run_id="run-1", context_snapshot=snapshot, since=since
        )
        await session.commit()

    assert len(rows) == 1
    md = rows[0]["metadata"]
    assert md
    assert rows[0]["title"] == "reports/deliverable.md"
    assert md["workspacePath"] == "reports/deliverable.md"
    assert md["source"] == "shared_workspace_scan"
    assert md["executionWorkspaceId"] == "ws-shared"


async def test_shared_workspace_generated_scan_captures_unicode_path_from_closeout(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    _, factory = app
    org_id, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    shared_cwd = tmp_path / "shared"
    report = shared_cwd / "reports" / "中国佛教四大名山.md"
    report.parent.mkdir(parents=True)
    since = datetime.now(UTC)
    report.write_text("# 中国佛教四大名山", encoding="utf-8")

    async with factory() as session:
        session.add(
            ActivityLog(
                org_id=org_id,
                actor_type="agent",
                actor_id="agent-1",
                action="issue.updated",
                entity_type="issue",
                entity_id=issue_id,
                run_id="run-1",
                details={
                    "status": "done",
                    "comment": "汇总报告位于 `reports/中国佛教四大名山.md`。",
                },
            )
        )
        await session.commit()

    snapshot = {
        "issueId": issue_id,
        "workspace": {
            "octopusWorkspace": {
                "id": "ws-shared",
                "mode": "shared_workspace",
                "cwd": str(shared_cwd),
            }
        },
    }

    async with factory() as session:
        rows = await WorkspaceService(session).persist_generated_workspace_files(
            run_id="run-1", context_snapshot=snapshot, since=since
        )
        await session.commit()

    assert [row["title"] for row in rows] == ["reports/中国佛教四大名山.md"]
    assert rows[0]["isPrimary"] is True


async def test_shared_workspace_generated_scan_ignores_undeclared_recent_shared_files(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    _, factory = app
    _, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    shared_cwd = tmp_path / "shared"
    shared_cwd.mkdir()
    report = shared_cwd / "reports" / "other-child.md"
    report.parent.mkdir(parents=True)
    since = datetime.now(UTC)
    report.write_text("belongs to another child task")

    snapshot = {
        "issueId": issue_id,
        "workspace": {
            "octopusWorkspace": {
                "id": "ws-shared",
                "mode": "shared_workspace",
                "cwd": str(shared_cwd),
            }
        },
    }

    async with factory() as session:
        rows = await WorkspaceService(session).persist_generated_workspace_files(
            run_id="run-1", context_snapshot=snapshot, since=since
        )
        await session.commit()

    assert rows == []


async def test_shared_workspace_generated_scan_uses_issue_requested_report_path(
    app: tuple[FastAPI, async_sessionmaker],
    tmp_path: Path,
) -> None:
    _, factory = app
    org_id, issue_id = await _seed_issue(factory)
    from server.services.workspaces import WorkspaceService

    shared_cwd = tmp_path / "shared"
    reports = shared_cwd / "reports"
    reports.mkdir(parents=True)
    since = datetime.now(UTC)
    (reports / "hongzehu.md").write_text("belongs to hongzehu")
    (reports / "chaohu.md").write_text("belongs to chaohu")

    async with factory() as session:
        issue = await session.get(Issue, issue_id)
        assert issue is not None
        issue.title = "洪泽湖介绍"
        issue.description = (
            "撰写洪泽湖介绍。完成后将文档保存到工作区的 reports/ "
            "目录下，文件名为 hongzehu.md"
        )
        await session.commit()

    snapshot = {
        "issueId": issue_id,
        "workspace": {
            "octopusWorkspace": {
                "id": "ws-shared",
                "mode": "shared_workspace",
                "cwd": str(shared_cwd),
            }
        },
    }

    async with factory() as session:
        rows = await WorkspaceService(session).persist_generated_workspace_files(
            run_id="run-1", context_snapshot=snapshot, since=since
        )
        await session.commit()

    assert [row["title"] for row in rows] == ["reports/hongzehu.md"]
    assert rows[0]["isPrimary"] is True


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
            "octopusWorkspace": {
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
            "octopusWorkspace": {
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


async def test_heartbeat_context_lists_blocked_child_issues(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"blocked-child-{org_id[:8]}",
                name="Blocked Child",
                issue_prefix="BC",
            )
        )
        session.add_all(
            [
                Issue(
                    id=parent_id,
                    org_id=org_id,
                    title="五湖报告",
                    status="in_progress",
                    priority="medium",
                ),
                Issue(
                    id=child_id,
                    org_id=org_id,
                    parent_id=parent_id,
                    title="太湖介绍",
                    status="blocked",
                    priority="medium",
                ),
            ]
        )
        session.add(
            ActivityLog(
                org_id=org_id,
                actor_type="agent",
                actor_id="child-agent",
                action="issue.updated",
                entity_type="issue",
                entity_id=child_id,
                details={"status": "blocked", "reason": "run_failed"},
            )
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        context = await client.get(f"/api/issues/{parent_id}/heartbeat-context")

    assert context.status_code == 200
    body = context.json()
    assert body["blockedChildIssues"][0]["id"] == child_id
    assert body["blockedChildIssues"][0]["title"] == "太湖介绍"
    assert body["blockedChildIssues"][0]["status"] == "blocked"
    assert body["blockedChildIssues"][0]["workProductCount"] == 0


async def test_parent_issue_lists_child_primary_work_products(
    app: tuple[FastAPI, async_sessionmaker],
) -> None:
    application, factory = app
    org_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    child_id = str(uuid.uuid4())
    async with factory() as session:
        session.add(
            Organization(
                id=org_id,
                url_key=f"parent-products-{org_id[:8]}",
                name="Parent Products",
                issue_prefix="PP",
            )
        )
        session.add_all(
            [
                Issue(
                    id=parent_id,
                    org_id=org_id,
                    title="四大美女报告",
                    status="in_progress",
                    priority="medium",
                ),
                Issue(
                    id=child_id,
                    org_id=org_id,
                    parent_id=parent_id,
                    title="西施介绍",
                    status="done",
                    priority="medium",
                ),
            ]
        )
        session.add(
            ActivityLog(
                org_id=org_id,
                actor_type="agent",
                actor_id="child-agent",
                action="issue.updated",
                entity_type="issue",
                entity_id=child_id,
                details={"status": "done", "comment": "完成西施介绍"},
            )
        )
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=application), base_url="http://test"
    ) as client:
        created = await client.post(
            f"/api/issues/{child_id}/work-products",
            json={
                "type": "document",
                "provider": "octopus",
                "title": "西施.md",
                "summary": "西施介绍",
                "isPrimary": True,
            },
        )
        listed = await client.get(f"/api/issues/{parent_id}/work-products")
        detail = await client.get(f"/api/issues/{parent_id}")
        context = await client.get(f"/api/issues/{parent_id}/heartbeat-context")
        children = await client.get(
            f"/api/issues/{parent_id}/children?includeWorkProducts=true"
        )

    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json() == []
    assert detail.status_code == 200
    assert detail.json()["workProducts"] == []
    assert context.status_code == 200
    heartbeat_context = context.json()
    assert (
        heartbeat_context["childPrimaryWorkProducts"][0]["id"] == created.json()["id"]
    )
    assert (
        heartbeat_context["childPrimaryWorkProducts"][0]["sourceIssueTitle"]
        == "西施介绍"
    )
    assert "Child Primary Work Products" in heartbeat_context["childWorkProductsPrompt"]
    assert "西施.md" in heartbeat_context["childWorkProductsPrompt"]
    assert children.status_code == 200
    child_outputs = children.json()
    assert child_outputs["parent"]["id"] == parent_id
    assert child_outputs["totalChildCount"] == 1
    assert child_outputs["activeChildCount"] == 0
    assert child_outputs["settledChildCount"] == 1
    assert child_outputs["children"][0]["id"] == child_id
    assert child_outputs["children"][0]["lastCloseout"]["action"] == "issue.updated"
    assert child_outputs["children"][0]["workProducts"][0]["title"] == "西施.md"


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
        f"octopus issue documents get {issue_id} design --json"
        in context["issueDocumentsPrompt"]
    )
