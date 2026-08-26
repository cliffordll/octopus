from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import importlib
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast
import uuid

import pytest
from sqlalchemy import Table, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from packages.database.clients import create_database_engine
from packages.database.clients.session import create_session_factory
from packages.database.migrations.runner import upgrade_to_head
from packages.database.queries.activity_log import insert_activity_log
from packages.database.schema import (
    Agent,
    ActivityLog,
    AgentWakeupRequest,
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
from server.services.heartbeat import (
    HeartbeatService,
    WorkspacePreparationCoordinator,
)
from server.services.issues import IssueService
from server.services.run_dispatch import RunDispatchService
from server.services.projects import ProjectService
from server.services.workspaces import WorkspaceService
from packages.shared.validators.workspace import (
    validate_issue_execution_workspace_settings,
    validate_project_workspace_execution_policy,
)
from packages.shared.types.project import CreateProjectWorkspacePayload


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
    project_policy = validate_project_workspace_execution_policy(
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
                {"name": "Workspace API Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
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
            assert workspace["cwd"] is not None
            Path(workspace["cwd"], ".venv", "local.txt").parent.mkdir()
            Path(workspace["cwd"], ".venv", "local.txt").write_text(
                "local\n", encoding="utf-8"
            )
            Path(workspace["cwd"], "tests", "__pycache__").mkdir(parents=True)
            Path(workspace["cwd"], "tests", "__pycache__", "cache.pyc").write_bytes(
                b"cache"
            )
            files_payload = await service.workspace_files(workspace["id"])
            status_payload = await service.workspace_status(workspace["id"])
            diff_payload = await service.git_diff_for_workspace(workspace["id"])
            shutil.rmtree(Path(workspace["cwd"], ".venv"))
            shutil.rmtree(Path(workspace["cwd"], "tests"))
            archived = await service.archive_workspace(workspace["id"])
            await session.commit()
    finally:
        await engine.dispose()

    assert files_payload is not None
    assert files_payload["available"] is True
    assert {node["name"] for node in files_payload["tree"]} >= {"README.md"}
    assert ".venv" not in {node["name"] for node in files_payload["tree"]}
    assert status_payload is not None
    assert status_payload["workspace"]["id"] == workspace["id"]
    assert status_payload["git"]["available"] is True
    assert status_payload["git"]["dirty"] is False
    assert status_payload["git"]["entries"] == []
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
                {"name": "Workspace Guard Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
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
                {"name": "Branch Guard Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
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
                {"name": "Merge Preview Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
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
                {"name": "Review Flow Project"},
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
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
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


async def test_execution_workspace_resolution_binds_issue_to_workspace(
    tmp_path: Path,
) -> None:
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
                {"name": "Workspace Resolution"},
                actor_type="user",
                actor_id="dev",
            )
            project_cwd = tmp_path / "primary"
            _init_repo_with_branch(project_cwd, "main")
            project_workspace = await projects.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
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
    assert workspace["providerType"] == "git_worktree"
    assert workspace["branchName"] is not None
    assert workspace["metadata"] is not None
    assert workspace["metadata"]["sourceWorkspaceCwd"] == str(project_cwd)


async def test_shared_workspace_run_uses_project_workspace_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    org_root = tmp_path / "org-workspace"
    monkeypatch.setattr(
        "server.services.workspaces.organization_workspace_root",
        lambda org_id: org_root,
    )
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
                {"name": "Shared Project Cwd"},
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
    workspace = context["workspace"]["octopusWorkspace"]
    assert workspace["mode"] == "shared_workspace"
    assert workspace["strategyType"] == "project_primary"
    assert workspace["projectWorkspaceId"] == project_workspace["id"]
    assert workspace["cwd"] == str(project_cwd)
    assert workspace["workspaceKind"] == "project_execution"
    assert workspace["codeSourceKind"] == "local_cwd"
    assert workspace["warnings"] == []
    assert workspace["requiresLease"] is False
    assert workspace["canRun"] is True
    assert workspace["failureReason"] is None
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_CWD"] == str(project_cwd)
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_KIND"] == "project_execution"
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_CODE_SOURCE"] == "local_cwd"
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_WARNINGS_JSON"] == "[]"
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_REQUIRES_LEASE"] == "false"
    issue_artifacts_dir = org_root / "artifacts" / "issues" / issue.id
    assert workspace["issueArtifactsDir"] == str(issue_artifacts_dir)
    assert context["workspace"]["env"]["OCTOPUS_ISSUE_ARTIFACTS_DIR"] == str(
        issue_artifacts_dir
    )
    assert not str(issue_artifacts_dir).startswith(str(project_cwd))


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
                {"name": "Shared Branch Guard"},
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


async def test_project_workspaces_resolve_independent_execution_modes(
    tmp_path: Path,
) -> None:
    frontend_cwd = tmp_path / "frontend"
    frontend_cwd.mkdir()
    backend_cwd = tmp_path / "backend"
    _init_repo_with_branch(backend_cwd, "main")
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-multi-workspace-modes",
                name="Multi Workspace Modes",
                issue_prefix="MWM",
            )
            session.add(org)
            await session.flush()
            projects = ProjectService(session)
            project = await projects.create_project(
                org.id,
                {"name": "Commerce"},
                actor_type="user",
                actor_id="dev",
            )
            frontend = await projects.create_workspace(
                project["id"],
                {
                    "name": "Frontend",
                    "cwd": str(frontend_cwd),
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "shared_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            backend = await projects.create_workspace(
                project["id"],
                {
                    "name": "Backend",
                    "cwd": str(backend_cwd),
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            assert frontend is not None
            assert backend is not None
            frontend_issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                project_workspace_id=frontend["id"],
                title="Frontend task",
            )
            backend_issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                project_workspace_id=backend["id"],
                title="Backend task",
            )
            session.add_all([frontend_issue, backend_issue])
            await session.flush()
            service = WorkspaceService(session)
            frontend_execution = await service.resolve_for_issue(frontend_issue)
            backend_execution = await service.resolve_for_issue(backend_issue)
    finally:
        await engine.dispose()

    assert frontend_execution is not None
    assert frontend_execution["projectWorkspaceId"] == frontend["id"]
    assert frontend_execution["mode"] == "shared_workspace"
    assert frontend_execution["cwd"] == str(frontend_cwd)
    assert backend_execution is not None
    assert backend_execution["projectWorkspaceId"] == backend["id"]
    assert backend_execution["mode"] == "isolated_workspace"
    assert backend_execution["strategyType"] == "git_worktree"
    assert backend_execution["cwd"] != str(backend_cwd)


async def test_existing_execution_workspace_stays_bound_when_default_changes(
    tmp_path: Path,
) -> None:
    frontend_cwd = tmp_path / "frontend"
    frontend_cwd.mkdir()
    backend_cwd = tmp_path / "backend"
    backend_cwd.mkdir()
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-stable-workspace-binding",
                name="Stable Workspace Binding",
                issue_prefix="SWB",
            )
            session.add(org)
            await session.flush()
            projects = ProjectService(session)
            project = await projects.create_project(
                org.id,
                {"name": "Commerce"},
                actor_type="user",
                actor_id="dev",
            )
            frontend = await projects.create_workspace(
                project["id"],
                {"name": "Frontend", "cwd": str(frontend_cwd)},
                actor_type="user",
                actor_id="dev",
            )
            backend = await projects.create_workspace(
                project["id"],
                {"name": "Backend", "cwd": str(backend_cwd)},
                actor_type="user",
                actor_id="dev",
            )
            assert frontend is not None
            assert backend is not None
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Continue frontend task",
            )
            session.add(issue)
            await session.flush()
            service = WorkspaceService(session)
            first_execution = await service.resolve_for_issue(issue)
            await projects.update_workspace(
                project["id"],
                backend["id"],
                {"isPrimary": True},
                actor_type="user",
                actor_id="dev",
            )
            resumed_execution = await service.resolve_for_issue(issue)
    finally:
        await engine.dispose()

    assert first_execution is not None
    assert resumed_execution is not None
    assert resumed_execution["id"] == first_execution["id"]
    assert resumed_execution["projectWorkspaceId"] == frontend["id"]
    assert resumed_execution["cwd"] == str(frontend_cwd)


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
                {"name": "Real Worktree Contract"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
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
    workspace = context["workspace"]["octopusWorkspace"]
    assert workspace["mode"] == "isolated_workspace"
    assert workspace["strategyType"] == "git_worktree"
    assert workspace["providerType"] == "git_worktree"
    assert workspace["workspaceKind"] == "project_execution"
    assert workspace["codeSourceKind"] == "local_cwd"
    assert workspace["metadata"]["sourceWorkspaceCwd"] == str(project_cwd)
    assert workspace["warnings"] == []
    assert workspace["requiresLease"] is False
    assert workspace["canRun"] is True
    assert workspace["failureReason"] is None
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
                {"name": "Reuse Worktree"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
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
            first_workspace = first_context["workspace"]["octopusWorkspace"]
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
    second_workspace = second_context["workspace"]["octopusWorkspace"]
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
                {"name": "Operator Branch Project"},
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
    workspace = context["workspace"]["octopusWorkspace"]
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
                {"name": "Operator Reuse Project"},
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
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "operator_branch",
                        "branchPolicy": {"operatorBranch": "feature/full-stack"},
                    },
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
    workspace_one = context_one["workspace"]["octopusWorkspace"]
    workspace_two = context_two["workspace"]["octopusWorkspace"]
    assert workspace_one["id"] == workspace_two["id"]
    assert workspace_one["cwd"] == workspace_two["cwd"]
    assert workspace_one["branchName"] == "feature/full-stack"
    assert workspace_two["branchName"] == "feature/full-stack"
    assert _git(project_cwd, "branch", "--show-current").stdout.strip() == "main"
    assert (
        _git_path_text(Path(workspace_one["cwd"]))
        in _git(project_cwd, "worktree", "list", "--porcelain").stdout
    )


@pytest.mark.parametrize("mode", ["isolated_workspace", "operator_branch"])
async def test_git_workspace_preparation_is_serialized_by_strategy(
    mode: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_cwd = tmp_path / f"{mode}-source"
    _init_repo_with_branch(project_cwd, "main")
    database_path = tmp_path / f"{mode}.sqlite3"
    org_root = tmp_path / f"{mode}-org"
    monkeypatch.setattr(
        "server.services.workspaces.organization_workspace_root",
        lambda org_id: org_root,
    )
    engine = create_database_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    original_prepare = WorkspaceService.prepare_runtime_context_for_heartbeat
    active_prepares = 0
    max_active_prepares = 0

    async def observed_prepare(
        self: WorkspaceService, *args: object, **kwargs: object
    ) -> dict[str, Any]:
        nonlocal active_prepares, max_active_prepares
        active_prepares += 1
        max_active_prepares = max(max_active_prepares, active_prepares)
        try:
            await asyncio.sleep(0.02)
            return await original_prepare(self, *args, **kwargs)  # type: ignore[arg-type]
        finally:
            active_prepares -= 1

    monkeypatch.setattr(
        WorkspaceService,
        "prepare_runtime_context_for_heartbeat",
        observed_prepare,
    )
    try:
        async with factory() as session:
            org = Organization(
                url_key=f"step15-{mode}",
                name=f"Step 15 {mode}",
                issue_prefix="GIT",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": f"{mode} project"},
                actor_type="user",
                actor_id="dev",
            )
            strategy: dict[str, Any] = {
                "type": "git_worktree",
                "baseRef": "main",
            }
            if mode == "operator_branch":
                strategy["operatorBranch"] = "feature/coordinated"
            await project_service.create_workspace(
                project["id"],
                cast(
                    CreateProjectWorkspacePayload,
                    {
                        "name": "Primary",
                        "cwd": str(project_cwd),
                        "defaultRef": "main",
                        "executionWorkspacePolicy": {
                            "enabled": True,
                            "defaultMode": mode,
                            "workspaceStrategy": strategy,
                        },
                    },
                ),
                actor_type="user",
                actor_id="dev",
            )
            agents = []
            for index in range(2):
                agents.append(
                    await AgentService(session).create_agent(
                        org.id,
                        {
                            "name": f"Git Workspace Agent {index}",
                            "agentRuntimeType": "process",
                            "agentRuntimeConfig": {
                                "command": sys.executable,
                                "args": ["-c", "print('ok')"],
                            },
                        },
                        actor_type="board",
                        actor_id="local-board",
                    )
                )
            issues = [
                Issue(
                    org_id=org.id,
                    project_id=project["id"],
                    title=f"Concurrent Git workspace {index}",
                )
                for index in range(2)
            ]
            session.add_all(issues)
            await session.flush()
            runs = []
            for agent, issue in zip(agents, issues, strict=True):
                run = HeartbeatRun(
                    org_id=org.id,
                    agent_id=agent["id"],
                    invocation_source="on_demand",
                    trigger_detail="manual",
                    status="running",
                    context_snapshot={"issueId": issue.id},
                )
                session.add(run)
                runs.append(run)
            await session.commit()

        contexts = await asyncio.gather(
            *(
                WorkspacePreparationCoordinator(factory).prepare(
                    agent_id=agent["id"], run_id=run.id, org_id=org.id
                )
                for agent, run in zip(agents, runs, strict=True)
            )
        )

        assert max_active_prepares == 1
        workspace_ids = {
            context["executionWorkspaceId"]
            for context in contexts
            if context is not None
        }
        expected_workspace_count = 2 if mode == "isolated_workspace" else 1
        assert len(workspace_ids) == expected_workspace_count
    finally:
        await engine.dispose()


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
                {"name": "Managed Shared"},
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
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "shared_workspace",
                    },
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
            workspace_service = WorkspaceService(session)
            context = await workspace_service.prepare_runtime_context_for_run(
                run.id, run.context_snapshot
            )
            issue_two = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Reuse managed checkout",
            )
            session.add(issue_two)
            await session.flush()
            run_two = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-managed-shared-two",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue_two.id},
            )
            session.add(run_two)
            await session.flush()
            context_two = await workspace_service.prepare_runtime_context_for_run(
                run_two.id, run_two.context_snapshot
            )
            assert context is not None
            await session.execute(
                text(
                    "update execution_workspaces set branch_name = NULL where id = :id"
                ),
                {"id": context["workspace"]["octopusWorkspace"]["id"]},
            )
            legacy_workspace = await workspace_service.get_execution_workspace(
                context["workspace"]["octopusWorkspace"]["id"]
            )
            detail = await project_service.get_by_id(project["id"])
            await session.commit()
    finally:
        await engine.dispose()

    assert project_workspace is not None
    assert context is not None
    assert context_two is not None
    workspace = context["workspace"]["octopusWorkspace"]
    workspace_two = context_two["workspace"]["octopusWorkspace"]
    expected_checkout = (
        org_root
        / "projects"
        / project["id"][:8]
        / project_workspace["id"][:8]
        / "checkout"
    )
    assert workspace["mode"] == "shared_workspace"
    assert workspace["strategyType"] == "project_primary"
    assert workspace["baseRef"] == "main"
    assert workspace["branchName"] == "main"
    assert legacy_workspace is not None
    assert legacy_workspace["branchName"] == "main"
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_BRANCH"] == "main"
    assert workspace["cwd"] == str(expected_checkout)
    assert workspace_two["id"] == workspace["id"]
    assert workspace_two["cwd"] == str(expected_checkout)
    assert workspace["workspaceKind"] == "project_execution"
    assert workspace["codeSourceKind"] == "managed_checkout"
    assert (
        context["workspace"]["env"]["OCTOPUS_WORKSPACE_CODE_SOURCE"]
        == "managed_checkout"
    )
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
                {"name": "Managed Isolated"},
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
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
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
            workspace_service = WorkspaceService(session)
            context = await workspace_service.prepare_runtime_context_for_run(
                run.id, run.context_snapshot
            )
            issue_two = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Use a second managed checkout worktree",
            )
            session.add(issue_two)
            await session.flush()
            run_two = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-managed-isolated-two",
                invocation_source="on_demand",
                trigger_detail="manual",
                status="queued",
                context_snapshot={"issueId": issue_two.id},
            )
            session.add(run_two)
            await session.flush()
            context_two = await workspace_service.prepare_runtime_context_for_run(
                run_two.id, run_two.context_snapshot
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert context is not None
    assert context_two is not None
    assert project_workspace is not None
    workspace = context["workspace"]["octopusWorkspace"]
    workspace_two = context_two["workspace"]["octopusWorkspace"]
    managed_checkout = (
        org_root
        / "projects"
        / project["id"][:8]
        / project_workspace["id"][:8]
        / "checkout"
    )
    assert workspace["providerType"] == "git_worktree"
    assert workspace["workspaceKind"] == "project_execution"
    assert workspace["codeSourceKind"] == "managed_checkout"
    assert workspace["metadata"]["sourceWorkspaceCwd"] == str(managed_checkout)
    assert workspace_two["metadata"]["sourceWorkspaceCwd"] == str(managed_checkout)
    assert workspace_two["id"] != workspace["id"]
    assert workspace_two["cwd"] != workspace["cwd"]
    assert workspace_two["branchName"] != workspace["branchName"]
    worktree_listing = _git(managed_checkout, "worktree", "list", "--porcelain").stdout
    for current_workspace in (workspace, workspace_two):
        current_cwd = Path(current_workspace["cwd"])
        assert (
            _git(current_cwd, "rev-parse", "--is-inside-work-tree").stdout.strip()
            == "true"
        )
        assert _git_path_text(current_cwd) in worktree_listing
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
    workspace = context["workspace"]["octopusWorkspace"]
    assert workspace["cwd"] == str(org_root)
    assert workspace["mode"] == "organization_scratch"
    assert workspace["projectWorkspaceId"] is None
    assert workspace["metadata"]["resolvedMode"] == "organization_scratch"
    assert workspace["metadata"]["fallback"] == "organization_workspace"
    assert workspace["metadata"]["warnings"] == [
        f'Project has no workspace configured. Run will start in organization scratch workspace "{org_root}".'
    ]
    assert workspace["workspaceKind"] == "organization_scratch"
    assert workspace["codeSourceKind"] == "none"
    assert workspace["warnings"] == workspace["metadata"]["warnings"]
    assert workspace["requiresLease"] is False
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_CWD"] == str(org_root)
    assert (
        context["workspace"]["env"]["OCTOPUS_WORKSPACE_KIND"] == "organization_scratch"
    )
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_CODE_SOURCE"] == "none"
    assert context["workspace"]["env"]["OCTOPUS_ORG_WORKSPACE_ROOT"] == str(org_root)
    assert context["workspace"]["env"]["OCTOPUS_ORG_ARTIFACTS_DIR"] == str(
        org_root / "artifacts"
    )
    issue_artifacts_dir = org_root / "artifacts" / "issues" / issue.id
    assert context["workspace"]["env"]["OCTOPUS_ISSUE_ARTIFACTS_DIR"] == str(
        issue_artifacts_dir
    )
    assert "OCTOPUS_RUN_ARTIFACTS_DIR" not in context["workspace"]["env"]
    assert all(
        not key.startswith("R" + "UDDER" + "_") for key in context["workspace"]["env"]
    )
    assert all(
        not key.startswith("CONTROL" + "_PLANE_") for key in context["workspace"]["env"]
    )
    assert workspace["issueArtifactsDir"] == str(issue_artifacts_dir)
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
    workspace = context["workspace"]["octopusWorkspace"]
    assert context["projectId"] is None
    assert context["executionWorkspaceId"] is None
    assert workspace["id"] is None
    assert workspace["cwd"] == str(org_root)
    assert workspace["mode"] == "organization_scratch"
    assert workspace["projectWorkspaceId"] is None
    assert workspace["metadata"]["resolvedMode"] == "organization_scratch"
    assert workspace["metadata"]["fallback"] == "organization_workspace"
    assert workspace["metadata"]["warnings"] == [
        f'Issue has no project configured. Run will start in organization scratch workspace "{org_root}".'
    ]
    assert workspace["workspaceKind"] == "organization_scratch"
    assert workspace["codeSourceKind"] == "none"
    assert workspace["warnings"] == workspace["metadata"]["warnings"]
    assert workspace["requiresLease"] is False
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_CWD"] == str(org_root)
    assert (
        context["workspace"]["env"]["OCTOPUS_WORKSPACE_KIND"] == "organization_scratch"
    )
    assert context["workspace"]["env"]["OCTOPUS_WORKSPACE_CODE_SOURCE"] == "none"
    assert context["workspace"]["env"]["OCTOPUS_ORG_ARTIFACTS_DIR"] == str(
        org_root / "artifacts"
    )
    assert "OCTOPUS_RUN_ARTIFACTS_DIR" not in context["workspace"]["env"]
    assert all(
        not key.startswith("R" + "UDDER" + "_") for key in context["workspace"]["env"]
    )
    assert all(
        not key.startswith("CONTROL" + "_PLANE_") for key in context["workspace"]["env"]
    )
    assert "runArtifactsDir" not in workspace


async def test_run_preflight_rejects_project_workspace_without_code_source(
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

            with pytest.raises(
                ValueError,
                match="requires a local cwd or repo URL",
            ):
                await WorkspaceService(session).prepare_runtime_context_for_run(
                    run.id, run.context_snapshot
                )
    finally:
        await engine.dispose()

    assert project_workspace is not None


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


async def test_run_preflight_injects_workspace_context_into_runtime_env(
    tmp_path: Path,
) -> None:
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
                {"name": "Workspace Runtime"},
                actor_type="user",
                actor_id="dev",
            )
            project_cwd = tmp_path / "runtime-primary"
            _init_repo_with_branch(project_cwd, "main")
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
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
    workspace = context_snapshot["workspace"]["octopusWorkspace"]
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
    workspace = context.workspace["octopusWorkspace"]
    assert workspace["cwd"] == str(expected_cwd)
    assert workspace["mode"] == "agent_default"
    assert workspace["workspaceKind"] == "agent_scratch"
    assert workspace["metadata"]["resolvedMode"] == "agent_default"
    assert workspace["strategyType"] == "adapter_managed"
    assert workspace["gitWritePolicy"] == "read_only"
    assert expected_cwd.is_dir()
    assert run["contextSnapshot"] is not None
    assert run["contextSnapshot"]["workspaceFallback"] == "agent_heartbeat_workspace"


async def test_workspace_operations_do_not_take_workspace_write_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
                url_key="step15-workspace-no-lease",
                name="Step 15 Workspace No Lease",
                issue_prefix="NLS",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Workspace No Lease Project"},
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
            first_operation = await service.begin_operation(
                org_id=org.id,
                run_id="run-one",
                execution_workspace_id=workspace_one["id"],
                phase="workspace_provision",
                command="runtime_adapter.execute",
                cwd=workspace_one["cwd"],
                metadata={"adapterExecution": True},
            )
            second_operation = await service.begin_operation(
                org_id=org.id,
                run_id="run-two",
                execution_workspace_id=workspace_two["id"],
                phase="workspace_provision",
                command="runtime_adapter.execute",
                cwd=workspace_two["cwd"],
                metadata={"adapterExecution": True},
            )
            assert first_operation["status"] == "running"
            assert second_operation["status"] == "running"
            await session.commit()
    finally:
        await engine.dispose()


async def test_settled_children_queue_parent_continuation() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-child-continuation",
                name="Step 15 Child Continuation",
                issue_prefix="CHD",
            )
            session.add(org)
            await session.flush()
            parent_agent = Agent(org_id=org.id, name="Parent Agent")
            child_agent = Agent(org_id=org.id, name="Child Agent")
            session.add_all([parent_agent, child_agent])
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Parent",
                status="in_progress",
                assignee_agent_id=parent_agent.id,
            )
            session.add(parent)
            await session.flush()
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Child",
                status="done",
                assignee_agent_id=child_agent.id,
            )
            settled_sibling = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Settled sibling",
                status="done",
                completed_at=datetime.now(UTC),
                assignee_agent_id=child_agent.id,
            )
            session.add_all([child, settled_sibling])
            await session.flush()
            child_run = HeartbeatRun(
                org_id=org.id,
                agent_id=child_agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={"issueId": child.id},
            )
            session.add(child_run)
            await session.flush()

            await HeartbeatService(session)._wake_parent_after_child_settled(
                child_run, child
            )
            await session.flush()

            result = await session.execute(
                select(HeartbeatRun).where(
                    HeartbeatRun.agent_id == parent_agent.id,
                    HeartbeatRun.status == "queued",
                )
            )
            continuation = result.scalar_one()
            assert continuation.context_snapshot is not None
            assert continuation.context_snapshot["issueId"] == parent.id
            assert (
                continuation.context_snapshot["wakeReason"] == "issue_children_settled"
            )
            activity = (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.entity_id == parent.id,
                        ActivityLog.action == "issue.children_settled",
                    )
                )
            ).scalar_one()
            assert activity.details["completedChildIssueId"] == child.id
            assert activity.details["reason"] == "issue_children_settled"
    finally:
        await engine.dispose()


