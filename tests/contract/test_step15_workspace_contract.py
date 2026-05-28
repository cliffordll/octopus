from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path

from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.database.clients import create_database_engine
from packages.database.clients.session import create_session_factory
from packages.database.migrations.runner import upgrade_to_head
from packages.database.schema import (
    Base,
    Issue,
    IssueWorkProduct,
    Organization,
    WorkspaceRuntimeService,
)
from packages.database.queries.workspaces import list_workspace_operations_for_run
from packages.runtimes.types import RuntimeExecutionResult
import packages.runtimes.registry as runtime_registry
from server.services.agents import AgentService
from server.services.heartbeat import HeartbeatService
from server.services.issues import IssueService
from server.services.projects import ProjectService
from server.services.workspaces import WorkspaceService


def test_workspace_contract_modules_are_defined() -> None:
    modules = (
        "packages.shared.constants.workspace",
        "packages.shared.types.workspace",
        "packages.shared.validators.workspace",
    )
    for module in modules:
        assert importlib.util.find_spec(module) is not None

    constants = importlib.import_module("packages.shared.constants.workspace")
    validators = importlib.import_module("packages.shared.validators.workspace")
    assert constants.EXECUTION_WORKSPACE_STATUSES == (
        "active",
        "idle",
        "in_review",
        "archived",
        "cleanup_failed",
    )
    payload = validators.validate_update_execution_workspace(
        {"status": "idle", "metadata": {"reason": "reuse"}}
    )
    assert payload["status"] == "idle"
    assert payload["metadata"] == {"reason": "reuse"}


def test_workspace_tables_match_upstream_step15_scope() -> None:
    table_names = {table.name for table in Base.metadata.sorted_tables}
    assert {
        "project_workspaces",
        "execution_workspaces",
        "workspace_runtime_services",
        "workspace_operations",
        "issue_work_products",
    }.issubset(table_names)

    schema = importlib.import_module("packages.database.schema")
    assert schema.ProjectWorkspace.__tablename__ == "project_workspaces"
    assert schema.ExecutionWorkspace.__tablename__ == "execution_workspaces"
    assert schema.WorkspaceRuntimeService.__tablename__ == "workspace_runtime_services"
    assert schema.WorkspaceOperation.__tablename__ == "workspace_operations"
    assert schema.IssueWorkProduct.__tablename__ == "issue_work_products"
    assert isinstance(schema.ExecutionWorkspace.__table__, Table)
    assert "execution_workspaces_company_project_status_idx" in {
        idx.name for idx in schema.ExecutionWorkspace.__table__.indexes
    }
    assert "workspace_runtime_services_company_execution_workspace_status_idx" in {
        idx.name for idx in schema.WorkspaceRuntimeService.__table__.indexes
    }
    assert "issue_work_products_company_issue_type_idx" in {
        idx.name for idx in schema.IssueWorkProduct.__table__.indexes
    }


async def test_upgrade_to_head_creates_workspace_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "step15-upgrade.db"
    await upgrade_to_head(f"sqlite+aiosqlite:///{db_path}")

    engine = create_database_engine(f"sqlite+aiosqlite:///{db_path}")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "select name from sqlite_master "
                    "where type='table' and name in "
                    "('project_workspaces', 'execution_workspaces', "
                    "'workspace_runtime_services', 'workspace_operations', "
                    "'issue_work_products')"
                )
            )
            names = {row[0] for row in result}
    finally:
        await engine.dispose()

    assert names == {
        "project_workspaces",
        "execution_workspaces",
        "workspace_runtime_services",
        "workspace_operations",
        "issue_work_products",
    }


