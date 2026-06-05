from __future__ import annotations

import asyncio
import importlib
import importlib.util
import shutil
import sys
from pathlib import Path
import uuid

from sqlalchemy import Table, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.database.clients import create_database_engine
from packages.database.clients.session import create_session_factory
from packages.database.migrations.runner import upgrade_to_head
from packages.database.schema import (
    Base,
    HeartbeatRun,
    Issue,
    IssueWorkProduct,
    Organization,
    WorkspaceOperation,
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
            assert project_workspace is not None
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Implement workspace resolution",
                project_workspace_id=project_workspace["id"],
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


async def test_run_preflight_uses_org_workspace_when_project_has_no_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    org_root = tmp_path / "org-workspace"
    monkeypatch.setattr(
        "server.services.workspaces.organization_workspace_root",
        lambda org_id: org_root,
    )
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-org-workspace",
                name="Step 15 Org Workspace",
                issue_prefix="ORG",
            )
            session.add(org)
            await session.flush()
            project = await ProjectService(session).create_project(
                org.id,
                {"name": "Org Workspace Fallback"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Use organization workspace",
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-org-workspace",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue.id},
            )
            session.add(run)
            await session.flush()

            context = await WorkspaceService(session).prepare_runtime_context_for_run(
                run.id, run.context_snapshot
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert context is not None
    workspace = context["workspace"]["rudderWorkspace"]
    assert workspace["cwd"] == str(org_root)
    assert workspace["projectWorkspaceId"] is None
    assert workspace["metadata"]["fallback"] == "organization_workspace"
    assert workspace["metadata"]["warnings"] == [
        f'Project has no workspace configured. Run will start in shared organization workspace "{org_root}".'
    ]
    assert context["workspace"]["env"]["RUDDER_WORKSPACE_CWD"] == str(org_root)
    assert context["workspace"]["env"]["RUDDER_ORG_WORKSPACE_ROOT"] == str(org_root)
    assert context["workspace"]["env"]["RUDDER_ORG_ARTIFACTS_DIR"] == str(
        org_root / "artifacts"
    )
    assert "RUDDER_ISSUE_ARTIFACTS_DIR" not in context["workspace"]["env"]
    assert "RUDDER_RUN_ARTIFACTS_DIR" not in context["workspace"]["env"]
    assert "issueArtifactsDir" not in workspace
    assert "runArtifactsDir" not in workspace


async def test_run_preflight_uses_org_workspace_when_issue_has_no_project(
    tmp_path: Path, monkeypatch
) -> None:
    org_root = tmp_path / "org-workspace"
    monkeypatch.setattr(
        "server.services.workspaces.organization_workspace_root",
        lambda org_id: org_root,
    )
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-projectless-issue",
                name="Step 15 Projectless Issue",
                issue_prefix="PLI",
            )
            session.add(org)
            await session.flush()
            issue = Issue(
                org_id=org.id,
                title="Use organization workspace without project",
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-projectless-issue",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue.id},
            )
            session.add(run)
            await session.flush()

            context = await WorkspaceService(session).prepare_runtime_context_for_run(
                run.id, run.context_snapshot
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert context is not None
    workspace = context["workspace"]["rudderWorkspace"]
    assert context["projectId"] is None
    assert context["executionWorkspaceId"] is None
    assert workspace["id"] is None
    assert workspace["cwd"] == str(org_root)
    assert workspace["projectWorkspaceId"] is None
    assert workspace["metadata"]["fallback"] == "organization_workspace"
    assert workspace["metadata"]["warnings"] == [
        f'Issue has no project configured. Run will start in shared organization workspace "{org_root}".'
    ]
    assert context["workspace"]["env"]["RUDDER_WORKSPACE_CWD"] == str(org_root)
    assert context["workspace"]["env"]["RUDDER_ORG_ARTIFACTS_DIR"] == str(
        org_root / "artifacts"
    )
    assert "RUDDER_RUN_ARTIFACTS_DIR" not in context["workspace"]["env"]
    assert "runArtifactsDir" not in workspace


async def test_run_preflight_uses_org_workspace_when_project_workspace_has_no_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    org_root = tmp_path / "org-workspace"
    monkeypatch.setattr(
        "server.services.workspaces.organization_workspace_root",
        lambda org_id: org_root,
    )
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-empty-cwd",
                name="Step 15 Empty Cwd",
                issue_prefix="ECW",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Workspace Without Cwd"},
                actor_type="user",
                actor_id="dev",
            )
            project_workspace = await project_service.create_workspace(
                project["id"],
                {
                    "name": "Remote Metadata Only",
                    "cwd": None,
                    "repoUrl": "https://example.test/org/repo.git",
                    "repoRef": "main",
                },
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Use organization workspace for empty cwd",
                project_workspace_id=project_workspace["id"]
                if project_workspace is not None
                else None,
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-empty-cwd",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue.id},
            )
            session.add(run)
            await session.flush()

            context = await WorkspaceService(session).prepare_runtime_context_for_run(
                run.id, run.context_snapshot
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert project_workspace is not None
    assert context is not None
    workspace = context["workspace"]["rudderWorkspace"]
    assert workspace["cwd"] == str(org_root)
    assert workspace["projectWorkspaceId"] == project_workspace["id"]
    assert workspace["metadata"]["fallback"] == "organization_workspace"
    assert workspace["metadata"]["warnings"] == [
        "Project workspace has no local cwd configured. Run will start "
        f'in shared organization workspace "{org_root}".'
    ]


async def test_issue_run_workspace_cwd_overrides_agent_runtime_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    configured_cwd = tmp_path / "repo-root"
    org_root = tmp_path / "org-workspace"
    configured_cwd.mkdir()

    class CwdWritingAdapter:
        type = "process"

        async def execute(self, context):
            cwd = context.config.get("cwd")
            assert isinstance(cwd, str)
            Path(cwd, "runtime-output.md").write_text(
                "# Runtime output\n", encoding="utf-8"
            )
            return RuntimeExecutionResult(
                exit_code=0,
                result_json={"cwd": cwd},
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
        "server.services.workspaces.organization_workspace_root",
        lambda org_id: org_root,
    )
    monkeypatch.setattr(
        runtime_registry,
        "get_runtime_adapter",
        lambda runtime_type: CwdWritingAdapter(),
    )
    import server.services.heartbeat as heartbeat_module

    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda runtime_type: CwdWritingAdapter(),
    )
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-cwd-override",
                name="Step 15 Cwd Override",
                issue_prefix="CWD",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            agent_service = AgentService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Cwd Override Project"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Do not write issue outputs to agent configured cwd",
            )
            session.add(issue)
            await session.flush()
            agent = await agent_service.create_agent(
                org.id,
                {
                    "name": "Cwd Override Agent",
                    "agentRuntimeType": "process",
                    "agentRuntimeConfig": {
                        "command": sys.executable,
                        "cwd": str(configured_cwd),
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
    assert (org_root / "runtime-output.md").is_file()
    assert not (configured_cwd / "runtime-output.md").exists()
    assert (run["resultJson"] or {})["cwd"] == str(org_root)


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
    context_snapshot = run["contextSnapshot"]
    workspace = context_snapshot["workspace"]["rudderWorkspace"]
    assert context_snapshot["executionWorkspaceId"] == workspace["id"]
    result_json = run["resultJson"] or {}
    assert workspace["id"] in result_json["stdout"]


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
    context_snapshot = run["contextSnapshot"]
    assert context_snapshot is not None
    assert service.execution_workspace_id == context_snapshot["executionWorkspaceId"]
    assert service.status == "stopped"
    assert service.health_status == "unknown"
    result_json = run["resultJson"] or {}
    assert result_json["runtimeServices"][0]["id"] == "svc-report-1"
    assert detail is not None
    assert product_row is not None
    assert product_row.issue_id == detail["id"]
    assert (
        product_row.execution_workspace_id == context_snapshot["executionWorkspaceId"]
    )
    assert product_row.created_by_run_id == run["id"]
    assert result_json["workProducts"][0]["id"] == product_row.id
    assert detail["workProducts"][0]["id"] == product_row.id


async def test_successful_run_captures_generated_workspace_files_as_work_products(
    monkeypatch,
) -> None:
    class FileWritingAdapter:
        type = "process"

        async def execute(self, context):
            workspace = context.config.get("cwd")
            assert isinstance(workspace, str)
            report = Path(workspace) / "CLAUDE_SUMMARY.md"
            report.write_text("# Summary\n\nGenerated by runtime.\n", encoding="utf-8")
            artifacts_dir = (context.env or {}).get("RUDDER_ORG_ARTIFACTS_DIR")
            assert isinstance(artifacts_dir, str)
            artifact = Path(artifacts_dir) / "analysis-plan.md"
            artifact.write_text("# Plan\n\nGenerated artifact.\n", encoding="utf-8")
            nested_artifact = Path(artifacts_dir) / "python-demo" / "README.md"
            nested_artifact.parent.mkdir(parents=True, exist_ok=True)
            nested_artifact.write_text(
                "# Python Demo\n\nGenerated artifact.\n", encoding="utf-8"
            )
            return RuntimeExecutionResult(
                exit_code=0, result_json={"summary": "generated markdown files"}
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
        lambda runtime_type: FileWritingAdapter(),
    )
    import server.services.heartbeat as heartbeat_module

    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda runtime_type: FileWritingAdapter(),
    )
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-generated-files",
                name="Step 15 Generated Files",
                issue_prefix="GWF",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            agent_service = AgentService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Generated File Project",
                    "executionWorkspacePolicy": {"enabled": True},
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": "D:/work/generated-primary"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Generate summary files",
            )
            session.add(issue)
            await session.flush()
            agent = await agent_service.create_agent(
                org.id,
                {
                    "name": "File Writer",
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
            detail = await IssueService(session).get_by_id(issue.id)
            await session.commit()
    finally:
        await engine.dispose()

    assert run is not None
    assert run["status"] == "succeeded"
    result_json = run["resultJson"] or {}
    titles = {product["title"] for product in result_json["workProducts"]}
    assert titles == {
        "CLAUDE_SUMMARY.md",
        "analysis-plan.md",
        "python-demo/README.md",
    }
    assert all(product["contentPath"] for product in result_json["workProducts"])
    assert detail is not None
    detail_titles = {product["title"] for product in detail["workProducts"]}
    assert detail_titles == {
        "CLAUDE_SUMMARY.md",
        "analysis-plan.md",
        "python-demo/README.md",
    }
    metadata_by_title = {
        product["title"]: product["metadata"] for product in detail["workProducts"]
    }
    assert metadata_by_title["CLAUDE_SUMMARY.md"] is not None
    assert metadata_by_title["analysis-plan.md"] is not None
    assert metadata_by_title["CLAUDE_SUMMARY.md"]["source"] == (
        "execution_workspace_scan"
    )
    assert metadata_by_title["analysis-plan.md"]["source"] == (
        "organization_artifacts_scan"
    )
    nested_metadata = metadata_by_title["python-demo/README.md"]
    assert isinstance(nested_metadata, dict)
    assert nested_metadata["source"] == "organization_artifacts_scan"
    assert nested_metadata["workspaceBrowserPath"] == "artifacts/python-demo/README.md"


async def test_run_preflight_and_adapter_execution_record_workspace_operations(
    monkeypatch,
) -> None:
    class LoggingAdapter:
        type = "process"

        async def execute(self, context):
            await context.on_log("stdout", "operation-ok\n")
            return RuntimeExecutionResult(
                exit_code=0,
                result_json={"summary": "operation-ok"},
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

    root = Path("pytest-tmp") / f"step15-operation-logs-{uuid.uuid4().hex}"
    if root.exists():
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    monkeypatch.setenv(
        "OCTOPUS_WORKSPACE_OPERATION_LOG_DIR", str(root / "operation-logs")
    )
    monkeypatch.setattr(
        "server.services.workspaces.organization_workspace_root",
        lambda org_id: (root / "organizations" / org_id / "workspaces").resolve(),
    )
    monkeypatch.setattr(
        runtime_registry,
        "get_runtime_adapter",
        lambda runtime_type: LoggingAdapter(),
    )
    import server.services.heartbeat as heartbeat_module

    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda runtime_type: LoggingAdapter(),
    )
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
            assert run is not None
            operations = await list_workspace_operations_for_run(session, run["id"])
            adapter_log = await WorkspaceService(session).read_operation_log(
                operations[1].id
            )
            await session.commit()
    finally:
        await engine.dispose()
        shutil.rmtree(root, ignore_errors=True)

    assert run is not None
    assert run["status"] == "succeeded"
    assert len(operations) == 2
    assert {operation.status for operation in operations} == {"succeeded"}
    assert all(operation.execution_workspace_id for operation in operations)
    preflight_metadata = operations[0].metadata_json
    adapter_metadata = operations[1].metadata_json
    assert preflight_metadata is not None
    assert adapter_metadata is not None
    assert preflight_metadata["preflight"] is True
    assert adapter_metadata["adapterExecution"] is True
    assert (
        operations[1].stdout_excerpt == "operation-ok\r\n"
        or operations[1].stdout_excerpt == "operation-ok\n"
    )
    assert operations[1].log_store == "local_file"
    assert operations[1].log_ref is not None
    assert operations[1].log_bytes is not None
    assert operations[1].log_bytes > 0
    assert operations[1].log_sha256 is not None
    assert adapter_log is not None
    assert '"stream": "stdout"' in adapter_log["content"]
    assert "operation-ok" in adapter_log["content"]


async def test_runtime_log_callbacks_are_serialized_for_one_session(
    monkeypatch,
) -> None:
    class ConcurrentLoggingAdapter:
        type = "process"

        async def execute(self, context):
            await asyncio.gather(
                context.on_log("stdout", "stdout-one\n"),
                context.on_log("stderr", "stderr-one\n"),
            )
            return RuntimeExecutionResult(exit_code=0, result_json={"summary": "ok"})

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
        lambda runtime_type: ConcurrentLoggingAdapter(),
    )
    import server.services.heartbeat as heartbeat_module

    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda runtime_type: ConcurrentLoggingAdapter(),
    )
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-concurrent-log",
                name="Step 15 Concurrent Log",
                issue_prefix="CLG",
            )
            session.add(org)
            await session.flush()
            agent = await AgentService(session).create_agent(
                org.id,
                {
                    "name": "Concurrent Log Agent",
                    "agentRuntimeType": "process",
                    "agentRuntimeConfig": {"command": sys.executable},
                },
                actor_type="user",
                actor_id="dev",
            )
            run = await HeartbeatService(session).wakeup(
                agent["id"],
                {"payload": {"reason": "concurrent_log_regression"}},
                actor_type="user",
                actor_id="dev",
            )
            assert run is not None
            events = await HeartbeatService(session).list_events(run["id"])
            await session.commit()
    finally:
        await engine.dispose()

    assert run["status"] == "succeeded"
    messages = [event["message"] for event in events]
    assert "stdout-one\n" in messages
    assert "stderr-one\n" in messages


