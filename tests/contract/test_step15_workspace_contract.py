from __future__ import annotations

import asyncio
import importlib
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path
from typing import cast
import uuid

import pytest
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
from packages.runtimes.types import RuntimeExecutionContext, RuntimeExecutionResult
import packages.runtimes.registry as runtime_registry
from server.services.agents import AgentService
from server.services.heartbeat import HeartbeatService
from server.services.issues import IssueService
from server.services.projects import ProjectService
from server.services.workspaces import WorkspaceService
from packages.shared.validators.workspace import (
    validate_issue_execution_workspace_settings,
    validate_project_execution_workspace_policy,
)


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo_with_branch(path: Path, branch: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", str(path)], check=True, capture_output=True, text=True
    )
    _git(path, "config", "user.name", "Octopus Test")
    _git(path, "config", "user.email", "octopus-test@example.invalid")
    path.joinpath("README.md").write_text("# Test repo\n", encoding="utf-8")
    _git(path, "add", "README.md")
    _git(path, "commit", "-m", "initial")
    _git(path, "branch", "-M", branch)


def _git_path_text(path: Path) -> str:
    return path.resolve().as_posix()


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


def test_workspace_policy_validators_normalize_three_mode_contract() -> None:
    project_policy = validate_project_execution_workspace_policy(
        {
            "enabled": True,
            "defaultMode": "isolated",
            "allowIssueOverride": True,
            "workspaceStrategy": {
                "mode": "operator_branch",
                "baseRef": "main",
                "branchTemplate": "octopus/{issueIdentifier}",
                "operatorBranch": "feature/full-stack",
            },
            "branchPolicy": {"operatorBranch": "feature/full-stack"},
        }
    )

    project_policy_dict = cast(dict[str, object], project_policy)
    project_strategy = cast(dict[str, object], project_policy_dict["workspaceStrategy"])
    assert project_policy_dict["defaultMode"] == "isolated_workspace"
    assert project_strategy["type"] == "git_worktree"
    assert project_strategy["mode"] == "operator_branch"
    assert project_strategy["operatorBranch"] == "feature/full-stack"

    issue_settings = validate_issue_execution_workspace_settings(
        {"mode": "project_primary", "workspaceStrategy": {"mode": "shared_workspace"}}
    )

    issue_settings_dict = cast(dict[str, object], issue_settings)
    issue_strategy = cast(dict[str, object], issue_settings_dict["workspaceStrategy"])
    assert issue_settings_dict["mode"] == "shared_workspace"
    assert issue_strategy["type"] == "project_primary"


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
    assert "workspace_runtime_services_company_exec_workspace_status_idx" in {
        idx.name for idx in schema.WorkspaceRuntimeService.__table__.indexes
    }
    assert "issue_work_products_company_issue_type_idx" in {
        idx.name for idx in schema.IssueWorkProduct.__table__.indexes
    }


