from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from packages.shared.constants.workspace import (
    EXECUTION_WORKSPACE_MODES,
    EXECUTION_WORKSPACE_STATUSES,
    EXECUTION_WORKSPACE_STRATEGY_TYPES,
    PROJECT_EXECUTION_WORKSPACE_DEFAULT_MODES,
)
from packages.shared.types.workspace import (
    IssueExecutionWorkspaceSettings,
    ProjectExecutionWorkspacePolicy,
    UpdateExecutionWorkspacePayload,
)

_UPDATE_EXECUTION_WORKSPACE_FIELDS = {
    "status",
    "cleanupEligibleAt",
    "cleanupReason",
    "metadata",
}
_PROJECT_POLICY_FIELDS = {
    "enabled",
    "defaultMode",
    "allowIssueOverride",
    "defaultProjectWorkspaceId",
    "workspaceStrategy",
    "workspaceRuntime",
    "branchPolicy",
    "pullRequestPolicy",
    "runtimePolicy",
    "cleanupPolicy",
}
_ISSUE_WORKSPACE_SETTINGS_FIELDS = {
    "mode",
    "workspaceStrategy",
    "workspaceRuntime",
}
_WORKSPACE_STRATEGY_FIELDS = {
    "type",
    "mode",
    "baseRef",
    "branchTemplate",
    "operatorBranch",
    "worktreeParentDir",
    "provisionCommand",
    "teardownCommand",
}
_STRING_OR_NULL_FIELDS = {
    "baseRef",
    "branchTemplate",
    "operatorBranch",
    "worktreeParentDir",
    "provisionCommand",
    "teardownCommand",
}


def _reject_unknown_fields(
    payload: Mapping[str, Any], *, allowed_fields: set[str]
) -> None:
    for field in payload:
        if field not in allowed_fields:
            raise ValueError(f"Unsupported field: '{field}'")


def _nullable_string(payload: Mapping[str, Any], field: str) -> None:
    if (
        field in payload
        and payload[field] is not None
        and not isinstance(payload[field], str)
    ):
        raise ValueError(f"'{field}' must be a string or null")


def _nullable_datetime(payload: Mapping[str, Any], field: str) -> None:
    if field not in payload or payload[field] is None:
        return
    if not isinstance(payload[field], str):
        raise ValueError(f"'{field}' must be an ISO datetime or null")
    try:
        datetime.fromisoformat(payload[field].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"'{field}' must be an ISO datetime or null") from exc


def validate_project_execution_workspace_policy(
    payload: Mapping[str, Any],
) -> ProjectExecutionWorkspacePolicy:
    _reject_unknown_fields(payload, allowed_fields=_PROJECT_POLICY_FIELDS)
    result = dict(payload)
    if "enabled" in result and not isinstance(result["enabled"], bool):
        raise ValueError("'enabled' must be a boolean")
    if "allowIssueOverride" in result and not isinstance(
        result["allowIssueOverride"], bool
    ):
        raise ValueError("'allowIssueOverride' must be a boolean")
    _nullable_string(result, "defaultProjectWorkspaceId")
    if "defaultMode" in result:
        result["defaultMode"] = _normalize_default_mode(result["defaultMode"])
    if result.get("workspaceStrategy") is not None:
        strategy = result["workspaceStrategy"]
        if not isinstance(strategy, Mapping):
            raise ValueError("'workspaceStrategy' must be an object or null")
        result["workspaceStrategy"] = _validate_workspace_strategy(strategy)
    for field in (
        "workspaceRuntime",
        "branchPolicy",
        "pullRequestPolicy",
        "runtimePolicy",
        "cleanupPolicy",
    ):
        if (
            field in result
            and result[field] is not None
            and not isinstance(result[field], dict)
        ):
            raise ValueError(f"'{field}' must be an object or null")
    return cast(ProjectExecutionWorkspacePolicy, result)