async def test_done_child_waits_for_run_finalization_before_parent_continuation() -> (
    None
):
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="child-finalization-barrier",
                name="Child Finalization Barrier",
                issue_prefix="CFB",
            )
            session.add(org)
            await session.flush()
            parent_agent = Agent(org_id=org.id, name="Parent Agent")
            child_agent = Agent(org_id=org.id, name="Child Agent")
            session.add_all([parent_agent, child_agent])
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Parent",
                status="in_progress",
                assignee_agent_id=parent_agent.id,
            )
            session.add(parent)
            await session.flush()
            origin_run_id = str(uuid.uuid4())
            policy = {
                "version": 1,
                "mode": "parent_output_required",
                "requirements": {
                    "minimumOutputs": 1,
                    "primaryOutputRequired": True,
                },
            }
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Child",
                status="done",
                origin_kind="delegation",
                origin_run_id=origin_run_id,
                closeout_policy=policy,
                completed_at=datetime.now(UTC),
                assignee_agent_id=child_agent.id,
            )
            session.add(child)
            await session.flush()
            child_run = HeartbeatRun(
                org_id=org.id,
                agent_id=child_agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="running",
                context_snapshot={"issueId": child.id},
            )
            session.add(child_run)
            await session.flush()
            child.execution_run_id = child_run.id
            child.checkout_run_id = child_run.id
            await session.flush()

            heartbeat = HeartbeatService(session)
            parent_agent_id = (
                await heartbeat.queue_parent_continuation_for_settled_child(child.id)
            )
            assert parent_agent_id is None
            assert (
                await session.execute(
                    select(HeartbeatRun).where(HeartbeatRun.agent_id == parent_agent.id)
                )
            ).scalar_one_or_none() is None

            await WorkspaceService(session).create_work_product_for_issue(
                org_id=org.id,
                issue_id=child.id,
                project_id=None,
                payload={
                    "type": "document",
                    "provider": "octopus",
                    "title": "child-report.md",
                    "status": "active",
                    "isPrimary": True,
                    "createdByRunId": child_run.id,
                },
            )
            child_run.status = "succeeded"
            child_run.finished_at = datetime.now(UTC)
            child.execution_run_id = None
            child.checkout_run_id = None
            await session.flush()

            parent_agent_id = (
                await heartbeat.queue_parent_continuation_for_settled_child(child.id)
            )
            assert parent_agent_id == parent_agent.id
            continuation = (
                await session.execute(
                    select(HeartbeatRun).where(HeartbeatRun.agent_id == parent_agent.id)
                )
            ).scalar_one()
            assert continuation.status == "queued"
    finally:
        await engine.dispose()


