from __future__ import annotations

import json
import mimetypes
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.projects import get_project_by_id
from packages.database.queries.workspaces import (
    create_execution_workspace,
    create_issue_work_product,
    create_workspace_operation,
    create_workspace_runtime_service,
    delete_issue_work_product,
    get_execution_workspace_by_id,
    get_issue_work_product,
    get_workspace_operation,
    list_execution_workspaces,
    list_issue_work_products,
    list_project_workspaces,
    list_running_workspace_operations_for_run,
    list_workspace_operations_for_run,
    list_workspace_runtime_services_for_workspace,
    update_execution_workspace,
    update_issue_work_product,
    update_workspace_operation,
    update_workspace_runtime_service,
)
from packages.database.queries.assets import create_asset
from packages.database.schema import (
    ExecutionWorkspace,
    Issue,
    IssueWorkProduct,
    WorkspaceOperation,
    WorkspaceRuntimeService,
)
from packages.shared.constants.workspace import (
    ExecutionWorkspaceMode,
    ExecutionWorkspaceStatus,
    ExecutionWorkspaceStrategyType,
)
from packages.shared.types.workspace import ExecutionWorkspace as ExecutionWorkspaceData
from packages.shared.types.workspace import IssueWorkProduct as IssueWorkProductData
from server.storage import get_storage_service
from packages.shared.types.workspace import WorkspaceOperation as WorkspaceOperationData
from packages.shared.types.workspace import (
    WorkspaceRuntimeService as RuntimeServiceData,
)

