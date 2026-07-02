from __future__ import annotations

import importlib
import importlib.util
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Any
import uuid

import pytest
from fastapi import FastAPI, Request
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Table, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
from starlette.responses import Response

from packages.database.clients import create_database_engine, create_session_factory
from packages.database.migrations.runner import upgrade_to_head
from packages.database.schema import Base, Organization, ProjectWorkspace
from server.app import create_app


def test_project_contract_modules_are_defined() -> None:
    modules = (
        "packages.shared.api_paths.projects",
        "packages.shared.constants.project",
        "packages.shared.types.project",
        "packages.shared.validators.project",
    )
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    paths = importlib.import_module("packages.shared.api_paths.projects")
    constants = importlib.import_module("packages.shared.constants.project")
    validators = importlib.import_module("packages.shared.validators.project")
    assert paths.ORG_PROJECT_LIST_PATH == "/api/orgs/{orgId}/projects"
    assert paths.PROJECT_DETAIL_PATH == "/api/projects/{id}"
    assert paths.PROJECT_RESOURCE_LIST_PATH == "/api/projects/{id}/resources"
    assert constants.PROJECT_STATUSES == (
        "backlog",
        "planned",
        "in_progress",
        "completed",
        "cancelled",
    )
    payload = validators.validate_create_project({"name": "Control Plane"})
    assert payload["name"] == "Control Plane"
    with pytest.raises(ValueError, match="status"):
        validators.validate_create_project({"name": "Invalid", "status": "unknown"})


def test_project_tables_match_upstream_step10_scope() -> None:
    table_names = {table.name for table in Base.metadata.sorted_tables}
    assert "projects" in table_names
    assert "organization_resources" in table_names
    assert "project_resource_attachments" in table_names

    schema = importlib.import_module("packages.database.schema")
    project = schema.Project
    resources = schema.OrganizationResource
    attachments = schema.ProjectResourceAttachment
    assert project.__tablename__ == "projects"
    assert resources.__tablename__ == "organization_resources"
    assert attachments.__tablename__ == "project_resource_attachments"
    assert {idx.name for idx in project.__table__.indexes} == {"projects_company_idx"}
    assert "project_resource_attachments_project_resource_idx" in {
        idx.name for idx in attachments.__table__.indexes
    }
    assert isinstance(project.__table__, Table)


async def test_upgrade_to_head_creates_project_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "step10-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")

    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master "
                    "where type='table' and name in "
                    "('projects', 'organization_resources', "
                    "'project_resource_attachments')"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()

    assert names == {
        "projects",
        "organization_resources",
        "project_resource_attachments",
    }


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
) -> async_sessionmaker:
    return create_session_factory(engine)