async def test_dispatcher_runs_parent_continuation_queued_by_child_closeout(
    tmp_path: Path,
) -> None:
    engine = create_database_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'parent-continuation-dispatch.db'}"
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="parent-continuation-dispatch",
                name="Parent Continuation Dispatch",
                issue_prefix="PCD",
            )
            session.add(org)
            await session.flush()
            runtime_config = {
                "command": sys.executable,
                "args": ["-c", "print('continued')"],
            }
            parent_agent = Agent(
                org_id=org.id,
                name="Parent Agent",
                agent_runtime_config=runtime_config,
            )
            child_agent = Agent(
                org_id=org.id,
                name="Child Agent",
                agent_runtime_config=runtime_config,
            )
            session.add_all([parent_agent, child_agent])
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Parent",
                status="in_progress",
                assignee_agent_id=parent_agent.id,
            )
            session.add(parent)
            await session.flush()
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Child",
                status="done",
                completed_at=datetime.now(UTC),
                assignee_agent_id=child_agent.id,
            )
            session.add(child)
            await session.flush()
            child_wakeup = AgentWakeupRequest(
                org_id=org.id,
                agent_id=child_agent.id,
                source="assignment",
                trigger_detail="system",
                reason="issue_assigned",
                status="queued",
            )
            session.add(child_wakeup)
            await session.flush()
            child_run = HeartbeatRun(
                org_id=org.id,
                agent_id=child_agent.id,
                invocation_source="assignment",
                run_purpose="task_execution",
                trigger_detail="system",
                status="queued",
                wakeup_request_id=child_wakeup.id,
                context_snapshot={
                    "issueId": child.id,
                    "wakeReason": "issue_assigned",
                },
            )
            session.add(child_run)
            await session.flush()
            child_wakeup.run_id = child_run.id
            child.execution_run_id = child_run.id
            child.checkout_run_id = child_run.id
            child.execution_agent_name_key = child_agent.name.lower()
            child.execution_locked_at = datetime.now(UTC)
            parent_runs_before = (
                (
                    await session.execute(
                        select(HeartbeatRun).where(
                            HeartbeatRun.agent_id == parent_agent.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert parent_runs_before == []
            await session.commit()

            await RunDispatchService(factory).dispatch_agent(child_agent.id)

        async with factory() as session:
            child_after = await session.get(HeartbeatRun, child_run.id)
            parent_after = (
                await session.execute(
                    select(HeartbeatRun).where(HeartbeatRun.agent_id == parent_agent.id)
                )
            ).scalar_one()
            assert child_after is not None and child_after.status == "succeeded"
            assert parent_after is not None
            assert parent_after.status == "failed"
            assert parent_after.error_code == "closeout_missing"
            assert parent_after.started_at is not None
    finally:
        await engine.dispose()


async def test_reopened_child_can_queue_a_new_parent_continuation() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="reopened-child-continuation",
                name="Reopened Child Continuation",
                issue_prefix="RCC",
            )
            session.add(org)
            await session.flush()
            parent_agent = Agent(org_id=org.id, name="Parent Agent")
            child_agent = Agent(org_id=org.id, name="Child Agent")
            session.add_all([parent_agent, child_agent])
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Parent",
                status="in_progress",
                assignee_agent_id=parent_agent.id,
            )
            session.add(parent)
            await session.flush()
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Child",
                status="todo",
                assignee_agent_id=child_agent.id,
            )
            settled_sibling = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Settled sibling",
                status="done",
                completed_at=datetime.now(UTC),
                assignee_agent_id=child_agent.id,
            )
            session.add_all([child, settled_sibling])
            await session.flush()
            heartbeat = HeartbeatService(session)
            issues = IssueService(session)

            child_run = HeartbeatRun(
                org_id=org.id,
                agent_id=child_agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={"issueId": child.id},
            )
            session.add(child_run)
            await session.flush()
            child.execution_run_id = child_run.id
            child.checkout_run_id = child_run.id
            child.execution_agent_name_key = child_agent.name.lower()
            child.execution_locked_at = datetime.now(UTC)
            await issues.update_issue(
                child.id,
                {"status": "done"},
                actor_type="agent",
                actor_id=child_agent.id,
                run_id=child_run.id,
            )
            await session.refresh(child)

            first_agent_id = (
                await heartbeat.queue_parent_continuation_for_settled_child(child.id)
            )
            assert first_agent_id == parent_agent.id
            sibling_agent_id = (
                await heartbeat.queue_parent_continuation_for_settled_child(
                    settled_sibling.id
                )
            )
            assert sibling_agent_id == parent_agent.id
            await heartbeat._release_issue_execution(child_run)
            first_run = (
                await session.execute(
                    select(HeartbeatRun).where(HeartbeatRun.agent_id == parent_agent.id)
                )
            ).scalar_one()
            first_wakeup = await session.get(
                AgentWakeupRequest, first_run.wakeup_request_id
            )
            assert first_wakeup is not None
            wakeups_after_retry = (
                (
                    await session.execute(
                        select(AgentWakeupRequest).where(
                            AgentWakeupRequest.agent_id == parent_agent.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(wakeups_after_retry) == 1
            first_run.status = "succeeded"
            first_wakeup.status = "completed"
            parent.execution_run_id = None
            parent.checkout_run_id = None
            parent.execution_agent_name_key = None
            parent.execution_locked_at = None

            await issues.update_issue(
                child.id,
                {"reopen": True},
                actor_type="user",
                actor_id="test-user",
            )
            await issues.update_issue(
                child.id,
                {"status": "done"},
                actor_type="agent",
                actor_id=child_agent.id,
            )

            second_agent_id = (
                await heartbeat.queue_parent_continuation_for_settled_child(child.id)
            )
            await session.refresh(child)
            child_run_two = HeartbeatRun(
                org_id=org.id,
                agent_id=child_agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={"issueId": child.id},
            )
            session.add(child_run_two)
            await session.flush()
            child.execution_run_id = child_run_two.id
            child.checkout_run_id = child_run_two.id
            await heartbeat._release_issue_execution(child_run_two)
            runs = (
                (
                    await session.execute(
                        select(HeartbeatRun).where(
                            HeartbeatRun.agent_id == parent_agent.id
                        )
                    )
                )
                .scalars()
                .all()
            )

            assert second_agent_id == parent_agent.id
            assert len(runs) == 2
            assert {run.status for run in runs} == {"succeeded", "queued"}
            wakeups = (
                (
                    await session.execute(
                        select(AgentWakeupRequest).where(
                            AgentWakeupRequest.agent_id == parent_agent.id
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(wakeups) == 2
            settlement_activities = (
                (
                    await session.execute(
                        select(ActivityLog).where(
                            ActivityLog.entity_id == parent.id,
                            ActivityLog.action == "issue.children_settled",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(settlement_activities) == 2
    finally:
        await engine.dispose()


@pytest.mark.skipif(
    not os.getenv("OCTOPUS_TEST_POSTGRES_URL"),
    reason="requires OCTOPUS_TEST_POSTGRES_URL",
)
async def test_postgres_concurrent_last_children_queue_one_parent_continuation() -> (
    None
):
    database_url = os.environ["OCTOPUS_TEST_POSTGRES_URL"]
    engine = create_database_engine(database_url)
    factory: async_sessionmaker = create_session_factory(engine)
    schema_name = f"octopus_parent_settlement_{uuid.uuid4().hex}"
    quoted_schema = f'"{schema_name}"'
    first_session = None
    second_session = None
    try:
        async with engine.begin() as connection:
            await connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
            await connection.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
            await connection.run_sync(Base.metadata.create_all)

        async with factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
                org = Organization(
                    url_key=f"pg-parent-settlement-{uuid.uuid4().hex}",
                    name="PostgreSQL Parent Settlement",
                    issue_prefix="PPS",
                )
                session.add(org)
                await session.flush()
                parent_agent = Agent(org_id=org.id, name="Parent Agent")
                child_agent = Agent(org_id=org.id, name="Child Agent")
                session.add_all([parent_agent, child_agent])
                await session.flush()
                parent = Issue(
                    org_id=org.id,
                    title="Parent",
                    status="in_progress",
                    assignee_agent_id=parent_agent.id,
                )
                session.add(parent)
                await session.flush()
                first_child = Issue(
                    org_id=org.id,
                    parent_id=parent.id,
                    title="First child",
                    status="in_progress",
                    assignee_agent_id=child_agent.id,
                )
                second_child = Issue(
                    org_id=org.id,
                    parent_id=parent.id,
                    title="Second child",
                    status="in_progress",
                    assignee_agent_id=child_agent.id,
                )
                session.add_all([first_child, second_child])
                await session.flush()
                org_id = org.id
                parent_agent_id = parent_agent.id
                first_child_id = first_child.id
                second_child_id = second_child.id

        first_session = factory()
        second_session = factory()
        await first_session.begin()
        await second_session.begin()
        await first_session.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
        await second_session.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
        first_child = await first_session.get(Issue, first_child_id)
        second_child = await second_session.get(Issue, second_child_id)
        assert first_child is not None and second_child is not None
        first_child.status = "done"
        first_child.completed_at = datetime.now(UTC)
        second_child.status = "done"
        second_child.completed_at = datetime.now(UTC)
        await first_session.flush()
        await second_session.flush()

        first_result = await HeartbeatService(
            first_session
        ).queue_parent_continuation_for_settled_child(
            first_child_id, expected_org_id=org_id
        )
        assert first_result is None

        second_task = asyncio.create_task(
            HeartbeatService(
                second_session
            ).queue_parent_continuation_for_settled_child(
                second_child_id, expected_org_id=org_id
            )
        )
        await asyncio.sleep(0.05)
        assert not second_task.done()
        await first_session.commit()
        second_result = await asyncio.wait_for(second_task, timeout=5)
        assert second_result == parent_agent_id
        await second_session.commit()

        async with factory() as session:
            async with session.begin():
                await session.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
                runs = (
                    (
                        await session.execute(
                            select(HeartbeatRun).where(
                                HeartbeatRun.agent_id == parent_agent_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                wakeups = (
                    (
                        await session.execute(
                            select(AgentWakeupRequest).where(
                                AgentWakeupRequest.agent_id == parent_agent_id
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                assert len(runs) == 1
                assert len(wakeups) == 1
                assert wakeups[0].status == "queued"
                assert wakeups[0].reason == "issue_children_settled"
    finally:
        if first_session is not None:
            await first_session.close()
        if second_session is not None:
            await second_session.close()
        async with engine.begin() as connection:
            await connection.execute(
                text(f"DROP SCHEMA IF EXISTS {quoted_schema} CASCADE")
            )
        await engine.dispose()


async def test_parent_run_with_active_children_finishes_without_closing_issue() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-parent-waiting",
                name="Step 15 Parent Waiting",
                issue_prefix="PWT",
            )
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
            session.add(agent)
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Parent",
                status="in_progress",
                assignee_agent_id=agent.id,
            )
            session.add(parent)
            await session.flush()
            session.add(
                Issue(
                    org_id=org.id,
                    parent_id=parent.id,
                    title="Active Child",
                    status="todo",
                )
            )
            wakeup = AgentWakeupRequest(
                org_id=org.id,
                agent_id=agent.id,
                source="assignment",
                trigger_detail="system",
                status="claimed",
            )
            session.add(wakeup)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                wakeup_request_id=wakeup.id,
                context_snapshot={"issueId": parent.id},
            )
            session.add(run)
            await session.flush()
            wakeup.run_id = run.id
            parent.execution_run_id = run.id
            await session.flush()

            final = await HeartbeatService(session)._complete_finalized_run(
                agent=agent,
                running=run,
                final=run,
                final_status="succeeded",
                result=RuntimeExecutionResult(exit_code=0),
                sequence=1,
            )
            await session.flush()
            await session.refresh(wakeup)
            await session.refresh(agent)
            await session.refresh(parent)

            assert final.status == "succeeded"
            assert final.error_code is None
            assert wakeup.status == "completed"
            assert agent.status == "idle"
            assert parent.execution_run_id is None
            assert parent.status == "in_progress"
    finally:
        await engine.dispose()


async def test_non_delegated_parent_done_ignores_delegation_closeout_policy() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-parent-warning",
                name="Step 15 Parent Warning",
                issue_prefix="PCW",
            )
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
            session.add(agent)
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Four beauties report",
                status="done",
                assignee_agent_id=agent.id,
            )
            session.add(parent)
            await session.flush()
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Xi Shi report",
                status="done",
                completed_at=datetime.now(UTC) - timedelta(minutes=5),
            )
            session.add(child)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                context_snapshot={"issueId": parent.id},
            )
            session.add(run)
            await session.flush()

            final = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(agent, run)
            warnings = (
                (
                    await session.execute(
                        select(ActivityLog).where(
                            ActivityLog.action
                            == "issue.parent_deliverable_convergence_warning"
                        )
                    )
                )
                .scalars()
                .all()
            )

            assert final.status == "succeeded"
            assert warnings == []
    finally:
        await engine.dispose()


async def test_done_issue_with_expected_output_requires_matching_work_product() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-done-output-required",
                name="Step 15 Done Output Required",
                issue_prefix="DOR",
            )
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Lake Agent")
            session.add(agent)
            await session.flush()
            issue = Issue(
                org_id=org.id,
                title="太湖介绍",
                description="完成后将文档保存到 reports/ 目录下，文件名为 taihu.md",
                status="done",
                assignee_agent_id=agent.id,
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                context_snapshot={"issueId": issue.id},
            )
            session.add(run)
            await session.flush()

            final = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(agent, run)
            activity = (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.action == "issue.done_missing_work_product"
                    )
                )
            ).scalar_one()

            assert final.status == "failed"
            assert final.error_code == "closeout_missing"
            assert activity.entity_id == issue.id
            assert activity.details["reason"] == "done_without_expected_work_product"
            assert activity.details["expectedPaths"] == [
                "reports/taihu.md",
                "taihu.md",
            ]
    finally:
        await engine.dispose()


async def test_failed_run_reconciles_done_issue_missing_expected_output_to_blocked() -> (
    None
):
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-failed-done-reconcile",
                name="Step 15 Failed Done Reconcile",
                issue_prefix="FDR",
            )
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Lake Agent")
            session.add(agent)
            await session.flush()
            issue = Issue(
                org_id=org.id,
                title="巢湖介绍",
                description="完成后将文档保存到 reports/ 目录下，文件名为 chaohu.md",
                status="done",
                completed_at=datetime.now(UTC),
                assignee_agent_id=agent.id,
            )
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="failed",
                error_code="process_lost",
                finished_at=datetime.now(UTC),
                context_snapshot={"issueId": issue.id},
            )
            session.add(run)
            await session.flush()

            await HeartbeatService(session)._reconcile_failed_done_issue(agent, run)
            await session.refresh(issue)
            activity = (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.action == "issue.done_missing_work_product"
                    )
                )
            ).scalar_one()

            assert issue.status == "blocked"
            assert issue.completed_at is None
            assert activity.entity_id == issue.id
            assert activity.details["reason"] == "done_without_expected_work_product"
    finally:
        await engine.dispose()


async def test_parent_children_settled_with_blocked_child_blocks_parent() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-settled-blocks-parent",
                name="Step 15 Settled Blocks Parent",
                issue_prefix="SBP",
            )
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
            session.add(agent)
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="四海报告",
                status="in_progress",
                assignee_agent_id=agent.id,
            )
            session.add(parent)
            await session.flush()
            blocked_child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="东海介绍",
                status="blocked",
            )
            done_child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="北海介绍",
                status="done",
                completed_at=datetime.now(UTC),
            )
            session.add_all([blocked_child, done_child])
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                context_snapshot={
                    "issueId": parent.id,
                    "wakeReason": "issue_children_settled",
                },
            )
            session.add(run)
            await session.flush()
            session.add(
                ActivityLog(
                    org_id=org.id,
                    actor_type="agent",
                    actor_id=agent.id,
                    action="issue.comment_added",
                    entity_type="issue",
                    entity_id=parent.id,
                    run_id=run.id,
                    details={"body": "进度更新：部分子任务 blocked"},
                )
            )
            await session.flush()

            final = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(agent, run)
            await session.refresh(parent)
            activity = (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.action == "issue.parent_blocked_child_unresolved"
                    )
                )
            ).scalar_one()

            assert final.status == "succeeded"
            assert parent.status == "blocked"
            assert (
                activity.details["reason"] == "parent_blocked_due_to_blocked_children"
            )
            assert activity.details["childIssues"][0]["title"] == "东海介绍"
            assert "retry_child" in activity.details["nextActions"]
    finally:
        await engine.dispose()