async def test_cancel_running_run_marks_workspace_resources_terminal() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-cancel-cleanup",
                name="Step 15 Cancel Cleanup",
                issue_prefix="CNL",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            agent_service = AgentService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Cancel Cleanup",
                    "executionWorkspacePolicy": {"enabled": True},
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": "D:/work/cancel-cleanup"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Cancel cleanup issue",
            )
            session.add(issue)
            await session.flush()
            workspace = await WorkspaceService(session).resolve_for_issue(issue)
            assert workspace is not None
            agent = await agent_service.create_agent(
                org.id,
                {
                    "name": "Cancel Cleanup Agent",
                    "agentRuntimeType": "process",
                    "agentRuntimeConfig": {"command": sys.executable},
                },
                actor_type="user",
                actor_id="dev",
            )
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent["id"],
                invocation_source="on_demand",
                trigger_detail="manual",
                status="running",
                context_snapshot={
                    "issueId": issue.id,
                    "executionWorkspaceId": workspace["id"],
                    "workspace": {"rudderWorkspace": workspace},
                },
            )
            session.add(run)
            await session.flush()
            service = WorkspaceRuntimeService(
                id="cancel-cleanup-service",
                org_id=org.id,
                project_id=project["id"],
                project_workspace_id=workspace["projectWorkspaceId"],
                execution_workspace_id=workspace["id"],
                issue_id=issue.id,
                scope_type="run",
                scope_id=run.id,
                service_name="preview",
                status="running",
                lifecycle="ephemeral",
                provider="adapter_managed",
                started_by_run_id=run.id,
                health_status="healthy",
            )
            operation = WorkspaceOperation(
                org_id=org.id,
                execution_workspace_id=workspace["id"],
                heartbeat_run_id=run.id,
                phase="workspace_provision",
                command="runtime_adapter.execute",
                status="running",
                metadata_json={"adapterExecution": True},
            )
            session.add_all([service, operation])
            await session.flush()

            cancelled = await HeartbeatService(session).cancel_run(run.id)
            await session.refresh(service)
            await session.refresh(operation)
            await session.commit()
    finally:
        await engine.dispose()

    assert cancelled is not None
    assert cancelled["status"] == "cancelled"
    assert service.status == "stopped"
    assert service.health_status == "unknown"
    assert service.stopped_at is not None
    assert operation.status == "failed"
    assert operation.finished_at is not None
    assert operation.stderr_excerpt == "run cancelled"
    operation_metadata = operation.metadata_json
    assert operation_metadata is not None
    assert operation_metadata["interrupted"] is True
    assert operation_metadata["reason"] == "cancelled"