def validate_issue_execution_workspace_settings(
    payload: Mapping[str, Any],
) -> IssueExecutionWorkspaceSettings:
    _reject_unknown_fields(payload, allowed_fields=_ISSUE_WORKSPACE_SETTINGS_FIELDS)
    result = dict(payload)
    if "mode" in result:
        result["mode"] = _normalize_execution_mode(result["mode"])
    if result.get("workspaceStrategy") is not None:
        strategy = result["workspaceStrategy"]
        if not isinstance(strategy, Mapping):
            raise ValueError("'workspaceStrategy' must be an object or null")
        result["workspaceStrategy"] = _validate_workspace_strategy(strategy)
    if "workspaceRuntime" in result and result["workspaceRuntime"] is not None:
        if not isinstance(result["workspaceRuntime"], dict):
            raise ValueError("'workspaceRuntime' must be an object or null")
    return cast(IssueExecutionWorkspaceSettings, result)


def _validate_workspace_strategy(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown_fields(payload, allowed_fields=_WORKSPACE_STRATEGY_FIELDS)
    result = dict(payload)
    legacy_mode = result.get("mode")
    strategy_type = result.get("type")
    if strategy_type is None and legacy_mode is not None:
        strategy_type = _legacy_strategy_mode_to_type(legacy_mode)
    if strategy_type is not None:
        if strategy_type not in EXECUTION_WORKSPACE_STRATEGY_TYPES:
            raise ValueError(
                "'workspaceStrategy.type' must be one of "
                f"{list(EXECUTION_WORKSPACE_STRATEGY_TYPES)}"
            )
        result["type"] = strategy_type
    for field in _STRING_OR_NULL_FIELDS:
        _nullable_string(result, field)
    if (
        "mode" in result
        and result["mode"] is not None
        and not isinstance(result["mode"], str)
    ):
        raise ValueError("'workspaceStrategy.mode' must be a string or null")
    return result


def _normalize_default_mode(value: Any) -> str:
    if value == "project_primary":
        value = "shared_workspace"
    if value == "isolated":
        value = "isolated_workspace"
    if value not in PROJECT_EXECUTION_WORKSPACE_DEFAULT_MODES:
        raise ValueError(
            "'defaultMode' must be one of "
            f"{list(PROJECT_EXECUTION_WORKSPACE_DEFAULT_MODES)}"
        )
    return str(value)


def _normalize_execution_mode(value: Any) -> str:
    if value == "project_primary":
        value = "shared_workspace"
    if value == "isolated":
        value = "isolated_workspace"
    if value not in EXECUTION_WORKSPACE_MODES and value not in {
        "inherit",
        "reuse_existing",
    }:
        raise ValueError(f"'mode' must be one of {list(EXECUTION_WORKSPACE_MODES)}")
    return str(value)


def _legacy_strategy_mode_to_type(value: Any) -> str:
    if value in {"isolated_workspace", "operator_branch", "isolated"}:
        return "git_worktree"
    if value in {"shared_workspace", "project_primary"}:
        return "project_primary"
    if value == "agent_default":
        return "adapter_managed"
    if value in EXECUTION_WORKSPACE_STRATEGY_TYPES:
        return str(value)
    raise ValueError("'workspaceStrategy.mode' is not a supported legacy mode")


def validate_update_execution_workspace(
    payload: Mapping[str, Any],
) -> UpdateExecutionWorkspacePayload:
    _reject_unknown_fields(payload, allowed_fields=_UPDATE_EXECUTION_WORKSPACE_FIELDS)
    if "status" in payload and payload["status"] not in EXECUTION_WORKSPACE_STATUSES:
        raise ValueError(
            f"'status' must be one of {list(EXECUTION_WORKSPACE_STATUSES)}"
        )
    _nullable_datetime(payload, "cleanupEligibleAt")
    _nullable_string(payload, "cleanupReason")
    if (
        "metadata" in payload
        and payload["metadata"] is not None
        and not isinstance(payload["metadata"], dict)
    ):
        raise ValueError("'metadata' must be an object or null")
    return cast(UpdateExecutionWorkspacePayload, dict(payload))