async def test_accepted_cancelled_child_does_not_fail_parent_closeout() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-accepted-cancelled-child",
                name="Step 15 Accepted Cancelled Child",
                issue_prefix="ACC",
            )
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
            session.add(agent)
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="父任务",
                status="done",
                assignee_agent_id=agent.id,
                completed_at=datetime.now(UTC),
            )
            session.add(parent)
            await session.flush()
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="用户取消的子任务",
                status="cancelled",
                assignee_agent_id=agent.id,
                cancelled_at=datetime.now(UTC),
            )
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                context_snapshot={
                    "issueId": parent.id,
                    "wakeReason": "issue_children_settled",
                },
            )
            session.add_all([child, run])
            await session.flush()
            parent_product = IssueWorkProduct(
                org_id=org.id,
                issue_id=parent.id,
                title="reports/final.md",
                type="file",
                provider="local",
                status="ready",
                summary="父任务最终报告",
                is_primary=True,
                created_by_run_id=run.id,
                created_at=datetime.now(UTC),
            )
            session.add(parent_product)
            await session.flush()
            await insert_activity_log(
                session,
                org_id=org.id,
                actor_type="user",
                actor_id="local-board",
                action="issue.incomplete_accepted",
                entity_type="issue",
                entity_id=parent.id,
                details={
                    "reason": "用户确认取消该子任务，不影响父任务交付",
                    "childIssueId": child.id,
                    "childIssueIds": [child.id],
                },
            )

            final = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(agent, run)

            await session.refresh(parent)
            assert final.status == "succeeded"
            assert parent.status == "done"
    finally:
        await engine.dispose()