@pytest.fixture
def app(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker,
) -> FastAPI:
    monkeypatch.setenv("OCTOPUS_LOCAL_TRUSTED", "1")
    application = create_app()
    application.state.session_factory = session_factory

    @application.middleware("http")
    async def inject_agent_actor(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        actor_id = request.headers.get("x-test-agent-id")
        if actor_id:
            request.state.actor = {
                "type": "agent",
                "id": actor_id,
                "agentId": actor_id,
                "orgId": request.headers["x-test-org-id"],
            }
        return await call_next(request)

    return application


async def _request(
    app: FastAPI,
    method: str,
    path: str,
    *,
    json: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.request(method, path, json=json)
    return response.status_code, response.json()


async def test_project_routes_create_list_update_and_delete(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        org = Organization(
            url_key="step10-contract", name="Step 10", issue_prefix="S10"
        )
        session.add(org)
        await session.commit()
        org_id = org.id

    create_code, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/projects",
        json={"name": "Control Plane", "status": "planned"},
    )
    assert create_code == 201
    assert created["orgId"] == org_id
    assert created["urlKey"] == "control-plane"
    assert created["resources"] == []
    expected_workspace_root = f"organizations/{org_id}/workspaces"
    assert created["codebase"]["scope"] == "none"
    assert created["codebase"]["localFolder"] is None
    assert created["codebase"]["managedFolder"] == expected_workspace_root
    assert created["codebase"]["effectiveLocalFolder"] == expected_workspace_root

    list_code, listed = await _request(app, "GET", f"/api/orgs/{org_id}/projects")
    assert list_code == 200
    assert [item["id"] for item in listed] == [created["id"]]

    patch_code, updated = await _request(
        app,
        "PATCH",
        f"/api/projects/{created['id']}",
        json={"status": "in_progress"},
    )
    assert patch_code == 200
    assert updated["status"] == "in_progress"

    delete_code, deleted = await _request(
        app, "DELETE", f"/api/projects/{created['id']}"
    )
    assert delete_code == 200
    assert deleted["id"] == created["id"]


async def test_project_workspace_routes_manage_primary_workspace(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        org = Organization(
            url_key="step10-workspaces", name="Step 10 Workspaces", issue_prefix="S10W"
        )
        session.add(org)
        await session.commit()
        org_id = org.id

    rejected_code, rejected = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/projects",
        json={
            "name": "Invalid Project Policy",
            "executionWorkspacePolicy": {
                "enabled": True,
                "defaultMode": "shared_workspace",
            },
        },
    )
    assert rejected_code == 422
    assert "executionWorkspacePolicy" in str(rejected)

    create_code, project = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/projects",
        json={"name": "Workspace Project", "status": "planned"},
    )
    assert create_code == 201
    assert "executionWorkspacePolicy" not in project

    first_code, first = await _request(
        app,
        "POST",
        f"/api/projects/{project['id']}/workspaces",
        json={
            "name": "Local checkout",
            "sourceType": "local_path",
            "cwd": "D:/workspaces/project-a",
            "repoUrl": "https://example.test/project-a.git",
            "repoRef": "main",
            "defaultRef": "main",
            "sharedWorkspaceKey": "project-a-local",
            "executionWorkspacePolicy": {
                "enabled": True,
                "defaultMode": "shared_workspace",
                "workspaceStrategy": {"mode": "shared_workspace"},
            },
        },
    )
    assert first_code == 201
    assert first["projectId"] == project["id"]
    assert first["name"] == "Local checkout"
    assert first["cwd"] == "D:/workspaces/project-a"
    assert first["isPrimary"] is True
    assert first["executionWorkspacePolicy"]["defaultMode"] == "shared_workspace"

    second_code, second = await _request(
        app,
        "POST",
        f"/api/projects/{project['id']}/workspaces",
        json={
            "name": "Secondary checkout",
            "sourceType": "local_path",
            "cwd": "D:/workspaces/project-b",
            "isPrimary": True,
            "executionWorkspacePolicy": {
                "enabled": True,
                "defaultMode": "isolated_workspace",
                "workspaceStrategy": {"type": "git_worktree"},
            },
        },
    )
    assert second_code == 201
    assert second["isPrimary"] is True
    assert second["executionWorkspacePolicy"]["defaultMode"] == "isolated_workspace"

    list_code, workspaces = await _request(
        app, "GET", f"/api/projects/{project['id']}/workspaces"
    )
    assert list_code == 200
    assert [workspace["id"] for workspace in workspaces] == [second["id"], first["id"]]
    assert [workspace["isPrimary"] for workspace in workspaces] == [True, False]

    patch_code, patched = await _request(
        app,
        "PATCH",
        f"/api/projects/{project['id']}/workspaces/{first['id']}",
        json={
            "name": "Primary checkout",
            "isPrimary": True,
            "executionWorkspacePolicy": {
                "enabled": True,
                "defaultMode": "operator_branch",
                "workspaceStrategy": {
                    "type": "git_worktree",
                    "operatorBranch": "release",
                },
            },
        },
    )
    assert patch_code == 200
    assert patched["name"] == "Primary checkout"
    assert patched["isPrimary"] is True
    assert patched["executionWorkspacePolicy"]["defaultMode"] == "operator_branch"

    async with session_factory() as session:
        stored_policy = await session.scalar(
            select(ProjectWorkspace.execution_workspace_policy).where(
                ProjectWorkspace.id == first["id"]
            )
        )
    assert stored_policy == patched["executionWorkspacePolicy"]

    detail_code, detail = await _request(app, "GET", f"/api/projects/{project['id']}")
    assert detail_code == 200
    assert detail["primaryWorkspace"]["id"] == first["id"]
    assert (
        detail["primaryWorkspace"]["executionWorkspacePolicy"]["defaultMode"]
        == "operator_branch"
    )
    assert detail["codebase"]["localFolder"] == "D:/workspaces/project-a"
    assert detail["codebase"]["scope"] == "project"

    rejected_delete_code, rejected_delete = await _request(
        app, "DELETE", f"/api/projects/{project['id']}/workspaces/{first['id']}"
    )
    assert rejected_delete_code == 422
    assert "another project workspace as default" in str(rejected_delete)

    promote_code, promoted = await _request(
        app,
        "PATCH",
        f"/api/projects/{project['id']}/workspaces/{second['id']}",
        json={"isPrimary": True},
    )
    assert promote_code == 200
    assert promoted["isPrimary"] is True

    delete_code, deleted = await _request(
        app, "DELETE", f"/api/projects/{project['id']}/workspaces/{first['id']}"
    )
    assert delete_code == 200
    assert deleted["id"] == first["id"]

    final_code, final_detail = await _request(
        app, "GET", f"/api/projects/{project['id']}"
    )
    assert final_code == 200
    assert final_detail["primaryWorkspace"]["id"] == second["id"]
    assert final_detail["workspaces"][0]["id"] == second["id"]


async def test_project_resource_route_resolves_shortname_with_org_context(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        org = Organization(url_key="shortname", name="Shortname", issue_prefix="SRT")
        session.add(org)
        await session.commit()
        org_id = org.id

    code, created = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/projects",
        json={
            "name": "Control Plane",
            "newResources": [
                {"name": "Reference", "kind": "file", "locator": "docs/ref.md"}
            ],
        },
    )
    assert code == 201

    resource_code, resources = await _request(
        app,
        "GET",
        f"/api/projects/{created['urlKey']}/resources?orgId={org_id}",
    )
    assert resource_code == 200
    assert resources[0]["resource"]["name"] == "Reference"


async def test_agent_cannot_list_projects_from_another_organization(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        org = Organization(url_key="private", name="Private", issue_prefix="PRI")
        session.add(org)
        await session.commit()
        org_id = org.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/orgs/{org_id}/projects",
            headers={
                "x-test-agent-id": "agent-1",
                "x-test-org-id": "another-org",
            },
        )
    assert response.status_code == 403


async def test_agent_cannot_resolve_shortname_in_another_organization(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        org = Organization(url_key="foreign-ref", name="Foreign", issue_prefix="FOR")
        session.add(org)
        await session.commit()
        org_id = org.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/projects/missing?orgId={org_id}",
            headers={
                "x-test-agent-id": "agent-1",
                "x-test-org-id": "another-org",
            },
        )
    assert response.status_code == 403


async def test_invalid_existing_resource_does_not_leave_created_project(
    app: FastAPI,
    session_factory: async_sessionmaker,
) -> None:
    async with session_factory() as session:
        org = Organization(
            url_key="invalid-resource", name="Invalid", issue_prefix="INV"
        )
        session.add(org)
        await session.commit()
        org_id = org.id

    code, _ = await _request(
        app,
        "POST",
        f"/api/orgs/{org_id}/projects",
        json={
            "name": "Must not persist",
            "resourceAttachments": [{"resourceId": str(uuid.uuid4())}],
        },
    )
    assert code == 422

    list_code, projects = await _request(app, "GET", f"/api/orgs/{org_id}/projects")
    assert list_code == 200
    assert projects == []