async def test_execution_workspace_status_diff_and_archive_service(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-workspace-api",
                name="Workspace API",
                issue_prefix="WAPI",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Workspace API Project",
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
                {"name": "Primary", "cwd": str(project_cwd), "defaultRef": "main"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Workspace API issue",
            )
            session.add(issue)
            await session.flush()
            service = WorkspaceService(session)
            workspace = await service.resolve_for_issue(issue)
            assert workspace is not None
            workspace = await service._ensure_managed_workspace_paths(workspace)
            status_payload = await service.workspace_status(workspace["id"])
            diff_payload = await service.git_diff_for_workspace(workspace["id"])
            archived = await service.archive_workspace(workspace["id"])
            await session.commit()
    finally:
        await engine.dispose()

    assert status_payload is not None
    assert status_payload["workspace"]["id"] == workspace["id"]
    assert status_payload["git"]["available"] is True
    assert diff_payload is not None
    assert diff_payload["available"] is True
    assert archived is not None
    assert archived["status"] == "archived"


async def test_execution_workspace_records_branch_guard_metadata(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-workspace-guard-metadata",
                name="Workspace Guard Metadata",
                issue_prefix="WGM",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Workspace Guard Project",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                        "workspaceStrategy": {
                            "type": "git_worktree",
                            "baseRef": "main",
                        },
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": str(project_cwd), "defaultRef": "main"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(org_id=org.id, project_id=project["id"], title="Guard")
            session.add(issue)
            await session.flush()
            service = WorkspaceService(session)
            workspace = await service.resolve_for_issue(issue)
            assert workspace is not None
            workspace = await service._ensure_managed_workspace_paths(workspace)
            await session.commit()
    finally:
        await engine.dispose()

    assert workspace["branchName"] is not None
    metadata = workspace["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["expectedBranch"] == workspace["branchName"]
    assert metadata["targetRef"] == "main"
    assert metadata["createdFromBranch"] == "main"
    assert len(metadata["createdFromHead"]) == 40


async def test_execution_workspace_push_blocks_branch_mismatch(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-branch-guard",
                name="Branch Guard",
                issue_prefix="BGD",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Branch Guard Project",
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
                {"name": "Primary", "cwd": str(project_cwd), "defaultRef": "main"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(org_id=org.id, project_id=project["id"], title="Guard")
            session.add(issue)
            await session.flush()
            service = WorkspaceService(session)
            workspace = await service.resolve_for_issue(issue)
            assert workspace is not None
            workspace = await service._ensure_managed_workspace_paths(workspace)
            assert workspace["cwd"] is not None
            _git(Path(workspace["cwd"]), "checkout", "-b", "unexpected-branch")
            with pytest.raises(ValueError, match="branch mismatch"):
                await service.push_workspace_branch(workspace["id"])
            await session.commit()
    finally:
        await engine.dispose()


async def test_execution_workspace_merge_preview_reports_clean_and_conflict(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-merge-preview",
                name="Merge Preview",
                issue_prefix="MGP",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Merge Preview Project",
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
                {"name": "Primary", "cwd": str(project_cwd), "defaultRef": "main"},
                actor_type="user",
                actor_id="dev",
            )
            service = WorkspaceService(session)
            clean_issue = Issue(org_id=org.id, project_id=project["id"], title="Clean")
            session.add(clean_issue)
            await session.flush()
            clean_workspace = await service.resolve_for_issue(clean_issue)
            assert clean_workspace is not None
            clean_workspace = await service._ensure_managed_workspace_paths(
                clean_workspace
            )
            assert clean_workspace["cwd"] is not None
            clean_cwd = Path(clean_workspace["cwd"])
            clean_cwd.joinpath("clean.md").write_text("clean\n", encoding="utf-8")
            _git(clean_cwd, "add", "clean.md")
            _git(clean_cwd, "commit", "-m", "clean change")
            clean_preview = await service.merge_preview(clean_workspace["id"])

            conflict_issue = Issue(
                org_id=org.id, project_id=project["id"], title="Conflict"
            )
            session.add(conflict_issue)
            await session.flush()
            conflict_workspace = await service.resolve_for_issue(conflict_issue)
            assert conflict_workspace is not None
            conflict_workspace = await service._ensure_managed_workspace_paths(
                conflict_workspace
            )
            assert conflict_workspace["cwd"] is not None
            conflict_cwd = Path(conflict_workspace["cwd"])
            conflict_cwd.joinpath("README.md").write_text(
                "# worktree\n", encoding="utf-8"
            )
            _git(conflict_cwd, "add", "README.md")
            _git(conflict_cwd, "commit", "-m", "worktree readme")
            project_cwd.joinpath("README.md").write_text("# target\n", encoding="utf-8")
            _git(project_cwd, "add", "README.md")
            _git(project_cwd, "commit", "-m", "target readme")
            conflict_preview = await service.merge_preview(conflict_workspace["id"])
            await session.commit()
    finally:
        await engine.dispose()

    assert clean_preview is not None
    assert clean_preview["available"] is True
    assert clean_preview["canMerge"] is True
    assert clean_preview["conflict"] is False
    assert conflict_preview is not None
    assert conflict_preview["available"] is True
    assert conflict_preview["canMerge"] is False
    assert conflict_preview["conflict"] is True


async def test_execution_workspace_merge_pr_abandon_and_cleanup_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    _git(project_cwd, "remote", "add", "origin", "git@github.com:acme/demo.git")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    original_subprocess_run = subprocess.run

    def fake_subprocess_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        command = args[0] if args else kwargs.get("args")
        if isinstance(command, list) and command[:3] == ["gh", "pr", "create"]:
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="https://github.com/acme/demo/pull/1\n",
                stderr="",
            )
        return original_subprocess_run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fake_subprocess_run)

    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-review-flow",
                name="Review Flow",
                issue_prefix="RVF",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Review Flow Project",
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
                {
                    "name": "Primary",
                    "sourceType": "git_repo",
                    "cwd": str(project_cwd),
                    "repoUrl": "git@github.com:acme/demo.git",
                    "defaultRef": "main",
                },
                actor_type="user",
                actor_id="dev",
            )
            service = WorkspaceService(session)
            merge_issue = Issue(org_id=org.id, project_id=project["id"], title="Merge")
            session.add(merge_issue)
            await session.flush()
            merge_workspace = await service.resolve_for_issue(merge_issue)
            assert merge_workspace is not None
            merge_workspace = await service._ensure_managed_workspace_paths(
                merge_workspace
            )
            assert merge_workspace["cwd"] is not None
            merge_cwd = Path(merge_workspace["cwd"])
            merge_cwd.joinpath("merged.md").write_text("merged\n", encoding="utf-8")
            _git(merge_cwd, "add", "merged.md")
            _git(merge_cwd, "commit", "-m", "merge me")
            pr_plan = await service.prepare_pull_request(merge_workspace["id"])
            created_pr = await service.create_pull_request(merge_workspace["id"])
            merged = await service.merge_workspace(merge_workspace["id"])

            cleanup_issue = Issue(
                org_id=org.id, project_id=project["id"], title="Cleanup"
            )
            session.add(cleanup_issue)
            await session.flush()
            cleanup_workspace = await service.resolve_for_issue(cleanup_issue)
            assert cleanup_workspace is not None
            cleanup_workspace = await service._ensure_managed_workspace_paths(
                cleanup_workspace
            )
            assert cleanup_workspace["cwd"] is not None
            cleanup_cwd = Path(cleanup_workspace["cwd"])
            cleanup_cwd.joinpath("scratch.md").write_text("scratch\n", encoding="utf-8")
            abandoned = await service.abandon_workspace(cleanup_workspace["id"])
            cleaned = await service.cleanup_workspace(
                cleanup_workspace["id"], discard_dirty=True
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert pr_plan is not None
    merge_branch = merge_workspace["branchName"]
    assert merge_branch is not None
    assert pr_plan["sourceBranch"] == merge_branch
    assert pr_plan["targetRef"] == "main"
    assert created_pr is not None
    assert created_pr["created"] is True
    assert created_pr["url"] == "https://github.com/acme/demo/pull/1"
    assert created_pr["sourceBranch"] == merge_branch
    assert created_pr["targetRef"] == "main"
    assert (
        pr_plan["compareUrl"]
        == "https://github.com/acme/demo/compare/main..." + merge_branch
    )
    assert merged is not None
    assert merged["merged"] is True
    assert _git(project_cwd, "branch", "--show-current").stdout.strip() == "main"
    assert project_cwd.joinpath("merged.md").read_text(encoding="utf-8") == "merged\n"
    assert abandoned is not None
    assert abandoned["status"] == "abandoned"
    assert cleaned is not None
    assert cleaned["status"] == "archived"
    assert not cleanup_cwd.exists()


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
                    "repoUrl": None,
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
    assert workspace["strategyType"] == "local_fs"
    assert workspace["providerType"] == "local_fs"
    assert workspace["metadata"] is not None
    assert workspace["metadata"]["fallback"] == "local_fs_execution_workspace"


async def test_shared_workspace_run_uses_project_workspace_cwd(tmp_path: Path) -> None:
    project_cwd = tmp_path / "project-workspace"
    project_cwd.mkdir()
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-shared-project-cwd",
                name="Step 15 Shared Project Cwd",
                issue_prefix="SPC",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Shared Project Cwd",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "shared_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            project_workspace = await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": str(project_cwd)},
                actor_type="user",
                actor_id="dev",
            )
            assert project_workspace is not None
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Run directly in project workspace",
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-shared-project-cwd",
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
    assert workspace["mode"] == "shared_workspace"
    assert workspace["strategyType"] == "project_primary"
    assert workspace["projectWorkspaceId"] == project_workspace["id"]
    assert workspace["cwd"] == str(project_cwd)
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_CWD"] == str(project_cwd)


async def test_shared_workspace_preflight_does_not_switch_project_branch(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "step-29-plugins")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-shared-branch-guard",
                name="Step 15 Shared Branch Guard",
                issue_prefix="SBG",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Shared Branch Guard",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "shared_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                },
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Do not switch shared workspace branch",
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-shared-branch-guard",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue.id},
            )
            session.add(run)
            await session.flush()

            with pytest.raises(ValueError, match="Shared workspace branch mismatch"):
                await WorkspaceService(session).prepare_runtime_context_for_run(
                    run.id, run.context_snapshot
                )
            await session.commit()
    finally:
        await engine.dispose()

    assert _git(project_cwd, "branch", "--show-current").stdout.strip() == (
        "step-29-plugins"
    )