async def test_parent_done_with_blocked_child_is_closeout_failure() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-parent-blocked-child",
                name="Step 15 Parent Blocked Child",
                issue_prefix="PBC",
            )
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
            session.add(agent)
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="五湖报告",
                status="done",
                assignee_agent_id=agent.id,
            )
            session.add(parent)
            await session.flush()
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="太湖介绍",
                status="blocked",
                assignee_agent_id=agent.id,
            )
            session.add(child)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                context_snapshot={
                    "issueId": parent.id,
                    "wakeReason": "issue_children_settled",
                },
            )
            session.add(run)
            await session.flush()

            final = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(agent, run)
            activity = (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.action == "issue.parent_blocked_child_unresolved"
                    )
                )
            ).scalar_one()

            await session.refresh(parent)
            assert final.status == "failed"
            assert final.error_code == "closeout_missing"
            assert parent.status == "blocked"
            assert parent.completed_at is None
            assert activity.entity_id == parent.id
            assert activity.details["reason"] == "parent_done_with_blocked_children"
            assert activity.details["childIssues"][0]["title"] == "太湖介绍"
    finally:
        await engine.dispose()


async def test_parent_primary_work_product_satisfies_child_output_evidence() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-parent-primary-evidence",
                name="Step 15 Parent Primary Evidence",
                issue_prefix="PCE",
            )
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
            session.add(agent)
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Four beauties report",
                status="done",
                assignee_agent_id=agent.id,
            )
            session.add(parent)
            await session.flush()
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Xi Shi report",
                status="done",
                completed_at=datetime.now(UTC) - timedelta(minutes=5),
            )
            session.add(child)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                context_snapshot={"issueId": parent.id},
            )
            session.add(run)
            await session.flush()
            session.add(
                IssueWorkProduct(
                    org_id=org.id,
                    issue_id=parent.id,
                    type="document",
                    provider="local_file",
                    title="four-beauties.md",
                    status="ready",
                    is_primary=True,
                    created_by_run_id=run.id,
                )
            )
            await session.flush()

            final = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(agent, run)
            warnings = (
                (
                    await session.execute(
                        select(ActivityLog).where(
                            ActivityLog.action
                            == "issue.parent_deliverable_convergence_warning"
                        )
                    )
                )
                .scalars()
                .all()
            )

            assert final.status == "succeeded"
            assert warnings == []
    finally:
        await engine.dispose()


