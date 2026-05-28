from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.projects import get_project_by_id
from packages.database.queries.workspaces import (
    create_execution_workspace,
    get_execution_workspace_by_id,
    list_execution_workspaces,
    list_project_workspaces,
    update_execution_workspace,
)
from packages.database.schema import ExecutionWorkspace, Issue
from packages.shared.constants.workspace import (
    ExecutionWorkspaceMode,
    ExecutionWorkspaceStatus,
    ExecutionWorkspaceStrategyType,
)
from packages.shared.types.workspace import ExecutionWorkspace as ExecutionWorkspaceData


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


def _parse_datetime(value: object) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return cast(datetime | None, value)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