async def test_isolated_workspace_directory_is_a_real_git_worktree(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-real-worktree-contract",
                name="Step 15 Real Worktree Contract",
                issue_prefix="RWT",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Real Worktree Contract",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                        "workspaceStrategy": {
                            "type": "git_worktree",
                            "baseRef": "main",
                        },
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                },
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Use a real git worktree",
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-real-worktree-contract",
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
    assert workspace["providerType"] == "git_worktree"
    worktree_cwd = Path(workspace["cwd"]).resolve()
    assert (
        _git(worktree_cwd, "rev-parse", "--is-inside-work-tree").stdout.strip()
        == "true"
    )
    assert (
        Path(
            _git(worktree_cwd, "rev-parse", "--show-toplevel").stdout.strip()
        ).resolve()
        == worktree_cwd
    )
    assert (
        _git_path_text(worktree_cwd)
        in _git(project_cwd, "worktree", "list", "--porcelain").stdout
    )


async def test_isolated_workspace_reuses_existing_issue_worktree(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-reuse-worktree",
                name="Step 15 Reuse Worktree",
                issue_prefix="RWT",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Reuse Worktree",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                        "workspaceStrategy": {
                            "type": "git_worktree",
                            "baseRef": "main",
                        },
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                },
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Reuse the issue worktree",
            )
            session.add(issue)
            await session.flush()
            run_one = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-reuse-worktree",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue.id},
            )
            session.add(run_one)
            await session.flush()
            first_context = await WorkspaceService(
                session
            ).prepare_runtime_context_for_run(run_one.id, run_one.context_snapshot)
            assert first_context is not None
            first_workspace = first_context["workspace"]["rudderWorkspace"]
            Path(first_workspace["cwd"], "generated.md").write_text(
                "# generated\n", encoding="utf-8"
            )
            run_two = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-reuse-worktree",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue.id},
            )
            session.add(run_two)
            await session.flush()
            second_context = await WorkspaceService(
                session
            ).prepare_runtime_context_for_run(run_two.id, run_two.context_snapshot)
            await session.commit()
    finally:
        await engine.dispose()

    assert second_context is not None
    second_workspace = second_context["workspace"]["rudderWorkspace"]
    assert first_workspace["id"] == second_workspace["id"]
    assert first_workspace["cwd"] == second_workspace["cwd"]
    assert Path(second_workspace["cwd"], "generated.md").is_file()
    assert _git(project_cwd, "branch", "--show-current").stdout.strip() == "main"
    assert (
        _git_path_text(Path(second_workspace["cwd"]))
        in _git(project_cwd, "worktree", "list", "--porcelain").stdout
    )