async def test_parent_can_resubmit_existing_primary_work_product_for_closeout() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-parent-resubmits-primary",
                name="Step 15 Parent Resubmits Primary",
                issue_prefix="PRP",
            )
            session.add(org)
            await session.flush()
            agent = Agent(org_id=org.id, name="Parent Agent")
            session.add(agent)
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Four mountains report",
                status="done",
                assignee_agent_id=agent.id,
            )
            session.add(parent)
            await session.flush()
            product = IssueWorkProduct(
                org_id=org.id,
                issue_id=parent.id,
                type="document",
                provider="octopus",
                title="reports/four-mountains.md",
                status="active",
                is_primary=True,
                created_at=datetime.now(UTC) - timedelta(hours=1),
            )
            origin_run_id = str(uuid.uuid4())
            policy = {
                "version": 1,
                "mode": "parent_output_required",
                "requirements": {
                    "minimumOutputs": 1,
                    "primaryOutputRequired": True,
                },
            }
            child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Jiuhua Mountain food guide",
                status="done",
                origin_kind="delegation",
                origin_run_id=origin_run_id,
                closeout_policy=policy,
                completed_at=datetime.now(UTC) - timedelta(minutes=1),
            )
            session.add_all([product, child])
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id=agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                context_snapshot={
                    "issueId": parent.id,
                    "delegationOriginRunId": origin_run_id,
                    "closeoutPolicy": policy,
                },
            )
            session.add(run)
            await session.flush()
            session.add(
                ActivityLog(
                    org_id=org.id,
                    actor_type="agent",
                    actor_id=agent.id,
                    action="issue.closeout_requested",
                    entity_type="issue",
                    entity_id=parent.id,
                    run_id=run.id,
                    details={
                        "version": 1,
                        "delegationOriginRunId": origin_run_id,
                        "declaredWorkProducts": [
                            {
                                "path": "reports\\four-mountains.md",
                                "isPrimary": True,
                            }
                        ],
                    },
                )
            )
            await session.flush()

            final = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(agent, run)
            warnings = (
                (
                    await session.execute(
                        select(ActivityLog).where(
                            ActivityLog.action
                            == "issue.parent_deliverable_convergence_warning"
                        )
                    )
                )
                .scalars()
                .all()
            )

            assert final.status == "succeeded"
            assert warnings == []
            await session.refresh(parent)
            assert parent.status == "done"
    finally:
        await engine.dispose()


async def test_child_outputs_policy_requires_parent_continuation() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-child-outputs-closeout",
                name="Step 15 Child Outputs Closeout",
                issue_prefix="COC",
            )
            session.add(org)
            await session.flush()
            parent_agent = Agent(org_id=org.id, name="Parent Agent")
            child_agent = Agent(org_id=org.id, name="Child Agent")
            session.add_all([parent_agent, child_agent])
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="Four travel guides",
                status="in_progress",
                assignee_agent_id=parent_agent.id,
            )
            session.add(parent)
            await session.flush()
            batch_run_id = str(uuid.uuid4())
            children = [
                Issue(
                    org_id=org.id,
                    parent_id=parent.id,
                    title=title,
                    status="done",
                    assignee_agent_id=child_agent.id,
                    origin_kind="delegation",
                    origin_run_id=batch_run_id,
                    closeout_policy={
                        "version": 1,
                        "mode": "child_outputs_are_final",
                    },
                    completed_at=datetime.now(UTC),
                )
                for title in ("Lushan guide", "Huangshan guide")
            ]
            unrelated_old_child = Issue(
                org_id=org.id,
                parent_id=parent.id,
                title="Old batch without output",
                status="done",
                origin_kind="delegation",
                origin_run_id=str(uuid.uuid4()),
                closeout_policy={
                    "version": 1,
                    "mode": "parent_output_required",
                    "requirements": {
                        "minimumOutputs": 1,
                        "primaryOutputRequired": True,
                    },
                },
                completed_at=datetime.now(UTC),
            )
            session.add_all([*children, unrelated_old_child])
            await session.flush()
            for child in children:
                session.add(
                    IssueWorkProduct(
                        org_id=org.id,
                        issue_id=child.id,
                        type="document",
                        provider="octopus",
                        title=f"reports/{child.id}.md",
                        status="ready",
                        is_primary=True,
                    )
                )
            child_run = HeartbeatRun(
                org_id=org.id,
                agent_id=child_agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={"issueId": children[-1].id},
            )
            session.add(child_run)
            await session.flush()

            await HeartbeatService(session)._wake_parent_after_child_settled(
                child_run, children[-1]
            )
            continuation = (
                await session.execute(
                    select(HeartbeatRun).where(
                        HeartbeatRun.agent_id == parent_agent.id,
                        HeartbeatRun.status == "queued",
                    )
                )
            ).scalar_one_or_none()
            await session.refresh(parent)
            settled = (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.entity_id == parent.id,
                        ActivityLog.action == "issue.children_settled",
                    )
                )
            ).scalar_one()

            assert continuation is not None
            assert continuation.agent_id == parent_agent.id
            assert continuation.context_snapshot["wakeReason"] == (
                "issue_children_settled"
            )
            assert continuation.context_snapshot["delegationOriginRunId"] == (
                batch_run_id
            )
            assert continuation.context_snapshot["closeoutPolicy"] == {
                "version": 1,
                "mode": "child_outputs_are_final",
            }
            assert parent.status == "in_progress"
            assert settled.details["delegationOriginRunId"] == batch_run_id
    finally:
        await engine.dispose()