async def test_orphaned_running_run_marks_workspace_resources_terminal() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-recovery-cleanup",
                name="Step 15 Recovery Cleanup",
                issue_prefix="RCV",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            agent_service = AgentService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Recovery Cleanup",
                    "executionWorkspacePolicy": {"enabled": True},
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": "D:/work/recovery-cleanup"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Recovery cleanup issue",
            )
            session.add(issue)
            await session.flush()
            workspace = await WorkspaceService(session).resolve_for_issue(issue)
            assert workspace is not None
            agent = await agent_service.create_agent(
                org.id,
                {
                    "name": "Recovery Cleanup Agent",
                    "agentRuntimeType": "process",
                    "agentRuntimeConfig": {"command": sys.executable},
                },
                actor_type="user",
                actor_id="dev",
            )
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent["id"],
                invocation_source="on_demand",
                trigger_detail="manual",
                status="running",
                context_snapshot={
                    "issueId": issue.id,
                    "executionWorkspaceId": workspace["id"],
                    "workspace": {"rudderWorkspace": workspace},
                },
            )
            session.add(run)
            await session.flush()
            service = WorkspaceRuntimeService(
                id="recovery-cleanup-service",
                org_id=org.id,
                project_id=project["id"],
                project_workspace_id=workspace["projectWorkspaceId"],
                execution_workspace_id=workspace["id"],
                issue_id=issue.id,
                scope_type="run",
                scope_id=run.id,
                service_name="preview",
                status="running",
                lifecycle="ephemeral",
                provider="adapter_managed",
                started_by_run_id=run.id,
                health_status="healthy",
            )
            operation = WorkspaceOperation(
                org_id=org.id,
                execution_workspace_id=workspace["id"],
                heartbeat_run_id=run.id,
                phase="workspace_provision",
                command="runtime_adapter.execute",
                status="running",
                metadata_json={"adapterExecution": True},
            )
            session.add_all([service, operation])
            await session.flush()

            recovery = await HeartbeatService(session).recover_orphaned_runs()
            await session.refresh(service)
            await session.refresh(operation)
            await session.commit()
    finally:
        await engine.dispose()

    assert recovery and recovery[0]["retryOfRunId"] == run.id
    assert service.status == "stopped"
    assert service.health_status == "unknown"
    assert service.stopped_at is not None
    assert operation.status == "failed"
    assert operation.finished_at is not None
    assert operation.stderr_excerpt == "Run interrupted before server recovery"
    operation_metadata = operation.metadata_json
    assert operation_metadata is not None
    assert operation_metadata["interrupted"] is True
    assert operation_metadata["reason"] == "process_lost"