async def test_project_detail_includes_workspace_aggregation() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-workspaces",
                name="Step 15",
                issue_prefix="WKS",
            )
            session.add(org)
            await session.flush()
            service = ProjectService(session)
            project = await service.create_project(
                org.id,
                {"name": "Workspace Project"},
                actor_type="user",
                actor_id="dev",
            )
            workspace = await service.create_workspace(
                project["id"],
                {
                    "name": "Main",
                    "cwd": "D:/work/main",
                    "repoUrl": "https://example.test/org/repo.git",
                    "repoRef": "main",
                },
                actor_type="user",
                actor_id="dev",
            )
            await session.commit()

            detail = await service.get_by_id(project["id"])
    finally:
        await engine.dispose()

    assert workspace is not None
    assert detail is not None
    assert detail["workspaces"][0]["id"] == workspace["id"]
    assert detail["primaryWorkspace"] is not None
    assert detail["primaryWorkspace"]["id"] == workspace["id"]
    assert detail["codebase"]["configured"] is True
    assert detail["codebase"]["workspaceId"] == workspace["id"]


async def test_execution_workspace_resolution_binds_issue_to_workspace() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-resolution",
                name="Step 15 Resolution",
                issue_prefix="RES",
            )
            session.add(org)
            await session.flush()
            projects = ProjectService(session)
            project = await projects.create_project(
                org.id,
                {
                    "name": "Workspace Resolution",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            project_workspace = await projects.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": "D:/work/primary"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Implement workspace resolution",
                project_workspace_id=project_workspace["id"]
                if project_workspace
                else None,
            )
            session.add(issue)
            await session.flush()

            workspace = await WorkspaceService(session).resolve_for_issue(issue)
            await session.commit()
    finally:
        await engine.dispose()

    assert workspace is not None
    assert workspace["projectId"] == project["id"]
    assert workspace["projectWorkspaceId"] == project_workspace["id"]
    assert workspace["sourceIssueId"] == issue.id
    assert workspace["mode"] == "isolated_workspace"
    assert workspace["strategyType"] == "git_worktree"


async def test_run_preflight_injects_workspace_context_into_runtime_env() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-preflight",
                name="Step 15 Preflight",
                issue_prefix="PFL",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            agent_service = AgentService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Workspace Runtime",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": "D:/work/runtime-primary"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Run with workspace context",
            )
            session.add(issue)
            await session.flush()
            agent = await agent_service.create_agent(
                org.id,
                {
                    "name": "Workspace Env Agent",
                    "agentRuntimeType": "process",
                    "agentRuntimeConfig": {
                        "command": sys.executable,
                        "args": [
                            "-c",
                            "import os; print(os.environ['RUDDER_WORKSPACE_ID'])",
                        ],
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            run = await HeartbeatService(session).wakeup(
                agent["id"],
                {"payload": {"issueId": issue.id}},
                actor_type="user",
                actor_id="dev",
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert run is not None
    assert run["status"] == "succeeded"
    assert run["contextSnapshot"] is not None
    workspace = run["contextSnapshot"]["workspace"]["rudderWorkspace"]
    assert run["contextSnapshot"]["executionWorkspaceId"] == workspace["id"]
    assert workspace["id"] in (run["resultJson"] or {})["stdout"]


async def test_adapter_runtime_services_are_persisted_and_released(
    monkeypatch,
) -> None:
    class ReportingAdapter:
        type = "process"

        async def execute(self, context):
            return RuntimeExecutionResult(
                exit_code=0,
                result_json={"ok": True},
                runtime_services=[
                    {
                        "id": "svc-report-1",
                        "serviceName": "preview",
                        "status": "running",
                        "lifecycle": "ephemeral",
                        "scopeType": "run",
                        "url": "http://127.0.0.1:8001",
                    }
                ],
                work_products=[
                    {
                        "type": "preview_url",
                        "provider": "custom",
                        "title": "Preview",
                        "url": "http://127.0.0.1:8001",
                        "status": "active",
                        "isPrimary": True,
                    }
                ],
            )

        async def test_environment(self, config):
            raise NotImplementedError

        async def list_models(self):
            return []

        async def list_skills(self, config):
            return {}

        async def sync_skills(self, config, desired_skills):
            return {}

        async def get_metadata(self):
            return {}

        async def get_quota_windows(self):
            return {}

    monkeypatch.setattr(
        runtime_registry,
        "get_runtime_adapter",
        lambda runtime_type: ReportingAdapter(),
    )
    import server.services.heartbeat as heartbeat_module

    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda runtime_type: ReportingAdapter(),
    )
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-services",
                name="Step 15 Services",
                issue_prefix="SVC",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            agent_service = AgentService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Runtime Service Project",
                    "executionWorkspacePolicy": {"enabled": True},
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": "D:/work/service-primary"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Run with runtime service",
            )
            session.add(issue)
            await session.flush()
            agent = await agent_service.create_agent(
                org.id,
                {
                    "name": "Runtime Service Agent",
                    "agentRuntimeType": "process",
                    "agentRuntimeConfig": {"command": sys.executable},
                },
                actor_type="user",
                actor_id="dev",
            )
            run = await HeartbeatService(session).wakeup(
                agent["id"],
                {"payload": {"issueId": issue.id}},
                actor_type="user",
                actor_id="dev",
            )
            rows = (
                await session.execute(text("select id from workspace_runtime_services"))
            ).all()
            service = await session.get(WorkspaceRuntimeService, "svc-report-1")
            product = (
                await session.execute(
                    text("select id from issue_work_products limit 1")
                )
            ).first()
            product_row = (
                await session.get(IssueWorkProduct, product[0])
                if product is not None
                else None
            )
            detail = await IssueService(session).get_by_id(issue.id)
            await session.commit()
    finally:
        await engine.dispose()

    assert run is not None
    assert run["status"] == "succeeded"
    assert rows == [("svc-report-1",)]
    assert service is not None
    assert service.service_name == "preview"
    assert service.execution_workspace_id == run["contextSnapshot"][
        "executionWorkspaceId"
    ]
    assert service.status == "stopped"
    assert service.health_status == "unknown"
    assert (run["resultJson"] or {})["runtimeServices"][0]["id"] == "svc-report-1"
    assert detail is not None
    assert product_row is not None
    assert product_row.issue_id == detail["id"]
    assert product_row.execution_workspace_id == run["contextSnapshot"][
        "executionWorkspaceId"
    ]
    assert product_row.created_by_run_id == run["id"]
    assert (run["resultJson"] or {})["workProducts"][0]["id"] == product_row.id
    assert detail["workProducts"][0]["id"] == product_row.id


async def test_run_preflight_and_adapter_execution_record_workspace_operations() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-ops",
                name="Step 15 Operations",
                issue_prefix="OPS",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            agent_service = AgentService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Workspace Operations",
                    "executionWorkspacePolicy": {"enabled": True},
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": "D:/work/ops-primary"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Run with workspace operations",
            )
            session.add(issue)
            await session.flush()
            agent = await agent_service.create_agent(
                org.id,
                {
                    "name": "Workspace Operation Agent",
                    "agentRuntimeType": "process",
                    "agentRuntimeConfig": {
                        "command": sys.executable,
                        "args": ["-c", "print('operation-ok')"],
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            run = await HeartbeatService(session).wakeup(
                agent["id"],
                {"payload": {"issueId": issue.id}},
                actor_type="user",
                actor_id="dev",
            )
            operations = await list_workspace_operations_for_run(session, run["id"])
            await session.commit()
    finally:
        await engine.dispose()

    assert run is not None
    assert run["status"] == "succeeded"
    assert len(operations) == 2
    assert {operation.status for operation in operations} == {"succeeded"}
    assert all(operation.execution_workspace_id for operation in operations)
    assert operations[0].metadata_json["preflight"] is True
    assert operations[1].metadata_json["adapterExecution"] is True
    assert operations[1].stdout_excerpt == "operation-ok\r\n" or operations[
        1
    ].stdout_excerpt == "operation-ok\n"