async def test_four_beauties_parent_child_delivery_acceptance() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-four-beauties",
                name="Step 15 Four Beauties",
                issue_prefix="FB",
            )
            session.add(org)
            await session.flush()
            parent_agent = Agent(org_id=org.id, name="Parent Agent")
            child_agent = Agent(org_id=org.id, name="Child Agent")
            session.add_all([parent_agent, child_agent])
            await session.flush()
            parent = Issue(
                org_id=org.id,
                title="四大美女报告",
                status="in_progress",
                assignee_agent_id=parent_agent.id,
            )
            session.add(parent)
            await session.flush()
            child_titles = ["西施介绍", "王昭君介绍", "貂蝉介绍", "杨贵妃介绍"]
            children: list[Issue] = []
            for title in child_titles:
                child = Issue(
                    org_id=org.id,
                    parent_id=parent.id,
                    title=title,
                    status="done",
                    assignee_agent_id=child_agent.id,
                    completed_at=datetime.now(UTC) - timedelta(minutes=5),
                )
                children.append(child)
                session.add(child)
            await session.flush()
            for child in children:
                session.add(
                    IssueWorkProduct(
                        org_id=org.id,
                        issue_id=child.id,
                        type="document",
                        provider="octopus",
                        title=f"reports/four-beauties/{child.title}.md",
                        status="ready",
                        is_primary=True,
                        summary=child.title,
                    )
                )
                session.add(
                    ActivityLog(
                        org_id=org.id,
                        actor_type="agent",
                        actor_id=child_agent.id,
                        action="issue.updated",
                        entity_type="issue",
                        entity_id=child.id,
                        details={"status": "done", "comment": f"完成{child.title}"},
                    )
                )
            await session.flush()
            child_run = HeartbeatRun(
                org_id=org.id,
                agent_id=child_agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                context_snapshot={"issueId": children[-1].id},
            )
            session.add(child_run)
            await session.flush()

            await HeartbeatService(session)._wake_parent_after_child_settled(
                child_run, children[-1]
            )
            outputs = await IssueService(session).get_child_outputs(
                parent.id, include_work_products=True
            )

            assert outputs is not None
            assert outputs["totalChildCount"] == 4
            assert outputs["activeChildCount"] == 0
            assert outputs["settledChildCount"] == 4
            assert {child["title"] for child in outputs["children"]} == set(
                child_titles
            )
            assert all(child["workProducts"] for child in outputs["children"])
            continuation = (
                await session.execute(
                    select(HeartbeatRun).where(
                        HeartbeatRun.agent_id == parent_agent.id,
                        HeartbeatRun.status == "queued",
                    )
                )
            ).scalar_one()
            assert (
                continuation.context_snapshot["wakeReason"] == "issue_children_settled"
            )
            activity = (
                await session.execute(
                    select(ActivityLog).where(
                        ActivityLog.entity_id == parent.id,
                        ActivityLog.action == "issue.children_settled",
                    )
                )
            ).scalar_one()
            assert activity.details["completedChildIssueId"] == children[-1].id

            parent.status = "done"
            parent.completed_at = datetime.now(UTC)
            parent_run = HeartbeatRun(
                org_id=org.id,
                agent_id=parent_agent.id,
                invocation_source="assignment",
                trigger_detail="system",
                status="succeeded",
                finished_at=datetime.now(UTC),
                context_snapshot={
                    "issueId": parent.id,
                    "wakeReason": "issue_children_settled",
                },
            )
            session.add(parent_run)
            await session.flush()
            session.add(
                IssueWorkProduct(
                    org_id=org.id,
                    issue_id=parent.id,
                    type="document",
                    provider="octopus",
                    title="reports/four-beauties.md",
                    status="ready",
                    is_primary=True,
                    summary="四大美女最终汇总报告",
                    created_by_run_id=parent_run.id,
                )
            )
            await session.flush()

            final = await HeartbeatService(
                session
            )._enforce_closeout_governance_success(parent_agent, parent_run)
            warnings = (
                (
                    await session.execute(
                        select(ActivityLog).where(
                            ActivityLog.action
                            == "issue.parent_deliverable_convergence_warning"
                        )
                    )
                )
                .scalars()
                .all()
            )
            detail = await IssueService(session).get_by_id(parent.id)

            assert final.status == "succeeded"
            assert warnings == []
            assert detail is not None
            assert detail["workProducts"][0]["title"] == "reports/four-beauties.md"
            assert detail["workProducts"][0]["issueId"] == parent.id
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
                {"name": "Archive Running Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
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
                {"name": "Archive Dirty Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
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
    tmp_path: Path, monkeypatch
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
    project_cwd = tmp_path / "service-primary"
    project_cwd.mkdir()
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
                {"name": "Runtime Service Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": str(project_cwd)},
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
    tmp_path: Path,
    monkeypatch,
) -> None:
    issue_ref: dict[str, str] = {}

    class FileWritingAdapter:
        type = "process"

        async def execute(self, context):
            workspace = context.config.get("cwd")
            assert isinstance(workspace, str)
            issue_artifacts_env = (context.env or {}).get("OCTOPUS_ISSUE_ARTIFACTS_DIR")
            assert isinstance(issue_artifacts_env, str)
            issue_artifacts = Path(issue_artifacts_env)
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
            shared_report = Path(workspace) / "reports" / "four-beauties.md"
            shared_report.parent.mkdir(parents=True, exist_ok=True)
            shared_report.write_text(
                "# Four Beauties\n\nShared report.\n", encoding="utf-8"
            )
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
                {"name": "Generated File Project"},
                actor_type="user",
                actor_id="dev",
            )
            project_cwd = tmp_path / "generated-primary"
            project_cwd.mkdir()
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": str(project_cwd)},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Generate summary files",
                description=(
                    "Expected shared deliverables: analysis-plan.md and "
                    "reports/four-beauties.md"
                ),
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
        "analysis-plan.md",
        "reports/four-beauties.md",
    }
    assert all(not title.startswith("agents/") for title in titles)
    assert all(product["contentPath"] for product in result_json["workProducts"])
    assert detail is not None
    detail_titles = {product["title"] for product in detail["workProducts"]}
    assert detail_titles == {
        "CLAUDE_SUMMARY.md",
        "python-demo/README.md",
        "analysis-plan.md",
        "reports/four-beauties.md",
    }
    metadata_by_title = {
        product["title"]: product["metadata"] for product in detail["workProducts"]
    }
    assert metadata_by_title["CLAUDE_SUMMARY.md"] is not None
    assert metadata_by_title["CLAUDE_SUMMARY.md"]["source"] == ("issue_artifacts_scan")
    nested_metadata = metadata_by_title["python-demo/README.md"]
    assert isinstance(nested_metadata, dict)
    assert nested_metadata["source"] == "issue_artifacts_scan"
    org_artifact_metadata = metadata_by_title["analysis-plan.md"]
    assert isinstance(org_artifact_metadata, dict)
    assert org_artifact_metadata["source"] == "organization_artifacts_scan"
    shared_metadata = metadata_by_title["reports/four-beauties.md"]
    assert isinstance(shared_metadata, dict)
    assert shared_metadata["source"] == "shared_workspace_scan"
    assert shared_metadata["workspacePath"] == "reports/four-beauties.md"


async def test_run_preflight_and_adapter_execution_record_workspace_operations(
    tmp_path: Path, monkeypatch
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

    project_cwd = tmp_path / "ops-primary"
    project_cwd.mkdir()
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
                {"name": "Workspace Operations"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": str(project_cwd)},
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


async def test_cancel_running_run_marks_workspace_resources_terminal(
    tmp_path: Path,
) -> None:
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
                {"name": "Cancel Cleanup"},
                actor_type="user",
                actor_id="dev",
            )
            project_cwd = tmp_path / "cancel-cleanup"
            project_cwd.mkdir()
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": str(project_cwd)},
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
                    "workspace": {"octopusWorkspace": workspace},
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


async def test_orphaned_running_run_marks_workspace_resources_terminal(
    tmp_path: Path,
) -> None:
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
                {"name": "Recovery Cleanup"},
                actor_type="user",
                actor_id="dev",
            )
            project_cwd = tmp_path / "recovery-cleanup"
            project_cwd.mkdir()
            await project_service.create_workspace(
                project["id"],
                {"name": "Primary", "cwd": str(project_cwd)},
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
                    "workspace": {"octopusWorkspace": workspace},
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


async def test_project_without_workspace_uses_organization_scratch() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-isolated-no-project-workspace",
                name="Step 15 Isolated No Project Workspace",
                issue_prefix="INW",
            )
            session.add(org)
            await session.flush()
            project = await ProjectService(session).create_project(
                org.id,
                {"name": "No Workspace"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Needs git source",
            )
            session.add(issue)
            await session.flush()

            workspace = await WorkspaceService(session).resolve_for_issue(issue)
            assert workspace is not None
            metadata = workspace["metadata"]
            assert metadata is not None
            assert metadata["workspaceKind"] == "organization_scratch"
            assert metadata["resolvedMode"] == "organization_scratch"
            assert workspace["mode"] == "organization_scratch"
            assert workspace["projectWorkspaceId"] is None
    finally:
        await engine.dispose()


async def test_project_without_workspace_does_not_resolve_operator_mode() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-operator-no-project-workspace",
                name="Step 15 Operator No Project Workspace",
                issue_prefix="ONW",
            )
            session.add(org)
            await session.flush()
            project = await ProjectService(session).create_project(
                org.id,
                {"name": "Operator No Workspace"},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Operator needs git source",
            )
            session.add(issue)
            await session.flush()

            workspace = await WorkspaceService(session).resolve_for_issue(issue)
            assert workspace is not None
            metadata = workspace["metadata"]
            assert metadata is not None
            assert metadata["workspaceKind"] == "organization_scratch"
            assert metadata["resolvedMode"] == "organization_scratch"
            assert workspace["mode"] == "organization_scratch"
    finally:
        await engine.dispose()