async def test_operator_branch_run_uses_project_repo_worktree(tmp_path: Path) -> None:
    project_cwd = tmp_path / "mytest"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-operator-worktree",
                name="Step 15 Operator Worktree",
                issue_prefix="OPW",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Operator Branch Project",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "operator_branch",
                        "workspaceStrategy": {
                            "mode": "operator_branch",
                            "operatorBranch": "feature/full-stack",
                        },
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            project_workspace = await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "sourceType": "git_repo",
                    "cwd": str(project_cwd),
                    "repoUrl": "https://github.com/cliffordll/mytest.git",
                    "defaultRef": "main",
                },
                actor_type="user",
                actor_id="dev",
            )
            assert project_workspace is not None
            issue = await IssueService(session).create_issue(
                org.id,
                {
                    "projectId": project["id"],
                    "title": "Run in operator branch",
                },
                actor_type="user",
                actor_id="dev",
            )
            run = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-operator-worktree",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue["id"]},
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
    expected_branch = "feature/full-stack"
    expected_cwd = project_cwd / ".octopus" / "worktrees" / "feature-full-stack"
    assert workspace["mode"] == "operator_branch"
    assert workspace["strategyType"] == "git_worktree"
    assert workspace["providerType"] == "git_worktree"
    assert workspace["projectWorkspaceId"] == project_workspace["id"]
    assert workspace["cwd"] == str(expected_cwd)
    assert workspace["repoUrl"] == "https://github.com/cliffordll/mytest.git"
    assert workspace["baseRef"] == "main"
    assert workspace["branchName"] == expected_branch
    assert workspace["metadata"]["sourceWorkspaceCwd"] == str(project_cwd)
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_CWD"] == str(expected_cwd)
    assert (
        context["workspace"]["env"]["OCTOPUS_WORKSPACE_REPO_URL"]
        == "https://github.com/cliffordll/mytest.git"
    )
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_BRANCH"] == expected_branch
    assert workspace["sourceIssueId"] is None
    assert workspace["metadata"]["operatorWorkspace"] is True