from .logs import (
    LogReadResult,
    append_local_file_log,
    finalize_local_file_log,
    read_local_file_log,
)
from . import workspace_paths as workspace_paths_module
from .workspace_paths import (
    ensure_organization_workspace_root,
    organization_workspace_root,
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _operation_log_dir() -> Path:
    return Path(
        os.getenv(
            "OCTOPUS_WORKSPACE_OPERATION_LOG_DIR",
            ".octopus/workspace-operation-logs",
        )
    )


def _database_log_fields(fields: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "logBytes" in fields:
        result["log_bytes"] = fields["logBytes"]
    if "logSha256" in fields:
        result["log_sha256"] = fields["logSha256"]
    if "logCompressed" in fields:
        result["log_compressed"] = fields["logCompressed"]
    return result


_WORK_PRODUCT_UPDATE_COLUMNS = {
    "projectId": "project_id",
    "executionWorkspaceId": "execution_workspace_id",
    "runtimeServiceId": "runtime_service_id",
    "type": "type",
    "provider": "provider",
    "externalId": "external_id",
    "title": "title",
    "url": "url",
    "status": "status",
    "reviewState": "review_state",
    "isPrimary": "is_primary",
    "healthStatus": "health_status",
    "summary": "summary",
    "metadata": "metadata_json",
    "createdByRunId": "created_by_run_id",
}

_GENERATED_FILE_EXTENSIONS = {
    ".csv",
    ".htm",
    ".html",
    ".json",
    ".log",
    ".md",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
_GENERATED_FILE_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".octopus",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}
_GENERATED_FILE_MAX_BYTES = 1_000_000
_GENERATED_FILE_MAX_COUNT = 20


@dataclass(frozen=True)
class _IssueWorkspaceFallback:
    org_id: str
    id: str


def _aware_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _iter_generated_workspace_files(root: Path, since: datetime | None) -> list[Path]:
    candidates: list[tuple[datetime, Path]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part in _GENERATED_FILE_EXCLUDED_PARTS for part in rel_parts):
            continue
        if path.suffix.lower() not in _GENERATED_FILE_EXTENSIONS:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if stat.st_size <= 0 or stat.st_size > _GENERATED_FILE_MAX_BYTES:
            continue
        modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
        if since is not None and modified_at < since:
            continue
        candidates.append((modified_at, path))
    candidates.sort(key=lambda item: (item[0], item[1].as_posix()))
    return [path for _, path in candidates[:_GENERATED_FILE_MAX_COUNT]]


def _parse_project_policy(value: Any) -> dict[str, Any] | None:
    parsed = _as_record(value)
    if not parsed:
        return None
    default_mode = parsed.get("defaultMode")
    if default_mode == "project_primary":
        default_mode = "shared_workspace"
    if default_mode == "isolated":
        default_mode = "isolated_workspace"
    return {
        "enabled": bool(parsed.get("enabled")),
        **({"defaultMode": default_mode} if isinstance(default_mode, str) else {}),
        **(
            {"allowIssueOverride": parsed["allowIssueOverride"]}
            if isinstance(parsed.get("allowIssueOverride"), bool)
            else {}
        ),
        **(
            {"defaultProjectWorkspaceId": parsed["defaultProjectWorkspaceId"]}
            if isinstance(parsed.get("defaultProjectWorkspaceId"), str)
            else {}
        ),
        **(
            {"workspaceStrategy": parsed["workspaceStrategy"]}
            if isinstance(parsed.get("workspaceStrategy"), dict)
            else {}
        ),
    }


def _parse_issue_settings(value: Any) -> dict[str, Any] | None:
    parsed = _as_record(value)
    if not parsed:
        return None
    mode = parsed.get("mode")
    if mode == "project_primary":
        mode = "shared_workspace"
    if mode == "isolated":
        mode = "isolated_workspace"
    result: dict[str, Any] = {}
    if isinstance(mode, str):
        result["mode"] = mode
    if isinstance(parsed.get("workspaceStrategy"), dict):
        result["workspaceStrategy"] = parsed["workspaceStrategy"]
    if isinstance(parsed.get("workspaceRuntime"), dict):
        result["workspaceRuntime"] = parsed["workspaceRuntime"]
    return result or None


def _resolve_mode(
    *,
    project_policy: dict[str, Any] | None,
    issue_settings: dict[str, Any] | None,
    issue_preference: str | None,
) -> str:
    issue_mode = issue_settings.get("mode") if issue_settings else None
    if isinstance(issue_preference, str) and issue_preference:
        issue_mode = issue_preference
    if issue_mode and issue_mode not in {"inherit", "reuse_existing"}:
        return str(issue_mode)
    if project_policy and project_policy.get("enabled"):
        default_mode = project_policy.get("defaultMode")
        if default_mode == "isolated_workspace":
            return "isolated_workspace"
        if default_mode == "operator_branch":
            return "operator_branch"
        if default_mode == "adapter_default":
            return "agent_default"
        return "shared_workspace"
    return "shared_workspace"


def _resolve_strategy_type(
    *,
    project_policy: dict[str, Any] | None,
    issue_settings: dict[str, Any] | None,
    mode: str,
) -> str:
    strategy = None
    if issue_settings and isinstance(issue_settings.get("workspaceStrategy"), dict):
        strategy = issue_settings["workspaceStrategy"]
    elif project_policy and isinstance(project_policy.get("workspaceStrategy"), dict):
        strategy = project_policy["workspaceStrategy"]
    strategy_type = strategy.get("type") if isinstance(strategy, dict) else None
    if isinstance(strategy_type, str) and strategy_type:
        return strategy_type
    if mode in {"isolated_workspace", "operator_branch"}:
        return "git_worktree"
    if mode == "agent_default":
        return "adapter_managed"
    return "project_primary"


class WorkspaceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_execution_workspaces(
        self,
        org_id: str,
        *,
        project_id: str | None = None,
        project_workspace_id: str | None = None,
        issue_id: str | None = None,
        status: str | None = None,
        reuse_eligible: bool = False,
    ) -> list[ExecutionWorkspaceData]:
        rows = await list_execution_workspaces(
            self._session,
            org_id,
            project_id=project_id,
            project_workspace_id=project_workspace_id,
            issue_id=issue_id,
            status=status,
            reuse_eligible=reuse_eligible,
        )
        return [self._to_execution_workspace(row) for row in rows]

    async def get_execution_workspace(
        self, workspace_id: str
    ) -> ExecutionWorkspaceData | None:
        row = await get_execution_workspace_by_id(self._session, workspace_id)
        return self._to_execution_workspace(row) if row is not None else None

    async def update_execution_workspace(
        self, workspace_id: str, fields: dict[str, Any]
    ) -> ExecutionWorkspaceData | None:
        values = {
            "status": fields["status"] if "status" in fields else None,
            "cleanup_eligible_at": _parse_datetime(fields.get("cleanupEligibleAt"))
            if "cleanupEligibleAt" in fields
            else None,
            "cleanup_reason": fields.get("cleanupReason")
            if "cleanupReason" in fields
            else None,
            "metadata_json": fields.get("metadata") if "metadata" in fields else None,
        }
        patch = {key: value for key, value in values.items() if key in values}
        row = await update_execution_workspace(self._session, workspace_id, patch)
        return self._to_execution_workspace(row) if row is not None else None

    async def resolve_for_issue(self, issue: Issue) -> ExecutionWorkspaceData | None:
        if issue.execution_workspace_id:
            existing = await get_execution_workspace_by_id(
                self._session, issue.execution_workspace_id
            )
            if existing is not None and existing.org_id == issue.org_id:
                touched = await update_execution_workspace(
                    self._session,
                    existing.id,
                    {"last_used_at": datetime.now(UTC)},
                )
                return self._to_execution_workspace(touched or existing)
        if issue.project_id is None:
            org_root = self._org_workspace_root(issue.org_id)
            return self._organization_workspace_fallback(
                issue,
                cwd=str(org_root),
                warning=(
                    "Issue has no project configured. Run will start in "
                    f'shared organization workspace "{org_root}".'
                ),
            )

        project = await get_project_by_id(self._session, issue.project_id)
        if project is None or project.org_id != issue.org_id:
            return None
        project_policy = _parse_project_policy(project.execution_workspace_policy)
        issue_settings = _parse_issue_settings(issue.execution_workspace_settings)
        mode = _resolve_mode(
            project_policy=project_policy,
            issue_settings=issue_settings,
            issue_preference=issue.execution_workspace_preference,
        )
        if mode == "agent_default":
            return None
        strategy_type = _resolve_strategy_type(
            project_policy=project_policy, issue_settings=issue_settings, mode=mode
        )
        project_workspace = await self._resolve_project_workspace(
            project_id=project.id,
            policy=project_policy,
            requested_id=issue.project_workspace_id,
        )
        project_workspace_id = (
            project_workspace.id if project_workspace is not None else None
        )
        fallback_cwd: str | None = None
        warnings: list[str] = []
        if project_workspace is None:
            fallback_cwd = str(self._org_workspace_root(issue.org_id))
            warnings.append(
                "Project has no workspace configured. Run will start in "
                f'shared organization workspace "{fallback_cwd}".'
            )
        elif not _string(project_workspace.cwd):
            fallback_cwd = str(self._org_workspace_root(issue.org_id))
            warnings.append(
                "Project workspace has no local cwd configured. Run will start "
                f'in shared organization workspace "{fallback_cwd}".'
            )
        reusable = await self._find_reusable_execution_workspace(
            org_id=issue.org_id,
            project_id=project.id,
            project_workspace_id=project_workspace_id,
            issue_id=issue.id,
            mode=mode,
        )
        row = reusable or await create_execution_workspace(
            self._session,
            {
                "org_id": issue.org_id,
                "project_id": project.id,
                "project_workspace_id": project_workspace_id,
                "source_issue_id": issue.id
                if mode in {"isolated_workspace", "operator_branch"}
                else None,
                "mode": mode,
                "strategy_type": strategy_type,
                "name": f"{project.name} workspace",
                "status": "active",
                "cwd": fallback_cwd,
                "provider_type": "git_worktree"
                if strategy_type == "git_worktree"
                else "local_fs",
                "metadata_json": {
                    "resolvedForIssueId": issue.id,
                    "resolvedMode": mode,
                    **(
                        {
                            "fallback": "organization_workspace",
                            "warnings": warnings,
                        }
                        if fallback_cwd
                        else {}
                    ),
                },
            },
        )
        issue.execution_workspace_id = row.id
        issue.execution_workspace_preference = cast(ExecutionWorkspaceMode, mode)
        await self._session.execute(
            update(Issue)
            .where(Issue.id == issue.id)
            .values(
                execution_workspace_id=row.id,
                execution_workspace_preference=mode,
                updated_at=datetime.now(UTC),
            )
        )
        return self._to_execution_workspace(row)

    async def prepare_runtime_context_for_run(
        self, run_id: str, context_snapshot: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        snapshot = dict(context_snapshot or {})
        issue_id = snapshot.get("issueId") or snapshot.get("primaryIssueId")
        if not isinstance(issue_id, str) or not issue_id:
            return None
        issue = await self._session.get(Issue, issue_id)
        if issue is None:
            return None
        workspace = await self.resolve_for_issue(issue)
        if workspace is None:
            return None
        workspace = await self._ensure_managed_workspace_paths(workspace)
        services = await self.list_runtime_services_for_workspace(workspace["id"])
        org_root = self._org_workspace_root(issue.org_id)
        agents_dir = org_root / "agents"
        skills_dir = org_root / "skills"
        plans_dir = org_root / "plans"
        artifacts_dir = org_root / "artifacts"
        issue_artifacts_dir = artifacts_dir / "issues" / issue.id
        run_artifacts_dir = issue_artifacts_dir / "runs" / run_id
        for path in (
            org_root,
            agents_dir,
            skills_dir,
            plans_dir,
            artifacts_dir,
            issue_artifacts_dir,
            run_artifacts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        workspace = self._with_organization_workspace_paths(
            workspace=workspace,
            org_root=org_root,
            agents_dir=agents_dir,
            skills_dir=skills_dir,
            plans_dir=plans_dir,
            artifacts_dir=artifacts_dir,
            issue_artifacts_dir=issue_artifacts_dir,
            run_artifacts_dir=run_artifacts_dir,
        )
        workspace_env = self._workspace_env(
            workspace=workspace,
            org_root=org_root,
            agents_dir=agents_dir,
            skills_dir=skills_dir,
            plans_dir=plans_dir,
            artifacts_dir=artifacts_dir,
            issue_artifacts_dir=issue_artifacts_dir,
            run_artifacts_dir=run_artifacts_dir,
        )
        runtime_context = {
            "rudderWorkspace": workspace,
            "rudderWorkspaces": [workspace],
            "rudderRuntimeServiceIntents": [],
            "rudderRuntimeServices": services,
            "env": workspace_env,
        }
        runtime_context["env"]["RUDDER_RUNTIME_SERVICES_JSON"] = _json_dump(services)
        return {
            "issueId": issue.id,
            "projectId": issue.project_id,
            "projectWorkspaceId": workspace["projectWorkspaceId"],
            "executionWorkspaceId": workspace["id"],
            "workspace": runtime_context,
        }

    async def prepare_runtime_context_for_chat(
        self,
        *,
        run_id: str,
        org_id: str,
        conversation_id: str,
        primary_issue_id: str | None = None,
    ) -> dict[str, Any]:
        if primary_issue_id:
            issue_context = await self.prepare_runtime_context_for_run(
                run_id, {"issueId": primary_issue_id}
            )
            if issue_context is not None:
                issue_context["conversationId"] = conversation_id
                return issue_context

        org_root = self._org_workspace_root(org_id)
        agents_dir = org_root / "agents"
        skills_dir = org_root / "skills"
        plans_dir = org_root / "plans"
        artifacts_dir = org_root / "artifacts"
        conversation_artifacts_dir = artifacts_dir / "conversations" / conversation_id
        run_artifacts_dir = conversation_artifacts_dir / "runs" / run_id
        for path in (
            org_root,
            agents_dir,
            skills_dir,
            plans_dir,
            artifacts_dir,
            conversation_artifacts_dir,
            run_artifacts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

        fallback_workspace = self._organization_workspace_fallback(
            _IssueWorkspaceFallback(
                org_id=org_id,
                id=conversation_id,
            ),
            cwd=str(org_root),
            warning=(
                "Chat has no primary issue workspace. Run will start in "
                f'shared organization workspace "{org_root}".'
            ),
        )
        workspace = dict(
            self._with_organization_workspace_paths(
                workspace=fallback_workspace,
                org_root=org_root,
                agents_dir=agents_dir,
                skills_dir=skills_dir,
                plans_dir=plans_dir,
                artifacts_dir=artifacts_dir,
                issue_artifacts_dir=conversation_artifacts_dir,
                run_artifacts_dir=run_artifacts_dir,
            )
        )
        workspace["conversationArtifactsDir"] = str(conversation_artifacts_dir)
        workspace["issueArtifactsDir"] = None

        workspace_env = self._workspace_env(
            workspace=cast(ExecutionWorkspaceData, workspace),
            org_root=org_root,
            agents_dir=agents_dir,
            skills_dir=skills_dir,
            plans_dir=plans_dir,
            artifacts_dir=artifacts_dir,
            issue_artifacts_dir=conversation_artifacts_dir,
            run_artifacts_dir=run_artifacts_dir,
        )
        workspace_env["RUDDER_CONVERSATION_ARTIFACTS_DIR"] = str(
            conversation_artifacts_dir
        )
        workspace_env.pop("RUDDER_ISSUE_ARTIFACTS_DIR", None)
        runtime_context = {
            "rudderWorkspace": workspace,
            "rudderWorkspaces": [workspace],
            "rudderRuntimeServiceIntents": [],
            "rudderRuntimeServices": [],
            "env": workspace_env,
        }
        runtime_context["env"]["RUDDER_RUNTIME_SERVICES_JSON"] = "[]"
        return {
            "conversationId": conversation_id,
            "issueId": None,
            "projectId": None,
            "projectWorkspaceId": None,
            "executionWorkspaceId": None,
            "workspace": runtime_context,
        }

    async def persist_adapter_runtime_services(
        self,
        *,
        run_id: str,
        agent_id: str,
        agent_runtime_type: str,
        context_snapshot: dict[str, Any] | None,
        reports: list[dict[str, Any]] | None,
    ) -> list[RuntimeServiceData]:
        if not reports:
            return []
        snapshot = dict(context_snapshot or {})
        workspace_context = snapshot.get("workspace")
        workspace = (
            workspace_context.get("rudderWorkspace")
            if isinstance(workspace_context, dict)
            else None
        )
        if not isinstance(workspace, dict):
            return []
        now = datetime.now(UTC)
        records: list[RuntimeServiceData] = []
        for index, report in enumerate(reports):
            if not isinstance(report, dict):
                continue
            service_name = _string(report.get("serviceName")) or "service"
            scope_type = _string(report.get("scopeType")) or "run"
            scope_id = _string(report.get("scopeId")) or run_id
            service_id = (
                _string(report.get("id"))
                or f"{run_id}:{agent_runtime_type}:{scope_type}:{scope_id}:{service_name}:{index}"
            )
            status = _string(report.get("status")) or "running"
            lifecycle = _string(report.get("lifecycle")) or "ephemeral"
            health_status = _string(report.get("healthStatus")) or (
                "healthy" if status == "running" else "unknown"
            )
            row = await create_workspace_runtime_service(
                self._session,
                {
                    "id": service_id,
                    "org_id": workspace.get("orgId"),
                    "project_id": report.get("projectId") or workspace.get("projectId"),
                    "project_workspace_id": report.get("projectWorkspaceId")
                    or workspace.get("projectWorkspaceId"),
                    "execution_workspace_id": report.get("executionWorkspaceId")
                    or workspace.get("id"),
                    "issue_id": report.get("issueId") or snapshot.get("issueId"),
                    "scope_type": scope_type,
                    "scope_id": scope_id,
                    "service_name": service_name,
                    "status": status,
                    "lifecycle": lifecycle,
                    "reuse_key": report.get("reuseKey"),
                    "command": report.get("command"),
                    "cwd": report.get("cwd"),
                    "port": report.get("port"),
                    "url": report.get("url"),
                    "provider": _string(report.get("provider")) or "adapter_managed",
                    "provider_ref": report.get("providerRef"),
                    "owner_agent_id": report.get("ownerAgentId") or agent_id,
                    "started_by_run_id": run_id,
                    "last_used_at": now,
                    "started_at": now,
                    "stopped_at": None if status in {"starting", "running"} else now,
                    "stop_policy": report.get("stopPolicy"),
                    "health_status": health_status,
                },
            )
            records.append(self._to_runtime_service(row))
        return records

    async def release_runtime_services_for_run(self, run_id: str) -> None:
        from packages.database.queries.workspaces import (
            list_workspace_runtime_services_for_run,
        )

        rows = await list_workspace_runtime_services_for_run(self._session, run_id)
        now = datetime.now(UTC)
        for row in rows:
            if row.lifecycle == "ephemeral" and row.status in {"starting", "running"}:
                await update_workspace_runtime_service(
                    self._session,
                    row.id,
                    {
                        "status": "stopped",
                        "health_status": "unknown",
                        "stopped_at": now,
                        "last_used_at": now,
                    },
                )

    async def mark_run_workspace_interrupted(
        self, run_id: str, *, reason: str, message: str
    ) -> None:
        await self.release_runtime_services_for_run(run_id)
        rows = await list_running_workspace_operations_for_run(self._session, run_id)
        for row in rows:
            metadata = dict(row.metadata_json or {})
            metadata.update({"interrupted": True, "reason": reason})
            await update_workspace_operation(
                self._session,
                row.id,
                {
                    "status": "failed",
                    "stderr_excerpt": message,
                    "metadata_json": metadata,
                    "finished_at": datetime.now(UTC),
                },
            )

    async def list_runtime_services_for_workspace(
        self, execution_workspace_id: str
    ) -> list[RuntimeServiceData]:
        rows = await list_workspace_runtime_services_for_workspace(
            self._session, execution_workspace_id
        )
        return [self._to_runtime_service(row) for row in rows]

    async def list_work_products_for_issue(
        self, issue_id: str
    ) -> list[IssueWorkProductData]:
        rows = await list_issue_work_products(self._session, issue_id)
        return [self._to_work_product(row) for row in rows]

    async def get_work_product(self, product_id: str) -> IssueWorkProductData | None:
        row = await get_issue_work_product(self._session, product_id)
        return self._to_work_product(row) if row is not None else None

    async def create_work_product_for_issue(
        self,
        *,
        org_id: str,
        issue_id: str,
        project_id: str | None,
        payload: Mapping[str, Any],
    ) -> IssueWorkProductData:
        row = await create_issue_work_product(
            self._session,
            {
                "org_id": org_id,
                "issue_id": issue_id,
                "project_id": payload.get("projectId", project_id),
                "execution_workspace_id": payload.get("executionWorkspaceId"),
                "runtime_service_id": payload.get("runtimeServiceId"),
                "type": payload["type"],
                "provider": payload["provider"],
                "external_id": payload.get("externalId"),
                "title": payload["title"],
                "url": payload.get("url"),
                "status": payload.get("status", "active"),
                "review_state": payload.get("reviewState", "none"),
                "is_primary": payload.get("isPrimary", False),
                "health_status": payload.get("healthStatus", "unknown"),
                "summary": payload.get("summary"),
                "metadata_json": payload.get("metadata"),
                "created_by_run_id": payload.get("createdByRunId"),
            },
        )
        return self._to_work_product(row)

    async def update_work_product(
        self, product_id: str, payload: Mapping[str, Any]
    ) -> IssueWorkProductData | None:
        fields: dict[str, Any] = {}
        for source, column in _WORK_PRODUCT_UPDATE_COLUMNS.items():
            if source in payload:
                fields[column] = payload[source]
        row = await update_issue_work_product(self._session, product_id, fields)
        return self._to_work_product(row) if row is not None else None

    async def delete_work_product(self, product_id: str) -> IssueWorkProductData | None:
        row = await delete_issue_work_product(self._session, product_id)
        return self._to_work_product(row) if row is not None else None

    async def persist_run_work_products(
        self,
        *,
        run_id: str,
        context_snapshot: dict[str, Any] | None,
        products: list[dict[str, Any]] | None,
    ) -> list[IssueWorkProductData]:
        if not products:
            return []
        snapshot = dict(context_snapshot or {})
        issue_id = snapshot.get("issueId") or snapshot.get("primaryIssueId")
        if not isinstance(issue_id, str) or not issue_id:
            return []
        issue = await self._session.get(Issue, issue_id)
        if issue is None:
            return []
        workspace_context = snapshot.get("workspace")
        workspace = (
            workspace_context.get("rudderWorkspace")
            if isinstance(workspace_context, dict)
            else None
        )
        stored: list[IssueWorkProductData] = []
        for product in products:
            if not isinstance(product, dict):
                continue
            title = _string(product.get("title"))
            product_type = _string(product.get("type"))
            provider = _string(product.get("provider")) or "rudder"
            if not title or not product_type:
                continue
            product = await self._archive_work_product_content(issue.org_id, product)
            row = await create_issue_work_product(
                self._session,
                {
                    "org_id": issue.org_id,
                    "project_id": product.get("projectId") or issue.project_id,
                    "issue_id": issue.id,
                    "execution_workspace_id": product.get("executionWorkspaceId")
                    or (workspace.get("id") if isinstance(workspace, dict) else None),
                    "runtime_service_id": product.get("runtimeServiceId"),
                    "type": product_type,
                    "provider": provider,
                    "external_id": product.get("externalId"),
                    "title": title,
                    "url": product.get("url"),
                    "status": _string(product.get("status")) or "active",
                    "review_state": _string(product.get("reviewState")) or "none",
                    "is_primary": bool(product.get("isPrimary")),
                    "health_status": _string(product.get("healthStatus")) or "unknown",
                    "summary": product.get("summary"),
                    "metadata_json": product.get("metadata"),
                    "created_by_run_id": run_id,
                },
            )
            stored.append(self._to_work_product(row))
        return stored

    async def persist_generated_workspace_files(
        self,
        *,
        run_id: str,
        context_snapshot: dict[str, Any] | None,
        since: datetime | None,
    ) -> list[IssueWorkProductData]:
        snapshot = dict(context_snapshot or {})
        issue_id = snapshot.get("issueId") or snapshot.get("primaryIssueId")
        if not isinstance(issue_id, str) or not issue_id:
            return []
        issue = await self._session.get(Issue, issue_id)
        if issue is None:
            return []
        workspace_context = snapshot.get("workspace")
        workspace = (
            workspace_context.get("rudderWorkspace")
            if isinstance(workspace_context, dict)
            else None
        )
        if not isinstance(workspace, dict):
            return []
        workspace_id = _string(workspace.get("id"))
        cwd = _string(workspace.get("cwd"))
        if cwd is None:
            return []
        workspace_ref = workspace_id or f"organization_workspace:{issue.org_id}"
        worktree_root = Path(cwd).resolve()
        if not worktree_root.is_dir():
            return []
        threshold = _aware_utc(since) - timedelta(seconds=1) if since else None
        products: list[dict[str, Any]] = []
        scan_roots: list[tuple[str, Path]] = []
        workspace_env = (
            workspace_context.get("env")
            if isinstance(workspace_context, dict)
            else None
        )
        artifacts_dir = _string(workspace.get("orgArtifactsDir"))
        if not artifacts_dir and isinstance(workspace_env, dict):
            artifacts_dir = _string(workspace_env.get("RUDDER_ORG_ARTIFACTS_DIR"))
        artifacts_root = Path(artifacts_dir).resolve() if artifacts_dir else None
        run_artifacts_dir = _string(workspace.get("runArtifactsDir"))
        if not run_artifacts_dir and isinstance(workspace_env, dict):
            run_artifacts_dir = _string(workspace_env.get("RUDDER_RUN_ARTIFACTS_DIR"))
        if run_artifacts_dir:
            run_artifacts_root = Path(run_artifacts_dir).resolve()
            if run_artifacts_root.is_dir() and run_artifacts_root != worktree_root:
                scan_roots.append(
                    ("organization_run_artifacts_scan", run_artifacts_root)
                )
        if artifacts_dir:
            assert artifacts_root is not None
            if artifacts_root.is_dir() and artifacts_root != worktree_root:
                scan_roots.append(("organization_artifacts_scan", artifacts_root))
        scan_roots.append(("execution_workspace_scan", worktree_root))
        seen_paths: set[Path] = set()
        for source, root in scan_roots:
            for path in _iter_generated_workspace_files(root, threshold):
                if len(products) >= _GENERATED_FILE_MAX_COUNT:
                    break
                resolved_path = path.resolve()
                if resolved_path in seen_paths:
                    continue
                seen_paths.add(resolved_path)
                rel_path = path.relative_to(root).as_posix()
                workspace_browser_path = _workspace_browser_path(
                    path=path,
                    artifacts_root=artifacts_root,
                )
                content = path.read_bytes()
                content_type = mimetypes.guess_type(path.name)[0] or "text/plain"
                products.append(
                    {
                        "title": rel_path,
                        "type": "document"
                        if path.suffix.lower() in {".md", ".txt"}
                        else "artifact",
                        "provider": "rudder",
                        "externalId": f"{source}:{workspace_ref}:{rel_path}",
                        "status": "active",
                        "reviewState": "none",
                        "isPrimary": len(products) == 0,
                        "summary": "Generated file captured from managed workspace storage.",
                        "content": content,
                        "contentType": content_type,
                        "filename": path.name,
                        "metadata": {
                            "source": source,
                            "workspacePath": rel_path,
                            "workspaceBrowserPath": workspace_browser_path,
                            "executionWorkspaceId": workspace_id,
                            "byteSize": len(content),
                        },
                    }
                )
        if not products:
            return []
        return await self.persist_run_work_products(
            run_id=run_id,
            context_snapshot=context_snapshot,
            products=products,
        )

    async def _archive_work_product_content(
        self, org_id: str, product: dict[str, Any]
    ) -> dict[str, Any]:
        body = product.get("content")
        if body is None:
            return product
        if isinstance(body, str):
            content = body.encode("utf-8")
            content_type = _string(product.get("contentType")) or "text/plain"
        elif isinstance(body, bytes):
            content = body
            content_type = (
                _string(product.get("contentType")) or "application/octet-stream"
            )
        else:
            return product
        if not content:
            return product
        storage = get_storage_service()
        stored = await storage.put_file(
            org_id=org_id,
            namespace="work-products",
            original_filename=_string(product.get("filename"))
            or f"{_string(product.get('title')) or 'work-product'}.txt",
            content_type=content_type,
            body=content,
        )
        asset = await create_asset(
            self._session,
            {
                "org_id": org_id,
                "provider": stored["provider"],
                "object_key": stored["objectKey"],
                "content_type": stored["contentType"],
                "byte_size": stored["byteSize"],
                "sha256": stored["sha256"],
                "original_filename": stored["originalFilename"],
            },
        )
        metadata = dict(product.get("metadata") or {})
        metadata.update(
            {
                "assetId": asset.id,
                "contentPath": f"/api/assets/{asset.id}/content",
                "contentType": asset.content_type,
                "byteSize": asset.byte_size,
                "sha256": asset.sha256,
            }
        )
        archived = dict(product)
        archived.pop("content", None)
        archived["metadata"] = metadata
        archived.setdefault("url", f"/api/assets/{asset.id}/content")
        return archived

    async def begin_operation(
        self,
        *,
        org_id: str,
        run_id: str | None,
        execution_workspace_id: str | None,
        phase: str,
        command: str | None = None,
        cwd: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkspaceOperationData:
        row = await create_workspace_operation(
            self._session,
            {
                "org_id": org_id,
                "execution_workspace_id": execution_workspace_id,
                "heartbeat_run_id": run_id,
                "phase": phase,
                "command": command,
                "cwd": cwd,
                "status": "running",
                "metadata_json": metadata,
            },
        )
        log_ref = f"{org_id}/{row.id}.ndjson"
        append_local_file_log(
            _operation_log_dir(),
            log_ref,
            stream="system",
            chunk=f"operation {phase} started",
        )
        row = await update_workspace_operation(
            self._session,
            row.id,
            {
                "log_store": "local_file",
                "log_ref": log_ref,
                "log_bytes": 0,
                "log_compressed": False,
            },
        )
        assert row is not None
        return self._to_operation(row)

    async def append_operation_log(
        self,
        operation_id: str,
        *,
        stream: str,
        chunk: str,
    ) -> None:
        row = await get_workspace_operation(self._session, operation_id)
        if row is None or row.log_store != "local_file" or row.log_ref is None:
            return
        append_local_file_log(
            _operation_log_dir(),
            row.log_ref,
            stream=stream,
            chunk=chunk,
        )

    async def finish_operation(
        self,
        operation_id: str,
        *,
        status: str,
        exit_code: int | None = None,
        stdout_excerpt: str | None = None,
        stderr_excerpt: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkspaceOperationData | None:
        row = await get_workspace_operation(self._session, operation_id)
        log_fields: dict[str, Any] = {}
        if row is not None and row.log_store == "local_file":
            await self.append_operation_log(
                operation_id,
                stream="system",
                chunk=f"operation finished with status {status}",
            )
            log_fields = finalize_local_file_log(_operation_log_dir(), row.log_ref)
        row = await update_workspace_operation(
            self._session,
            operation_id,
            {
                "status": status,
                "exit_code": exit_code,
                "stdout_excerpt": stdout_excerpt,
                "stderr_excerpt": stderr_excerpt,
                "metadata_json": metadata,
                "finished_at": datetime.now(UTC),
                **_database_log_fields(log_fields),
            },
        )
        return self._to_operation(row) if row is not None else None

    async def list_operations_for_run(
        self, run_id: str
    ) -> list[WorkspaceOperationData]:
        rows = await list_workspace_operations_for_run(self._session, run_id)
        return [self._to_operation(row) for row in rows]

    async def get_operation(self, operation_id: str) -> WorkspaceOperationData | None:
        row = await get_workspace_operation(self._session, operation_id)
        return self._to_operation(row) if row is not None else None

    async def read_operation_log(
        self, operation_id: str, *, offset: int = 0, limit_bytes: int = 256_000
    ) -> dict[str, Any] | None:
        row = await get_workspace_operation(self._session, operation_id)
        if row is None:
            return None
        if row.log_store != "local_file":
            log: LogReadResult = {"content": "", "endOffset": 0, "eof": True}
        else:
            log = read_local_file_log(
                Path(
                    os.getenv(
                        "OCTOPUS_WORKSPACE_OPERATION_LOG_DIR",
                        ".octopus/workspace-operation-logs",
                    )
                ),
                row.log_ref,
                offset=offset,
                limit_bytes=limit_bytes,
            )
        return {
            "operationId": row.id,
            "store": row.log_store,
            "logRef": row.log_ref,
            **log,
        }

    async def _resolve_project_workspace(
        self,
        *,
        project_id: str,
        policy: dict[str, Any] | None,
        requested_id: str | None,
    ) -> Any | None:
        workspaces = await list_project_workspaces(self._session, project_id)
        if requested_id:
            return next(
                (workspace for workspace in workspaces if workspace.id == requested_id),
                None,
            )
        policy_workspace_id = (
            policy.get("defaultProjectWorkspaceId") if policy is not None else None
        )
        if isinstance(policy_workspace_id, str):
            return next(
                (
                    workspace
                    for workspace in workspaces
                    if workspace.id == policy_workspace_id
                ),
                None,
            )
        primary = next(
            (workspace for workspace in workspaces if workspace.is_primary), None
        )
        if not workspaces:
            return None
        return primary or workspaces[0]

    async def _ensure_managed_workspace_paths(
        self, workspace: ExecutionWorkspaceData
    ) -> ExecutionWorkspaceData:
        cwd = workspace["cwd"]
        if cwd:
            worktree = Path(cwd)
        else:
            worktree = (
                self._org_workspace_root(workspace["orgId"])
                / "executions"
                / workspace["id"]
                / "worktree"
            )
            row = await update_execution_workspace(
                self._session, workspace["id"], {"cwd": str(worktree)}
            )
            if row is not None:
                workspace = self._to_execution_workspace(row)
        worktree.mkdir(parents=True, exist_ok=True)
        log_dir = worktree.parent / "logs"
        tmp_dir = worktree.parent / "tmp"
        log_dir.mkdir(parents=True, exist_ok=True)
        tmp_dir.mkdir(parents=True, exist_ok=True)
        return workspace

    def _org_workspace_root(self, org_id: str) -> Path:
        if (
            organization_workspace_root
            is not workspace_paths_module.organization_workspace_root
        ):
            return organization_workspace_root(org_id)
        return ensure_organization_workspace_root(org_id)

    def _with_organization_workspace_paths(
        self,
        *,
        workspace: ExecutionWorkspaceData,
        org_root: Path,
        agents_dir: Path,
        skills_dir: Path,
        plans_dir: Path,
        artifacts_dir: Path,
        issue_artifacts_dir: Path,
        run_artifacts_dir: Path,
    ) -> ExecutionWorkspaceData:
        enriched = dict(workspace)
        enriched.update(
            {
                "source": workspace["providerType"],
                "strategy": workspace["strategyType"],
                "workspaceId": workspace["id"],
                "orgWorkspaceRoot": str(org_root),
                "orgAgentsDir": str(agents_dir),
                "orgSkillsDir": str(skills_dir),
                "orgPlansDir": str(plans_dir),
                "orgArtifactsDir": str(artifacts_dir),
                "issueArtifactsDir": str(issue_artifacts_dir),
                "runArtifactsDir": str(run_artifacts_dir),
            }
        )
        return cast(ExecutionWorkspaceData, enriched)

    def _workspace_env(
        self,
        *,
        workspace: ExecutionWorkspaceData,
        org_root: Path,
        agents_dir: Path,
        skills_dir: Path,
        plans_dir: Path,
        artifacts_dir: Path,
        issue_artifacts_dir: Path,
        run_artifacts_dir: Path,
    ) -> dict[str, str]:
        workspaces_json = _json_dump([workspace])
        services_json = _json_dump([])
        return {
            "RUDDER_WORKSPACE_CWD": workspace["cwd"] or "",
            "RUDDER_WORKSPACE_SOURCE": workspace["providerType"],
            "RUDDER_WORKSPACE_STRATEGY": workspace["strategyType"],
            "RUDDER_WORKSPACE_ID": workspace["id"] or "",
            "RUDDER_WORKSPACE_REPO_URL": workspace["repoUrl"] or "",
            "RUDDER_WORKSPACE_REPO_REF": workspace["baseRef"] or "",
            "RUDDER_WORKSPACE_BRANCH": workspace["branchName"] or "",
            "RUDDER_WORKSPACE_WORKTREE_PATH": workspace["cwd"] or "",
            "RUDDER_WORKSPACES_JSON": workspaces_json,
            "RUDDER_RUNTIME_SERVICE_INTENTS_JSON": "[]",
            "RUDDER_RUNTIME_SERVICES_JSON": services_json,
            "RUDDER_ORG_WORKSPACE_ROOT": str(org_root),
            "RUDDER_ORG_AGENTS_DIR": str(agents_dir),
            "RUDDER_ORG_SKILLS_DIR": str(skills_dir),
            "RUDDER_ORG_PLANS_DIR": str(plans_dir),
            "RUDDER_ORG_ARTIFACTS_DIR": str(artifacts_dir),
            "RUDDER_ISSUE_ARTIFACTS_DIR": str(issue_artifacts_dir),
            "RUDDER_RUN_ARTIFACTS_DIR": str(run_artifacts_dir),
        }

    async def _find_reusable_execution_workspace(
        self,
        *,
        org_id: str,
        project_id: str,
        project_workspace_id: str | None,
        issue_id: str,
        mode: str,
    ) -> ExecutionWorkspace | None:
        issue_scope = (
            issue_id if mode in {"isolated_workspace", "operator_branch"} else None
        )
        rows = await list_execution_workspaces(
            self._session,
            org_id,
            project_id=project_id,
            project_workspace_id=project_workspace_id,
            issue_id=issue_scope,
            reuse_eligible=True,
        )
        return rows[0] if rows else None

    def _to_execution_workspace(
        self, row: ExecutionWorkspace
    ) -> ExecutionWorkspaceData:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "projectId": row.project_id,
            "projectWorkspaceId": row.project_workspace_id,
            "sourceIssueId": row.source_issue_id,
            "mode": row.mode,
            "strategyType": cast(ExecutionWorkspaceStrategyType, row.strategy_type),
            "name": row.name,
            "status": cast(ExecutionWorkspaceStatus, row.status),
            "cwd": row.cwd,
            "repoUrl": row.repo_url,
            "baseRef": row.base_ref,
            "branchName": row.branch_name,
            "providerType": cast(Any, row.provider_type),
            "providerRef": row.provider_ref,
            "derivedFromExecutionWorkspaceId": row.derived_from_execution_workspace_id,
            "lastUsedAt": row.last_used_at.isoformat(),
            "openedAt": row.opened_at.isoformat(),
            "closedAt": _iso(row.closed_at),
            "cleanupEligibleAt": _iso(row.cleanup_eligible_at),
            "cleanupReason": row.cleanup_reason,
            "metadata": row.metadata_json,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }

    def _organization_workspace_fallback(
        self, issue: Issue | _IssueWorkspaceFallback, *, cwd: str, warning: str
    ) -> ExecutionWorkspaceData:
        now = datetime.now(UTC).isoformat()
        return cast(
            ExecutionWorkspaceData,
            {
                "id": None,
                "orgId": issue.org_id,
                "projectId": None,
                "projectWorkspaceId": None,
                "sourceIssueId": issue.id,
                "mode": "shared_workspace",
                "strategyType": "organization_workspace",
                "name": "Organization workspace",
                "status": "active",
                "cwd": cwd,
                "repoUrl": None,
                "baseRef": None,
                "branchName": None,
                "providerType": "local_fs",
                "providerRef": None,
                "derivedFromExecutionWorkspaceId": None,
                "lastUsedAt": now,
                "openedAt": now,
                "closedAt": None,
                "cleanupEligibleAt": None,
                "cleanupReason": None,
                "metadata": {
                    "resolvedForIssueId": issue.id,
                    "resolvedMode": "shared_workspace",
                    "fallback": "organization_workspace",
                    "warnings": [warning],
                },
                "createdAt": now,
                "updatedAt": now,
            },
        )

    def _to_runtime_service(self, row: WorkspaceRuntimeService) -> RuntimeServiceData:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "projectId": row.project_id,
            "projectWorkspaceId": row.project_workspace_id,
            "executionWorkspaceId": row.execution_workspace_id,
            "issueId": row.issue_id,
            "scopeType": cast(Any, row.scope_type),
            "scopeId": row.scope_id,
            "serviceName": row.service_name,
            "status": cast(Any, row.status),
            "lifecycle": cast(Any, row.lifecycle),
            "reuseKey": row.reuse_key,
            "command": row.command,
            "cwd": row.cwd,
            "port": row.port,
            "url": row.url,
            "provider": cast(Any, row.provider),
            "providerRef": row.provider_ref,
            "ownerAgentId": row.owner_agent_id,
            "startedByRunId": row.started_by_run_id,
            "lastUsedAt": row.last_used_at.isoformat(),
            "startedAt": row.started_at.isoformat(),
            "stoppedAt": _iso(row.stopped_at),
            "stopPolicy": row.stop_policy,
            "healthStatus": cast(Any, row.health_status),
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }

    def _to_operation(self, row: WorkspaceOperation) -> WorkspaceOperationData:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "executionWorkspaceId": row.execution_workspace_id,
            "heartbeatRunId": row.heartbeat_run_id,
            "phase": cast(Any, row.phase),
            "command": row.command,
            "cwd": row.cwd,
            "status": cast(Any, row.status),
            "exitCode": row.exit_code,
            "logStore": row.log_store,
            "logRef": row.log_ref,
            "logBytes": row.log_bytes,
            "logSha256": row.log_sha256,
            "logCompressed": row.log_compressed,
            "stdoutExcerpt": row.stdout_excerpt,
            "stderrExcerpt": row.stderr_excerpt,
            "metadata": row.metadata_json,
            "startedAt": row.started_at.isoformat(),
            "finishedAt": _iso(row.finished_at),
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }

    def _to_work_product(self, row: IssueWorkProduct) -> IssueWorkProductData:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "projectId": row.project_id,
            "issueId": row.issue_id,
            "executionWorkspaceId": row.execution_workspace_id,
            "runtimeServiceId": row.runtime_service_id,
            "type": cast(Any, row.type),
            "provider": row.provider,
            "externalId": row.external_id,
            "title": row.title,
            "url": row.url,
            "assetId": (
                row.metadata_json.get("assetId")
                if isinstance(row.metadata_json, dict)
                else None
            ),
            "contentPath": (
                row.metadata_json.get("contentPath")
                if isinstance(row.metadata_json, dict)
                else None
            ),
            "status": cast(Any, row.status),
            "reviewState": cast(Any, row.review_state),
            "isPrimary": row.is_primary,
            "healthStatus": cast(Any, row.health_status),
            "summary": row.summary,
            "metadata": row.metadata_json,
            "createdByRunId": row.created_by_run_id,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }


def _parse_datetime(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return cast(datetime | None, value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _json_dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _workspace_browser_path(*, path: Path, artifacts_root: Path | None) -> str | None:
    if artifacts_root is None:
        return None
    try:
        rel_path = path.resolve().relative_to(artifacts_root.resolve()).as_posix()
    except ValueError:
        return None
    return f"artifacts/{rel_path}"