async def test_isolated_workspace_rejects_non_git_project_cwd(
    tmp_path: Path,
) -> None:
    project_cwd = tmp_path / "plain-directory"
    project_cwd.mkdir()
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-isolated-non-git",
                name="Step 15 Isolated Non Git",
                issue_prefix="ING",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Isolated Non Git"},
                actor_type="user",
                actor_id="dev",
            )
            project_workspace = await project_service.create_workspace(
                project["id"],
                {
                    "name": "Plain Directory",
                    "cwd": str(project_cwd),
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            assert project_workspace is not None
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                project_workspace_id=project_workspace["id"],
                title="Reject non Git isolated source",
            )
            session.add(issue)
            await session.flush()

            with pytest.raises(
                ValueError,
                match="existing Git repository",
            ):
                await WorkspaceService(session).resolve_for_issue(issue)
    finally:
        await engine.dispose()

    assert not (project_cwd / ".octopus" / "worktrees").exists()


async def test_isolated_workspace_without_cwd_or_repo_fails_preflight() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-isolated-empty-cwd",
                name="Step 15 Isolated Empty Cwd",
                issue_prefix="IEC",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Isolated Empty Cwd"},
                actor_type="user",
                actor_id="dev",
            )
            project_workspace = await project_service.create_workspace(
                project["id"],
                {
                    "name": "No Cwd",
                    "cwd": None,
                    "repoUrl": None,
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "isolated_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            assert project_workspace is not None
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                project_workspace_id=project_workspace["id"],
                title="Needs git source",
            )
            session.add(issue)
            await session.flush()

            with pytest.raises(
                ValueError,
                match="requires a local cwd or repo URL",
            ):
                await WorkspaceService(session).resolve_for_issue(issue)
    finally:
        await engine.dispose()


async def test_operator_branch_without_cwd_or_repo_fails_preflight() -> None:
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-operator-empty-cwd",
                name="Step 15 Operator Empty Cwd",
                issue_prefix="OEC",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Operator Empty Cwd"},
                actor_type="user",
                actor_id="dev",
            )
            project_workspace = await project_service.create_workspace(
                project["id"],
                {
                    "name": "No Cwd",
                    "cwd": None,
                    "repoUrl": None,
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "operator_branch",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            assert project_workspace is not None
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                project_workspace_id=project_workspace["id"],
                title="Operator needs cwd",
            )
            session.add(issue)
            await session.flush()

            with pytest.raises(ValueError, match="requires a local cwd or repo URL"):
                await WorkspaceService(session).resolve_for_issue(issue)
    finally:
        await engine.dispose()


async def test_configured_missing_project_workspace_cwd_fails_preflight(
    tmp_path: Path,
) -> None:
    missing_cwd = tmp_path / "missing-project"
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-missing-cwd",
                name="Step 15 Missing Cwd",
                issue_prefix="MCW",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Missing Cwd Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {"name": "Missing", "cwd": str(missing_cwd)},
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Missing cwd should fail",
            )
            session.add(issue)
            await session.flush()

            with pytest.raises(ValueError, match="does not exist"):
                await WorkspaceService(session).resolve_for_issue(issue)
    finally:
        await engine.dispose()


async def test_projectless_workspace_fallback_has_no_workspace_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
                url_key="step15-projectless-no-lease",
                name="Step 15 Projectless No Lease",
                issue_prefix="PNL",
            )
            session.add(org)
            await session.flush()
            issue = Issue(org_id=org.id, title="Projectless no lease")
            session.add(issue)
            await session.flush()
            run = HeartbeatRun(
                org_id=org.id,
                agent_id="agent-projectless-no-lease",
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
            assert context is not None
            workspace = context["workspace"]["octopusWorkspace"]
            assert workspace["id"] is None
            assert "leaseKey" not in workspace
            service = WorkspaceService(session)
            first = await service.begin_operation(
                org_id=org.id,
                run_id="run-one",
                execution_workspace_id=None,
                phase="workspace_provision",
                command="runtime_adapter.execute",
                cwd=workspace["cwd"],
                metadata={"adapterExecution": True},
            )
            second = await service.begin_operation(
                org_id=org.id,
                run_id="run-two",
                execution_workspace_id=None,
                phase="workspace_provision",
                command="runtime_adapter.execute",
                cwd=workspace["cwd"],
                metadata={"adapterExecution": True},
            )
            assert first["status"] == "running"
            assert second["status"] == "running"
    finally:
        await engine.dispose()


async def test_workspace_commit_requires_user_approval_and_records_work_product(
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
                url_key="step15-user-approved-commit",
                name="User Approved Commit",
                issue_prefix="UAC",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Commit Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "shared_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Commit workspace changes",
            )
            session.add(issue)
            await session.flush()
            service = WorkspaceService(session)
            workspace = await service.resolve_for_issue(issue)
            assert workspace is not None
            project_cwd.joinpath("hello.py").write_text(
                "print('hello')\n", encoding="utf-8"
            )
            project_cwd.joinpath(".venv").mkdir()
            project_cwd.joinpath(".venv", "local.py").write_text(
                "local cache\n", encoding="utf-8"
            )
            listed_for_issue = await service.list_execution_workspaces(
                org.id, issue_id=issue.id
            )
            with pytest.raises(ValueError, match="explicit user approval"):
                await service.commit_workspace_changes(
                    workspace["id"], message="Add hello script", approved=False
                )
            result = await service.commit_workspace_changes(
                workspace["id"], message="Add hello script", approved=True
            )
            products = await service.list_work_products_for_issue(issue.id)
            await session.commit()
    finally:
        await engine.dispose()

    assert result is not None
    assert result["committed"] is True
    assert result["commit"]
    assert result["message"] == "Add hello script"
    assert [workspace["id"] for workspace in listed_for_issue] == [workspace["id"]]
    status_lines = _git(project_cwd, "status", "--porcelain").stdout.splitlines()
    assert status_lines == ["?? .venv/"]
    assert _git(
        project_cwd, "ls-tree", "-r", "--name-only", "HEAD"
    ).stdout.splitlines() == [
        "README.md",
        "hello.py",
    ]
    assert (
        _git(project_cwd, "log", "--oneline", "-1")
        .stdout.strip()
        .endswith("Add hello script")
    )
    assert len(products) == 1
    assert products[0]["type"] == "commit"
    assert products[0]["externalId"] == result["commit"]
    assert products[0]["reviewState"] == "approved"


async def test_repo_url_configured_empty_shared_cwd_is_cloned_before_run(
    tmp_path: Path,
) -> None:
    remote_repo = tmp_path / "remote-repo"
    _init_repo_with_branch(remote_repo, "main")
    shared_cwd = tmp_path / "shared-empty"
    shared_cwd.mkdir()
    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-empty-cwd-clone",
                name="Empty Cwd Clone",
                issue_prefix="ECC",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Clone Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(shared_cwd),
                    "repoUrl": str(remote_repo),
                    "defaultRef": "main",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "shared_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(
                org_id=org.id,
                project_id=project["id"],
                title="Clone configured shared cwd",
            )
            session.add(issue)
            await session.flush()
            context = await WorkspaceService(session).prepare_runtime_context_for_run(
                "run-clone", {"issueId": issue.id}
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert context is not None
    workspace = context["workspace"]["octopusWorkspace"]
    assert workspace["cwd"] == str(shared_cwd)
    assert (
        _git(shared_cwd, "rev-parse", "--is-inside-work-tree").stdout.strip() == "true"
    )
    assert (
        shared_cwd.joinpath("README.md").read_text(encoding="utf-8") == "# Test repo\n"
    )


async def test_execution_workspace_push_uses_one_time_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_cwd = tmp_path / "project-repo"
    _init_repo_with_branch(project_cwd, "main")
    captured: dict[str, Any] = {}
    real_run = subprocess.run

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        command = args[0]
        if (
            isinstance(command, list)
            and command[:3] == ["git", "-C", str(project_cwd)]
            and command[3:] == ["push", "--set-upstream", "origin", "main"]
        ):
            captured["env"] = kwargs.get("env")
            captured["command"] = command
            return subprocess.CompletedProcess(command, 0, "pushed\n", "")
        return real_run(*args, **kwargs)

    engine = create_database_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker = create_session_factory(engine)
    try:
        async with factory() as session:
            org = Organization(
                url_key="step15-push-creds",
                name="Push Creds",
                issue_prefix="PCD",
            )
            session.add(org)
            await session.flush()
            project_service = ProjectService(session)
            project = await project_service.create_project(
                org.id,
                {"name": "Push Creds Project"},
                actor_type="user",
                actor_id="dev",
            )
            await project_service.create_workspace(
                project["id"],
                {
                    "name": "Primary",
                    "cwd": str(project_cwd),
                    "defaultRef": "main",
                    "executionWorkspacePolicy": {
                        "enabled": True,
                        "defaultMode": "shared_workspace",
                    },
                },
                actor_type="user",
                actor_id="dev",
            )
            issue = Issue(org_id=org.id, project_id=project["id"], title="Push")
            session.add(issue)
            await session.flush()
            service = WorkspaceService(session)
            workspace = await service.resolve_for_issue(issue)
            assert workspace is not None
            monkeypatch.setattr("server.services.workspaces.subprocess.run", fake_run)
            pushed = await service.push_workspace_branch(
                workspace["id"], username="alice", password="token-secret"
            )
            await session.commit()
    finally:
        await engine.dispose()

    assert pushed is not None
    assert pushed["pushed"] is True
    assert pushed["branch"] == "main"
    assert captured["env"]["OCTOPUS_GIT_USERNAME"] == "alice"
    assert captured["env"]["OCTOPUS_GIT_PASSWORD"] == "token-secret"
    assert captured["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert "token-secret" not in str(pushed)