async def test_operator_branch_reuses_fixed_project_worktree_for_multiple_issues(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "mytest"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-operator-reuse",
                name="Step 15 Operator Reuse",
                issue_prefix="OPR",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Operator Reuse Project",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "operator_branch",
                        "branchPolicy": {"operatorBranch": "feature/full-stack"},
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "sourceType": "git_repo",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                },
                actor_type="user",
                actor_id="dev",
            )
            issue_one = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Server work",
            )
            issue_two = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="UI work",
            )
            session.add_all([issue_one, issue_two])
            await session.flush()
            run_one = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-operator-reuse",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue_one.id},
            )
            run_two = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-operator-reuse",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue_two.id},
            )
            session.add_all([run_one, run_two])
            await session.flush()
            context_one = await WorkspaceService(
                session
            ).prepare_runtime_context_for_run(run_one.id, run_one.context_snapshot)
            context_two = await WorkspaceService(
                session
            ).prepare_runtime_context_for_run(run_two.id, run_two.context_snapshot)
            await session.commit()
    finally:
        await engine.dispose()

    assert context_one is not None
    assert context_two is not None
    workspace_one = context_one["workspace"]["rudderWorkspace"]
    workspace_two = context_two["workspace"]["rudderWorkspace"]
    assert workspace_one["id"] == workspace_two["id"]
    assert workspace_one["cwd"] == workspace_two["cwd"]
    assert workspace_one["branchName"] == "feature/full-stack"
    assert workspace_two["branchName"] == "feature/full-stack"
    assert _git(project_cwd, "branch", "--show-current").stdout.strip() == "main"
    assert (
        _git_path_text(Path(workspace_one["cwd"]))
        in _git(project_cwd, "worktree", "list", "--porcelain").stdout
    )


