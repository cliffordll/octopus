from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.projects import get_project_by_id
from packages.database.queries.workspaces import (
    create_execution_workspace,
    create_workspace_operation,
    create_workspace_runtime_service,
    get_execution_workspace_by_id,
    list_execution_workspaces,
    list_project_workspaces,
    list_workspace_runtime_services_for_workspace,
    update_execution_workspace,
    update_workspace_operation,
    update_workspace_runtime_service,
)
from packages.database.schema import (
    ExecutionWorkspace,
    Issue,
    WorkspaceOperation,
    WorkspaceRuntimeService,
)
from packages.shared.constants.workspace import (
    ExecutionWorkspaceMode,
    ExecutionWorkspaceStatus,
    ExecutionWorkspaceStrategyType,
)
from packages.shared.types.workspace import ExecutionWorkspace as ExecutionWorkspaceData
from packages.shared.types.workspace import WorkspaceOperation as WorkspaceOperationData
from packages.shared.types.workspace import WorkspaceRuntimeService as RuntimeServiceData


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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
        if issue.project_id is None:
            return None
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
        project_workspace_id = await self._resolve_project_workspace_id(
            project_id=project.id,
            policy=project_policy,
            requested_id=issue.project_workspace_id,
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
                "provider_type": "git_worktree"
                if strategy_type == "git_worktree"
                else "local_fs",
                "metadata_json": {
                    "resolvedForIssueId": issue.id,
                    "resolvedMode": mode,
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
        artifacts_dir = org_root / "artifacts"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        workspace_env = self._workspace_env(
            workspace=workspace,
            org_root=org_root,
            artifacts_dir=artifacts_dir,
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
            health_status = (
                _string(report.get("healthStatus"))
                or ("healthy" if status == "running" else "unknown")
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
                    "stopped_at": None
                    if status in {"starting", "running"}
                    else now,
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

    async def list_runtime_services_for_workspace(
        self, execution_workspace_id: str
    ) -> list[RuntimeServiceData]:
        rows = await list_workspace_runtime_services_for_workspace(
            self._session, execution_workspace_id
        )
        return [self._to_runtime_service(row) for row in rows]

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
        return self._to_operation(row)

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
            },
        )
        return self._to_operation(row) if row is not None else None

    async def _resolve_project_workspace_id(
        self,
        *,
        project_id: str,
        policy: dict[str, Any] | None,
        requested_id: str | None,
    ) -> str | None:
        if requested_id:
            return requested_id
        policy_workspace_id = (
            policy.get("defaultProjectWorkspaceId") if policy is not None else None
        )
        if isinstance(policy_workspace_id, str):
            return policy_workspace_id
        workspaces = await list_project_workspaces(self._session, project_id)
        primary = next((workspace for workspace in workspaces if workspace.is_primary), None)
        return (primary or (workspaces[0] if workspaces else None)).id if workspaces else None

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
        return (Path.cwd() / ".octopus" / "workspaces" / f"org_{org_id}").resolve()

    def _workspace_env(
        self,
        *,
        workspace: ExecutionWorkspaceData,
        org_root: Path,
        artifacts_dir: Path,
    ) -> dict[str, str]:
        workspaces_json = _json_dump([workspace])
        services_json = _json_dump([])
        return {
            "RUDDER_WORKSPACE_SOURCE": workspace["providerType"],
            "RUDDER_WORKSPACE_STRATEGY": workspace["strategyType"],
            "RUDDER_WORKSPACE_ID": workspace["id"],
            "RUDDER_WORKSPACE_REPO_URL": workspace["repoUrl"] or "",
            "RUDDER_WORKSPACE_REPO_REF": workspace["baseRef"] or "",
            "RUDDER_WORKSPACE_BRANCH": workspace["branchName"] or "",
            "RUDDER_WORKSPACE_WORKTREE_PATH": workspace["cwd"] or "",
            "RUDDER_WORKSPACES_JSON": workspaces_json,
            "RUDDER_RUNTIME_SERVICE_INTENTS_JSON": "[]",
            "RUDDER_RUNTIME_SERVICES_JSON": services_json,
            "RUDDER_ORG_WORKSPACE_ROOT": str(org_root),
            "RUDDER_ORG_ARTIFACTS_DIR": str(artifacts_dir),
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
        issue_scope = issue_id if mode in {"isolated_workspace", "operator_branch"} else None
        rows = await list_execution_workspaces(
            self._session,
            org_id,
            project_id=project_id,
            project_workspace_id=project_workspace_id,
            issue_id=issue_scope,
            reuse_eligible=True,
        )
        return rows[0] if rows else None

    def _to_execution_workspace(self, row: ExecutionWorkspace) -> ExecutionWorkspaceData:
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


def _parse_datetime(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return cast(datetime | None, value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _json_dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None