async def test_repo_url_only_shared_workspace_creates_managed_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    source_repo = tmp_path / "source-repo"
    _init_repo_with_branch(source_repo, "main")
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
                url_key="step15-managed-shared",
                name="Step 15 Managed Shared",
                issue_prefix="MGS",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Managed Shared",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "shared_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            project_workspace = await project_service.create_workspace(
                project["id"],
                {
                    "name": "Remote Only",
                    "cwd": None,
                    "repoUrl": str(source_repo),
                    "defaultRef": "main",
                },
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Use managed checkout",
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-managed-shared",
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
            detail = await project_service.get_by_id(project["id"])
            await session.commit()
    finally:
        await engine.dispose()

    assert project_workspace is not None
    assert context is not None
    workspace = context["workspace"]["rudderWorkspace"]
    expected_checkout = org_root / "projects" / project["id"][:8] / "checkout"
    assert workspace["mode"] == "shared_workspace"
    assert workspace["strategyType"] == "project_primary"
    assert workspace["cwd"] == str(expected_checkout)
    assert (
        _git(expected_checkout, "rev-parse", "--is-inside-work-tree").stdout.strip()
        == "true"
    )
    assert detail is not None
    assert detail["primaryWorkspace"] is not None
    assert detail["primaryWorkspace"]["cwd"] == str(expected_checkout)


async def test_repo_url_only_isolated_workspace_creates_worktree_from_managed_checkout(
    tmp_path: Path, monkeypatch
) -> None:
    source_repo = tmp_path / "source-repo"
    _init_repo_with_branch(source_repo, "main")
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
                url_key="step15-managed-isolated",
                name="Step 15 Managed Isolated",
                issue_prefix="MGI",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Managed Isolated",
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
                {
                    "name": "Remote Only",
                    "cwd": None,
                    "repoUrl": str(source_repo),
                    "defaultRef": "main",
                },
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Use managed checkout worktree",
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-managed-isolated",
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
    managed_checkout = org_root / "projects" / project["id"][:8] / "checkout"
    assert workspace["providerType"] == "git_worktree"
    assert workspace["metadata"]["sourceWorkspaceCwd"] == str(managed_checkout)
    assert (
        _git(
            Path(workspace["cwd"]), "rev-parse", "--is-inside-work-tree"
        ).stdout.strip()
        == "true"
    )
    assert _git(managed_checkout, "branch", "--show-current").stdout.strip() == "main"


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
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_CWD"] == str(org_root)
    assert context["workspace"]["env"]["OCTOPUS_ORG_WORKSPACE_ROOT"] == str(org_root)
    assert context["workspace"]["env"]["OCTOPUS_ORG_ARTIFACTS_DIR"] == str(
        org_root / "artifacts"
    )
    assert "OCTOPUS_ISSUE_ARTIFACTS_DIR" not in context["workspace"]["env"]
    assert "OCTOPUS_RUN_ARTIFACTS_DIR" not in context["workspace"]["env"]
    assert all(
        not key.startswith("RUDDER" + "_") for key in context["workspace"]["env"]
    )
    assert all(
        not key.startswith("CONTROL" + "_PLANE_") for key in context["workspace"]["env"]
    )
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
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_CWD"] == str(org_root)
    assert context["workspace"]["env"]["OCTOPUS_ORG_ARTIFACTS_DIR"] == str(
        org_root / "artifacts"
    )
    assert "OCTOPUS_RUN_ARTIFACTS_DIR" not in context["workspace"]["env"]
    assert all(
        not key.startswith("RUDDER" + "_") for key in context["workspace"]["env"]
    )
    assert all(
        not key.startswith("CONTROL" + "_PLANE_") for key in context["workspace"]["env"]
    )
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
                    "repoUrl": None,
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
                            "import os; print(os.environ['OCTOPUS_WORKSPACE_ID'])",
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


async def test_unassigned_heartbeat_uses_read_only_agent_workspace(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class CapturingAdapter:
        type = "process"

        async def execute(self, context):
            captured["context"] = context
            return RuntimeExecutionResult(exit_code=0, result_json={"ok": True})

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
        lambda runtime_type: CapturingAdapter(),
    )
    import server.services.heartbeat as heartbeat_module

    monkeypatch.setattr(
        heartbeat_module,
        "get_runtime_adapter",
        lambda runtime_type: CapturingAdapter(),
    )
    org_root = tmp_path / "org-workspace"
    sandbox_root = tmp_path / "heartbeat-sandbox"
    monkeypatch.setattr(
        "server.services.workspaces.organization_workspace_root",
        lambda org_id: org_root,
    )
    monkeypatch.setattr(
        "server.services.workspaces.agent_heartbeat_workspace_root",
        lambda org_id, workspace_key: (
            sandbox_root / workspace_key / "heartbeat-workspace"
        ),
    )

    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-heartbeat-sandbox",
                name="Step 15 Heartbeat Sandbox",
                issue_prefix="HBS",
            )
            session.add(org)
            await session.flush()
            agent = await AgentService(session).create_agent(
                org.id,
                {
                    "name": "Heartbeat Sandbox Agent",
                    "agentRuntimeType": "process",
                    "agentRuntimeConfig": {"command": sys.executable},
                },
                actor_type="user",
                actor_id="dev",
            )
            run = await HeartbeatService(session).wakeup(
                agent["id"],
                {"payload": {"reason": "timer_without_issue"}},
                actor_type="user",
                actor_id="scheduler",
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert run is not None
    assert run["status"] == "succeeded"
    context = cast(RuntimeExecutionContext, captured["context"])
    expected_cwd = Path(context.config["cwd"])
    assert expected_cwd.name == "heartbeat-workspace"
    assert expected_cwd.parent.parent == sandbox_root
    assert context.config["cwd"] == str(expected_cwd)
    assert context.env is not None
    assert context.env["OCTOPUS_GIT_WRITE_POLICY"] == "read_only"
    assert context.workspace is not None
    workspace = context.workspace["rudderWorkspace"]
    assert workspace["cwd"] == str(expected_cwd)
    assert workspace["mode"] == "agent_default"
    assert workspace["strategyType"] == "adapter_managed"
    assert workspace["gitWritePolicy"] == "read_only"
    assert expected_cwd.is_dir()
    assert run["contextSnapshot"] is not None
    assert run["contextSnapshot"]["workspaceFallback"] == "agent_heartbeat_workspace"


async def test_workspace_write_lease_blocks_concurrent_adapter_operation(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-workspace-lease",
                name="Step 15 Workspace Lease",
                issue_prefix="LSE",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Workspace Lease Project",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "operator_branch",
                        "branchPolicy": {"operatorBranch": "feature/full-stack"},
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": str(project_cwd), "defaultRef": "main"},
                actor_type="user",
                actor_id="dev",
            )
            issue_one = Issue(org_id=org.id, project_id=project["id"], title="One")
            issue_two = Issue(org_id=org.id, project_id=project["id"], title="Two")
            session.add_all([issue_one, issue_two])
            await session.flush()
            service = WorkspaceService(session)
            workspace_one = await service.resolve_for_issue(issue_one)
            workspace_two = await service.resolve_for_issue(issue_two)
            assert workspace_one is not None
            assert workspace_two is not None
            assert workspace_one["id"] == workspace_two["id"]
            await service.begin_operation(
                org_id=org.id,
                run_id="run-one",
                execution_workspace_id=workspace_one["id"],
                phase="workspace_provision",
                command="runtime_adapter.execute",
                cwd=workspace_one["cwd"],
                metadata={"adapterExecution": True},
            )
            with pytest.raises(ValueError, match="already leased"):
                await service.begin_operation(
                    org_id=org.id,
                    run_id="run-two",
                    execution_workspace_id=workspace_two["id"],
                    phase="workspace_provision",
                    command="runtime_adapter.execute",
                    cwd=workspace_two["cwd"],
                    metadata={"adapterExecution": True},
                )
            await session.commit()
    finally:
        await engine.dispose()


async def test_workspace_archive_blocks_running_adapter_operation(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-archive-running",
                name="Step 15 Archive Running",
                issue_prefix="ARC",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Archive Running Project",
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
                {"name": "Primary", "cwd": str(project_cwd), "defaultRef": "main"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(org_id=org.id, project_id=project["id"], title="Archive")
            session.add(issue)
            await session.flush()
            service = WorkspaceService(session)
            workspace = await service.resolve_for_issue(issue)
            assert workspace is not None
            await service.begin_operation(
                org_id=org.id,
                run_id="run-one",
                execution_workspace_id=workspace["id"],
                phase="workspace_provision",
                command="runtime_adapter.execute",
                cwd=workspace["cwd"],
                metadata={"adapterExecution": True},
            )
            with pytest.raises(ValueError, match="adapter operation is running"):
                await service.update_execution_workspace(
                    workspace["id"], {"status": "archived"}
                )
            await session.commit()
    finally:
        await engine.dispose()


async def test_workspace_archive_blocks_dirty_git_worktree(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-archive-dirty",
                name="Step 15 Archive Dirty",
                issue_prefix="ARD",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {
                    "name": "Archive Dirty Project",
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
                {"name": "Primary", "cwd": str(project_cwd), "defaultRef": "main"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(org_id=org.id, project_id=project["id"], title="Archive")
            session.add(issue)
            await session.flush()
            service = WorkspaceService(session)
            workspace = await service.resolve_for_issue(issue)
            assert workspace is not None
            workspace = await service._ensure_managed_workspace_paths(workspace)
            assert workspace["cwd"] is not None
            Path(workspace["cwd"], "dirty.md").write_text("dirty\n", encoding="utf-8")
            with pytest.raises(ValueError, match="uncommitted changes"):
                await service.update_execution_workspace(
                    workspace["id"], {"status": "archived"}
                )
            await session.commit()
    finally:
        await engine.dispose()


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
    issue_ref: dict[str, str] = {}

    class FileWritingAdapter:
        type = "process"

        async def execute(self, context):
            workspace = context.config.get("cwd")
            assert isinstance(workspace, str)
            issue_artifacts = Path(workspace) / "artifacts" / "issues" / issue_ref["id"]
            issue_artifacts.mkdir(parents=True, exist_ok=True)
            report = issue_artifacts / "CLAUDE_SUMMARY.md"
            report.write_text("# Summary\n\nGenerated by runtime.\n", encoding="utf-8")
            memory = (
                Path(workspace)
                / "agents"
                / "file-writer--agent"
                / "memory"
                / "2026-06-11.md"
            )
            memory.parent.mkdir(parents=True, exist_ok=True)
            memory.write_text("# Memory\n\nInternal note.\n", encoding="utf-8")
            artifacts_dir = (context.env or {}).get("OCTOPUS_ORG_ARTIFACTS_DIR")
            assert isinstance(artifacts_dir, str)
            artifact = Path(artifacts_dir) / "analysis-plan.md"
            artifact.write_text("# Plan\n\nGenerated artifact.\n", encoding="utf-8")
            nested_artifact = issue_artifacts / "python-demo" / "README.md"
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
            issue_ref["id"] = issue.id
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
        "python-demo/README.md",
    }
    assert all(not title.startswith("agents/") for title in titles)
    assert all(product["contentPath"] for product in result_json["workProducts"])
    assert detail is not None
    detail_titles = {product["title"] for product in detail["workProducts"]}
    assert detail_titles == {
        "CLAUDE_SUMMARY.md",
        "python-demo/README.md",
    }
    metadata_by_title = {
        product["title"]: product["metadata"] for product in detail["workProducts"]
    }
    assert metadata_by_title["CLAUDE_SUMMARY.md"] is not None
    assert metadata_by_title["CLAUDE_SUMMARY.md"]["source"] == ("issue_artifacts_scan")
    nested_metadata = metadata_by_title["python-demo/README.md"]
    assert isinstance(nested_metadata, dict)
    assert nested_metadata["source"] == "issue_artifacts_scan"


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
