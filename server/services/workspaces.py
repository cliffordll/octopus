from __future__ import annotations

import hashlib
import json
import mimetypes
import subprocess
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
    list_workspace_operations_for_execution_workspace,
    list_workspace_operations_for_run,
    list_workspace_runtime_services_for_workspace,
    update_execution_workspace,
    update_project_workspace,
    update_issue_work_product,
    update_workspace_operation,
    update_workspace_runtime_service,
)
from packages.database.queries.assets import create_asset, get_asset_by_sha256
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
from packages.shared.validators.workspace import (
    validate_issue_execution_workspace_settings,
    validate_project_workspace_execution_policy,
)

from .logs import (
    LogReadResult,
    append_local_file_log,
    finalize_local_file_log,
    read_local_file_log,
)
from . import workspace_paths as workspace_paths_module
from .workspace_paths import (
    agent_heartbeat_workspace_root,
    ensure_organization_workspace_root,
    ensure_octopus_workspace_operation_log_dir,
    organization_workspace_root,
)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _operation_log_dir() -> Path:
    return ensure_octopus_workspace_operation_log_dir()


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
    # Binary document deliverables agents commonly produce. Without these, a
    # generated .docx/.pdf/... is silently skipped by the work-product scan and
    # only ever surfaces as an issue attachment, never as a work product.
    ".doc",
    ".docx",
    ".odp",
    ".ods",
    ".odt",
    ".pdf",
    ".ppt",
    ".pptx",
    ".rtf",
    ".xls",
    ".xlsx",
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
_GENERATED_FILE_EXCLUDED_AGENT_DIRS = {
    "instructions",
    "life",
    "memory",
    "skills",
}
# Binary document deliverables (docx/pdf with embedded images) routinely exceed
# the old 1 MB text-oriented cap; raise it so real deliverables aren't dropped.
_GENERATED_FILE_MAX_BYTES = 25_000_000
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
        if _is_agent_internal_generated_file(rel_parts):
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


def _is_agent_internal_generated_file(rel_parts: tuple[str, ...]) -> bool:
    return (
        len(rel_parts) >= 4
        and rel_parts[0] == "agents"
        and rel_parts[2] in _GENERATED_FILE_EXCLUDED_AGENT_DIRS
    )


def _parse_workspace_policy(value: Any) -> dict[str, Any] | None:
    parsed = _as_record(value)
    if not parsed:
        return None
    return dict(validate_project_workspace_execution_policy(parsed))


def _parse_issue_settings(value: Any) -> dict[str, Any] | None:
    parsed = _as_record(value)
    if not parsed:
        return None
    return dict(validate_issue_execution_workspace_settings(parsed)) or None


def _resolve_mode(
    *,
    workspace_policy: dict[str, Any] | None,
    issue_settings: dict[str, Any] | None,
    issue_preference: str | None,
) -> str:
    issue_mode = issue_settings.get("mode") if issue_settings else None
    if isinstance(issue_preference, str) and issue_preference:
        issue_mode = issue_preference
    if issue_mode and issue_mode not in {"inherit", "reuse_existing"}:
        return str(issue_mode)
    if workspace_policy and workspace_policy.get("enabled"):
        default_mode = workspace_policy.get("defaultMode")
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
    workspace_policy: dict[str, Any] | None,
    issue_settings: dict[str, Any] | None,
    mode: str,
) -> str:
    strategy = None
    if issue_settings and isinstance(issue_settings.get("workspaceStrategy"), dict):
        strategy = issue_settings["workspaceStrategy"]
    elif workspace_policy and isinstance(
        workspace_policy.get("workspaceStrategy"), dict
    ):
        strategy = workspace_policy["workspaceStrategy"]
    strategy_type = strategy.get("type") if isinstance(strategy, dict) else None
    if isinstance(strategy_type, str) and strategy_type:
        return strategy_type
    if mode in {"isolated_workspace", "operator_branch"}:
        return "git_worktree"
    if mode == "agent_default":
        return "adapter_managed"
    return "project_primary"


def _strategy_record(
    *,
    workspace_policy: dict[str, Any] | None,
    issue_settings: dict[str, Any] | None,
) -> dict[str, Any]:
    if issue_settings and isinstance(issue_settings.get("workspaceStrategy"), dict):
        return cast(dict[str, Any], issue_settings["workspaceStrategy"])
    if workspace_policy and isinstance(workspace_policy.get("workspaceStrategy"), dict):
        return cast(dict[str, Any], workspace_policy["workspaceStrategy"])
    return {}


def _safe_branch_suffix(value: str) -> str:
    cleaned = value.strip().replace("\\", "-").replace("/", "-").replace(" ", "-")
    cleaned = "".join(
        char for char in cleaned if char.isalnum() or char in {".", "_", "-"}
    ).strip(".-")
    return cleaned or "workspace"


def _render_branch_template(template: str, *, issue: Issue) -> str:
    identifier = _safe_branch_suffix(str(getattr(issue, "identifier", "") or issue.id))
    return (
        template.replace("{issueId}", issue.id)
        .replace("{issueIdentifier}", identifier)
        .replace("{issueNumber}", str(getattr(issue, "issue_number", "") or ""))
    )


def _default_workspace_branch(*, issue: Issue) -> str:
    fallback = str(issue.id)[:8] if issue.id else "workspace"
    identifier = _safe_branch_suffix(str(getattr(issue, "identifier", "") or fallback))
    return f"octopus/{identifier}"


def _operator_branch_name(
    *, workspace_policy: dict[str, Any] | None, strategy: dict[str, Any]
) -> str:
    branch_policy = cast(
        dict[str, Any],
        workspace_policy.get("branchPolicy")
        if workspace_policy and isinstance(workspace_policy.get("branchPolicy"), dict)
        else {},
    )
    configured = (
        _string(strategy.get("operatorBranch"))
        or _string(branch_policy.get("operatorBranch"))
        or _string(strategy.get("branchName"))
    )
    return configured or "octopus/operator"


def _worktree_path(*, parent: Path, branch_name: str) -> Path:
    return parent / _safe_branch_suffix(branch_name)


def _normalize_ref_name(value: str) -> str:
    ref = value.strip()
    for prefix in ("refs/heads/", "origin/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix) :]
    return ref


def _current_git_branch(cwd: Path) -> str | None:
    try:
        inside = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--is-inside-work-tree"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        return None
    try:
        branch = subprocess.run(
            ["git", "-C", str(cwd), "branch", "--show-current"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if branch.returncode != 0:
        return None
    return branch.stdout.strip() or None


def _ensure_shared_workspace_branch_matches(workspace: ExecutionWorkspaceData) -> None:
    if (
        workspace["mode"] != "shared_workspace"
        or workspace["strategyType"] != "project_primary"
    ):
        return
    expected = _string(workspace["baseRef"])
    cwd = _string(workspace["cwd"])
    if not expected or not cwd:
        return
    actual = _current_git_branch(Path(cwd))
    if actual is None:
        return
    normalized_expected = _normalize_ref_name(expected)
    if _normalize_ref_name(actual) != normalized_expected:
        raise ValueError(
            "Shared workspace branch mismatch: expected "
            f"'{normalized_expected}' but current branch is '{actual}'. "
            "Octopus will not switch the project main worktree branch automatically."
        )


def _run_git(
    cwd: Path, *args: str, timeout: int = 20
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _require_git_success(
    cwd: Path, *args: str, timeout: int = 20
) -> subprocess.CompletedProcess[str]:
    result = _run_git(cwd, *args, timeout=timeout)
    if result.returncode != 0:
        command = "git -C <repo> " + " ".join(args)
        detail = (result.stderr or result.stdout or "Git command failed").strip()
        raise ValueError(f"{command} failed: {detail}")
    return result


def _is_git_worktree(path: Path) -> bool:
    if not path.exists():
        return False
    result = _run_git(path, "rev-parse", "--is-inside-work-tree")
    if result.returncode != 0 or result.stdout.strip() != "true":
        return False
    top_level = _run_git(path, "rev-parse", "--show-toplevel")
    if top_level.returncode != 0:
        return False
    try:
        return Path(top_level.stdout.strip()).resolve() == path.resolve()
    except OSError:
        return False


def _branch_exists(repo: Path, branch_name: str) -> bool:
    result = _run_git(
        repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch_name}"
    )
    return result.returncode == 0


def _is_git_repository(path: Path) -> bool:
    result = _run_git(path, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def _git_worktree_source_available(project_cwd: str | None) -> bool:
    if not project_cwd:
        return False
    try:
        return _is_git_repository(Path(project_cwd))
    except OSError:
        return False


def _workspace_metadata(workspace: ExecutionWorkspaceData) -> dict[str, Any]:
    metadata = workspace.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _workspace_warnings(workspace: ExecutionWorkspaceData) -> list[str]:
    metadata = _workspace_metadata(workspace)
    warnings = metadata.get("warnings")
    if not isinstance(warnings, list):
        return []
    return [str(warning) for warning in warnings if isinstance(warning, str)]


def _workspace_kind(workspace: ExecutionWorkspaceData) -> str:
    metadata = _workspace_metadata(workspace)
    explicit = _string(metadata.get("workspaceKind"))
    if explicit:
        return explicit
    if workspace.get("strategyType") == "organization_workspace":
        return "organization_scratch"
    if workspace.get("projectId"):
        return "project_execution"
    return "agent_scratch"


def _workspace_code_source_kind(workspace: ExecutionWorkspaceData) -> str:
    metadata = _workspace_metadata(workspace)
    explicit = _string(metadata.get("codeSourceKind"))
    if explicit:
        return explicit
    if workspace.get("strategyType") == "organization_workspace":
        return "none"
    if _string(workspace.get("repoUrl")) and not _string(workspace.get("cwd")):
        return "repo_url_pending_checkout"
    if _string(workspace.get("cwd")):
        return "local_cwd"
    return "none"


def _workspace_expected_branch(workspace: ExecutionWorkspaceData) -> str | None:
    metadata = _workspace_metadata(workspace)
    return (
        _string(metadata.get("expectedBranch"))
        or _string(workspace.get("branchName"))
        or _string(metadata.get("createdFromBranch"))
    )


def _workspace_target_ref(workspace: ExecutionWorkspaceData) -> str | None:
    metadata = _workspace_metadata(workspace)
    return _string(metadata.get("targetRef")) or _string(workspace.get("baseRef"))


def _workspace_source_repo(workspace: ExecutionWorkspaceData) -> Path | None:
    metadata = _workspace_metadata(workspace)
    source_cwd = _string(metadata.get("sourceWorkspaceCwd"))
    cwd = _string(workspace.get("cwd"))
    value = source_cwd or cwd
    return Path(value) if value else None


def _assert_workspace_branch_guard(
    workspace: ExecutionWorkspaceData, *, operation: str
) -> None:
    cwd = _string(workspace.get("cwd"))
    expected = _workspace_expected_branch(workspace)
    if not cwd or not expected:
        return
    actual = _current_git_branch(Path(cwd))
    if actual is None:
        return
    if _normalize_ref_name(actual) != _normalize_ref_name(expected):
        raise ValueError(
            f"Cannot {operation}: execution workspace branch mismatch. "
            f"Expected '{expected}' but current branch is '{actual}'."
        )


def _git_commit(cwd: Path, ref: str) -> str | None:
    result = _run_git(cwd, "rev-parse", "--verify", f"{ref}^{{commit}}")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _extract_merge_conflict_files(output: str) -> list[str]:
    files: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        lowered = stripped.lower()
        if lowered.startswith("changed in both") or lowered.startswith("added in both"):
            parts = stripped.split()
            if parts:
                candidate = parts[-1]
                if candidate not in files:
                    files.append(candidate)
        elif lowered.startswith("<<<<<<<"):
            continue
    return files


def _git_dirty(cwd: Path, *, ignore_octopus: bool = False) -> bool:
    args = ["status", "--porcelain"]
    if ignore_octopus:
        args.extend(["--", ".", ":!/.octopus", ":!.octopus"])
    status = _run_git(cwd, *args)
    return status.returncode == 0 and bool(status.stdout.strip())


def _remote_http_url(fetch_url: str) -> str:
    value = fetch_url.strip()
    if value.startswith("git@") and ":" in value:
        host, path = value[4:].split(":", 1)
        return f"https://{host}/{path.removesuffix('.git')}"
    return value.removesuffix(".git")


def _ensure_git_worktree(workspace: ExecutionWorkspaceData) -> None:
    cwd_value = _string(workspace["cwd"])
    branch_name = _string(workspace["branchName"])
    metadata = workspace.get("metadata") or {}
    source_cwd = (
        _string(metadata.get("sourceWorkspaceCwd"))
        if isinstance(metadata, dict)
        else None
    )
    base_ref = _string(workspace["baseRef"]) or "HEAD"
    if not cwd_value or not branch_name or not source_cwd:
        raise ValueError(
            "Git worktree workspace is missing cwd, branchName, or sourceWorkspaceCwd"
        )
    worktree = Path(cwd_value).resolve()
    source_repo = Path(source_cwd).resolve()
    _require_git_success(source_repo, "rev-parse", "--is-inside-work-tree")
    if _is_git_worktree(worktree):
        current = _current_git_branch(worktree)
        if current and _normalize_ref_name(current) != _normalize_ref_name(branch_name):
            raise ValueError(
                "Existing worktree branch mismatch: expected "
                f"'{branch_name}' but current branch is '{current}'."
            )
        return
    if worktree.exists() and any(worktree.iterdir()):
        raise ValueError(
            f"Git worktree path '{worktree}' exists but is not an empty Git worktree"
        )
    worktree.parent.mkdir(parents=True, exist_ok=True)
    if _branch_exists(source_repo, branch_name):
        result = _run_git(
            source_repo, "worktree", "add", str(worktree), branch_name, timeout=60
        )
    else:
        result = _run_git(
            source_repo,
            "worktree",
            "add",
            "-b",
            branch_name,
            str(worktree),
            base_ref,
            timeout=60,
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "git worktree add failed").strip()
        raise ValueError(f"Failed to prepare Git worktree '{worktree}': {detail}")
    if not _is_git_worktree(worktree):
        raise ValueError(f"Prepared path '{worktree}' is not a Git worktree")


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

    async def workspace_status(self, workspace_id: str) -> dict[str, Any] | None:
        workspace = await self.get_execution_workspace(workspace_id)
        if workspace is None:
            return None
        operations = await list_workspace_operations_for_execution_workspace(
            self._session, workspace_id
        )
        running_adapter = [
            operation
            for operation in operations
            if operation.status == "running"
            and isinstance(operation.metadata_json, dict)
            and operation.metadata_json.get("adapterExecution")
        ]
        git_status = self._git_status_for_workspace(workspace)
        return {
            "workspace": workspace,
            "git": git_status,
            "lease": {
                "locked": bool(running_adapter),
                "operationId": running_adapter[0].id if running_adapter else None,
                "runId": running_adapter[0].heartbeat_run_id
                if running_adapter
                else None,
            },
            "canArchive": not running_adapter
            and not bool((git_status or {}).get("dirty")),
            "operations": [self._to_operation(row) for row in operations[:10]],
        }

    async def git_diff_for_workspace(self, workspace_id: str) -> dict[str, Any] | None:
        workspace = await self.get_execution_workspace(workspace_id)
        if workspace is None:
            return None
        cwd = self._workspace_git_cwd(workspace)
        if cwd is None:
            return {
                "available": False,
                "diff": "",
                "error": "Workspace is not a Git worktree",
            }
        result = _run_git(cwd, "diff", "--stat")
        stat = result.stdout if result.returncode == 0 else ""
        diff = _run_git(cwd, "diff", "--", timeout=20)
        return {
            "available": diff.returncode == 0,
            "stat": stat,
            "diff": diff.stdout if diff.returncode == 0 else "",
            "error": None
            if diff.returncode == 0
            else (diff.stderr or diff.stdout).strip(),
        }

    async def merge_preview(
        self, workspace_id: str, *, target_ref: str | None = None
    ) -> dict[str, Any] | None:
        workspace = await self.get_execution_workspace(workspace_id)
        if workspace is None:
            return None
        if workspace["mode"] == "shared_workspace":
            return {
                "available": False,
                "canMerge": False,
                "conflict": False,
                "targetRef": target_ref or _workspace_target_ref(workspace),
                "sourceBranch": _current_git_branch(Path(workspace["cwd"]))
                if workspace["cwd"]
                else None,
                "error": "Shared workspace already runs in the project worktree; use diff/push instead of merge.",
                "preview": "",
                "conflictFiles": [],
            }
        cwd = self._workspace_git_cwd(workspace)
        if cwd is None:
            raise ValueError("Workspace is not a Git worktree")
        _assert_workspace_branch_guard(workspace, operation="preview merge")
        source_repo = _workspace_source_repo(workspace) or cwd
        target = target_ref or _workspace_target_ref(workspace)
        if not target:
            raise ValueError("Merge preview requires a target ref")
        source_commit = _git_commit(cwd, "HEAD")
        target_commit = _git_commit(source_repo, target)
        if not source_commit:
            raise ValueError("Cannot resolve execution workspace HEAD")
        if not target_commit:
            raise ValueError(f"Cannot resolve target ref '{target}'")
        result = _run_git(
            source_repo,
            "merge-tree",
            "--write-tree",
            target_commit,
            source_commit,
            timeout=60,
        )
        unsupported = (
            result.returncode != 0
            and "unknown option" in (result.stderr or result.stdout).lower()
        )
        if unsupported:
            base = _run_git(source_repo, "merge-base", target_commit, source_commit)
            if base.returncode != 0 or not base.stdout.strip():
                raise ValueError(
                    (base.stderr or base.stdout or "git merge-base failed").strip()
                )
            result = _run_git(
                source_repo,
                "merge-tree",
                base.stdout.strip(),
                target_commit,
                source_commit,
                timeout=60,
            )
            output = (
                result.stdout
                if result.returncode == 0
                else result.stderr or result.stdout
            )
            conflict = "<<<<<<<" in output or "changed in both" in output.lower()
        else:
            output = (
                result.stdout
                if result.returncode == 0
                else result.stderr or result.stdout
            )
            conflict = result.returncode != 0
        conflict_files = _extract_merge_conflict_files(output)
        return {
            "available": True,
            "canMerge": result.returncode == 0 and not conflict,
            "conflict": conflict,
            "conflictFiles": conflict_files,
            "targetRef": target,
            "targetCommit": target_commit,
            "sourceBranch": _current_git_branch(cwd),
            "sourceCommit": source_commit,
            "preview": output,
            "error": None
            if result.returncode == 0 and not conflict
            else output.strip(),
        }

    async def merge_workspace(
        self, workspace_id: str, *, target_ref: str | None = None
    ) -> dict[str, Any] | None:
        workspace = await self.get_execution_workspace(workspace_id)
        if workspace is None:
            return None
        await self._ensure_no_running_adapter_operation(workspace_id, action="merged")
        if workspace["mode"] == "shared_workspace":
            raise ValueError(
                "Shared workspace changes are already in the project worktree; merge is not applicable"
            )
        cwd = self._workspace_git_cwd(workspace)
        if cwd is None:
            raise ValueError("Workspace is not a Git worktree")
        _assert_workspace_branch_guard(workspace, operation="merge")
        source_repo = _workspace_source_repo(workspace)
        if source_repo is None or not _is_git_repository(source_repo):
            raise ValueError("Merge requires a source project Git repository")
        target = target_ref or _workspace_target_ref(workspace)
        if not target:
            raise ValueError("Merge requires a target ref")
        source_commit = _git_commit(cwd, "HEAD")
        if not source_commit:
            raise ValueError("Cannot resolve execution workspace HEAD")
        current_target_branch = _current_git_branch(source_repo)
        normalized_target = _normalize_ref_name(target)
        if _normalize_ref_name(current_target_branch or "") != normalized_target:
            raise ValueError(
                "Cannot merge because target ref is not the current project branch. "
                f"Expected project workspace to already be on '{normalized_target}' but it is on '{current_target_branch}'. "
                "Octopus will not checkout the target branch automatically."
            )
        if _git_dirty(source_repo, ignore_octopus=True):
            raise ValueError(
                "Cannot merge because the target project workspace has uncommitted changes"
            )
        preview = await self.merge_preview(workspace_id, target_ref=target)
        if preview is None or not preview.get("canMerge"):
            raise ValueError("Cannot merge because merge preview is not clean")
        result = _run_git(
            source_repo,
            "merge",
            "--no-ff",
            source_commit,
            "-m",
            f"Merge execution workspace {workspace_id}",
            timeout=120,
        )
        if result.returncode != 0:
            raise ValueError(
                (result.stderr or result.stdout or "git merge failed").strip()
            )
        merged_head = _git_commit(source_repo, "HEAD")
        await self.update_execution_workspace(
            workspace_id,
            {
                "status": "merged",
                "metadata": {
                    **_workspace_metadata(workspace),
                    "mergedAt": datetime.now(UTC).isoformat(),
                    "mergedInto": normalized_target,
                    "mergedCommit": merged_head,
                },
            },
        )
        return {
            "merged": True,
            "targetRef": normalized_target,
            "sourceCommit": source_commit,
            "mergedCommit": merged_head,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    async def prepare_pull_request(
        self,
        workspace_id: str,
        *,
        remote: str = "origin",
        target_ref: str | None = None,
    ) -> dict[str, Any] | None:
        workspace = await self.get_execution_workspace(workspace_id)
        if workspace is None:
            return None
        cwd = self._workspace_git_cwd(workspace)
        branch = _string(workspace["branchName"])
        if cwd is None or not branch:
            raise ValueError("Workspace does not have a Git branch for PR preparation")
        _assert_workspace_branch_guard(workspace, operation="prepare PR")
        target = target_ref or _workspace_target_ref(workspace) or "main"
        remote_result = _run_git(cwd, "remote", "get-url", remote)
        remote_url = (
            remote_result.stdout.strip() if remote_result.returncode == 0 else None
        )
        web_url = _remote_http_url(remote_url) if remote_url else None
        compare_url = f"{web_url}/compare/{target}...{branch}" if web_url else None
        command = f"gh pr create --base {target} --head {branch}"
        return {
            "remote": remote,
            "remoteUrl": remote_url,
            "sourceBranch": branch,
            "targetRef": target,
            "compareUrl": compare_url,
            "command": command,
        }

    async def create_pull_request(
        self,
        workspace_id: str,
        *,
        remote: str = "origin",
        target_ref: str | None = None,
        title: str | None = None,
        body: str | None = None,
    ) -> dict[str, Any] | None:
        workspace = await self.get_execution_workspace(workspace_id)
        if workspace is None:
            return None
        plan = await self.prepare_pull_request(
            workspace_id, remote=remote, target_ref=target_ref
        )
        assert plan is not None
        cwd = self._workspace_git_cwd(workspace)
        if cwd is None:
            raise ValueError("Workspace is not a Git worktree")
        args = [
            "pr",
            "create",
            "--base",
            str(plan["targetRef"]),
            "--head",
            str(plan["sourceBranch"]),
        ]
        if title:
            args.extend(["--title", title])
        else:
            args.extend(["--fill"])
        if body:
            args.extend(["--body", body])
        try:
            result = subprocess.run(
                ["gh", *args],
                cwd=str(cwd),
                check=False,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise ValueError("GitHub CLI 'gh' is not installed or not on PATH") from exc
        except subprocess.TimeoutExpired as exc:
            raise ValueError("GitHub CLI timed out while creating PR") from exc
        if result.returncode != 0:
            raise ValueError(
                (result.stderr or result.stdout or "gh pr create failed").strip()
            )
        pr_url = (
            result.stdout.strip().splitlines()[-1] if result.stdout.strip() else None
        )
        return {
            "created": True,
            "url": pr_url,
            "remote": remote,
            "sourceBranch": plan["sourceBranch"],
            "targetRef": plan["targetRef"],
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    async def abandon_workspace(
        self, workspace_id: str
    ) -> ExecutionWorkspaceData | None:
        workspace = await self.get_execution_workspace(workspace_id)
        if workspace is None:
            return None
        await self._ensure_no_running_adapter_operation(
            workspace_id, action="abandoned"
        )
        return await self.update_execution_workspace(
            workspace_id,
            {
                "status": "abandoned",
                "metadata": {
                    **_workspace_metadata(workspace),
                    "abandonedAt": datetime.now(UTC).isoformat(),
                },
            },
        )

    async def cleanup_workspace(
        self, workspace_id: str, *, discard_dirty: bool = False
    ) -> ExecutionWorkspaceData | None:
        workspace = await self.get_execution_workspace(workspace_id)
        if workspace is None:
            return None
        if workspace["mode"] == "shared_workspace":
            raise ValueError("Cleanup is not allowed for shared project workspaces")
        if discard_dirty:
            cwd = self._workspace_git_cwd(workspace)
            if cwd is not None and _git_dirty(cwd):
                _assert_workspace_branch_guard(
                    workspace, operation="discard dirty changes"
                )
                _require_git_success(cwd, "reset", "--hard", timeout=60)
                _require_git_success(cwd, "clean", "-fd", timeout=60)
        archived = await self.archive_workspace(workspace_id)
        if archived is None:
            return None
        metadata = _workspace_metadata(archived)
        return await self.update_execution_workspace(
            workspace_id,
            {
                "status": archived["status"],
                "metadata": {
                    **metadata,
                    "cleanedAt": datetime.now(UTC).isoformat(),
                    "discardedDirtyChanges": discard_dirty,
                },
            },
        )

    async def push_workspace_branch(
        self, workspace_id: str, *, remote: str = "origin", set_upstream: bool = True
    ) -> dict[str, Any] | None:
        workspace = await self.get_execution_workspace(workspace_id)
        if workspace is None:
            return None
        cwd = self._workspace_git_cwd(workspace)
        branch = _string(workspace["branchName"])
        if cwd is None or not branch:
            raise ValueError("Workspace does not have a Git branch to push")
        _assert_workspace_branch_guard(workspace, operation="push")
        args = ["push"]
        if set_upstream:
            args.append("--set-upstream")
        args.extend([remote, branch])
        result = _run_git(cwd, *args, timeout=120)
        if result.returncode != 0:
            raise ValueError(
                (result.stderr or result.stdout or "git push failed").strip()
            )
        return {
            "pushed": True,
            "remote": remote,
            "branch": branch,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    async def archive_workspace(
        self, workspace_id: str
    ) -> ExecutionWorkspaceData | None:
        workspace = await self.get_execution_workspace(workspace_id)
        if workspace is None:
            return None
        await self._ensure_workspace_can_archive(workspace_id)
        _assert_workspace_branch_guard(workspace, operation="archive")
        if workspace["providerType"] == "git_worktree" and workspace["cwd"]:
            cwd = Path(workspace["cwd"])
            if _is_git_worktree(cwd):
                metadata = workspace.get("metadata") or {}
                source_cwd = (
                    _string(metadata.get("sourceWorkspaceCwd"))
                    if isinstance(metadata, dict)
                    else None
                )
                git_cwd = Path(source_cwd) if source_cwd else cwd.parent
                result = _run_git(git_cwd, "worktree", "remove", str(cwd), timeout=60)
                if result.returncode != 0:
                    raise ValueError(
                        (
                            result.stderr
                            or result.stdout
                            or "git worktree remove failed"
                        ).strip()
                    )
        return await self.update_execution_workspace(
            workspace_id,
            {"status": "archived", "cleanupReason": "explicit_archive"},
        )

    def _workspace_git_cwd(self, workspace: ExecutionWorkspaceData) -> Path | None:
        cwd = _string(workspace["cwd"])
        if not cwd:
            return None
        path = Path(cwd)
        return path if _is_git_worktree(path) else None

    def _git_status_for_workspace(
        self, workspace: ExecutionWorkspaceData
    ) -> dict[str, Any] | None:
        cwd = self._workspace_git_cwd(workspace)
        if cwd is None:
            return None
        branch = _current_git_branch(cwd)
        status = _run_git(cwd, "status", "--porcelain=v1", "--branch")
        if status.returncode != 0:
            return {
                "available": False,
                "error": (status.stderr or status.stdout).strip(),
            }
        lines = [line for line in status.stdout.splitlines() if line]
        dirty_lines = [line for line in lines if not line.startswith("## ")]
        return {
            "available": True,
            "branch": branch,
            "dirty": bool(dirty_lines),
            "entries": dirty_lines,
            "summary": lines[0] if lines and lines[0].startswith("## ") else None,
        }

    async def update_execution_workspace(
        self, workspace_id: str, fields: dict[str, Any]
    ) -> ExecutionWorkspaceData | None:
        if fields.get("status") == "archived":
            await self._ensure_workspace_can_archive(workspace_id)
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
        existing: ExecutionWorkspace | None = None
        if issue.execution_workspace_id:
            existing_row = await get_execution_workspace_by_id(
                self._session, issue.execution_workspace_id
            )
            if existing_row is not None and existing_row.org_id == issue.org_id:
                existing = existing_row
        if existing is not None and issue.project_id is None:
            self._validate_existing_execution_workspace(existing)
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
                    f'organization scratch workspace "{org_root}".'
                ),
            )

        project = await get_project_by_id(self._session, issue.project_id)
        if project is None or project.org_id != issue.org_id:
            return None
        issue_settings = _parse_issue_settings(issue.execution_workspace_settings)
        requested_workspace_id = issue.project_workspace_id
        if (
            requested_workspace_id is None
            and existing is not None
            and existing.project_id == project.id
        ):
            requested_workspace_id = existing.project_workspace_id
        project_workspace = await self._resolve_project_workspace(
            project_id=project.id,
            requested_id=requested_workspace_id,
        )
        if issue.project_workspace_id and project_workspace is None:
            raise ValueError(
                "Issue project workspace does not exist in the selected project."
            )
        if project_workspace is None:
            org_root = self._org_workspace_root(issue.org_id)
            return self._organization_workspace_fallback(
                issue,
                cwd=str(org_root),
                warning=(
                    "Project has no workspace configured. Run will start in "
                    f'organization scratch workspace "{org_root}".'
                ),
            )
        workspace_policy = _parse_workspace_policy(
            project_workspace.execution_workspace_policy
        )
        mode = _resolve_mode(
            workspace_policy=workspace_policy,
            issue_settings=issue_settings,
            issue_preference=issue.execution_workspace_preference,
        )
        if mode == "agent_default":
            return None
        strategy_type = _resolve_strategy_type(
            workspace_policy=workspace_policy,
            issue_settings=issue_settings,
            mode=mode,
        )
        project_workspace_id = project_workspace.id
        strategy = _strategy_record(
            workspace_policy=workspace_policy,
            issue_settings=issue_settings,
        )
        project_had_configured_cwd = bool(_string(project_workspace.cwd))
        project_cwd = await self._ensure_project_checkout(
            org_id=issue.org_id,
            project_id=project.id,
            project_workspace=project_workspace,
        )
        project_code_source_kind = self._project_code_source_kind(
            org_id=issue.org_id,
            project_id=project.id,
            cwd=project_cwd,
            had_configured_cwd=project_had_configured_cwd,
            workspace_id=project_workspace.id,
            repo_url=_string(project_workspace.repo_url),
        )
        project_repo_url = _string(project_workspace.repo_url)
        project_base_ref = _string(project_workspace.default_ref) or _string(
            project_workspace.repo_ref
        )
        execution_cwd: str | None = None
        execution_repo_url: str | None = None
        execution_base_ref: str | None = None
        execution_branch_name: str | None = None
        execution_metadata: dict[str, Any] = {
            "resolvedForIssueId": issue.id,
            "resolvedMode": mode,
        }
        warnings: list[str] = []
        if not project_cwd:
            raise ValueError(
                "Project workspace requires a local cwd or repo URL before it can execute tasks."
            )
        elif mode == "shared_workspace":
            execution_cwd = project_cwd
            execution_repo_url = project_repo_url
            execution_base_ref = project_base_ref
        elif strategy_type == "git_worktree":
            branch_template = _string(strategy.get("branchTemplate"))
            if mode == "operator_branch":
                execution_branch_name = _operator_branch_name(
                    workspace_policy=workspace_policy, strategy=strategy
                )
                execution_metadata["operatorWorkspace"] = True
            else:
                execution_branch_name = (
                    _render_branch_template(branch_template, issue=issue)
                    if branch_template
                    else _default_workspace_branch(issue=issue)
                )
            worktree_parent_value = _string(strategy.get("worktreeParentDir"))
            if worktree_parent_value:
                worktree_parent = Path(worktree_parent_value)
            else:
                source_path = Path(project_cwd)
                worktree_parent = (
                    source_path.parent / "worktrees"
                    if source_path.name == "checkout"
                    else source_path / ".octopus" / "worktrees"
                )
            execution_cwd = str(
                _worktree_path(
                    parent=worktree_parent, branch_name=execution_branch_name
                )
            )
            execution_repo_url = project_repo_url
            execution_base_ref = _string(strategy.get("baseRef")) or project_base_ref
            execution_metadata.update(
                {
                    "sourceWorkspaceCwd": project_cwd,
                    "sourceWorkspaceRepoUrl": project_repo_url,
                }
            )
            if not _git_worktree_source_available(project_cwd):
                if mode == "operator_branch" or project_repo_url:
                    raise ValueError(
                        "Git worktree mode requires the project cwd to be an existing Git repository. "
                        "Octopus will not create a fake git_worktree directory."
                    )
                raise ValueError(
                    "Isolated workspace mode requires the project cwd to be an existing Git repository. "
                    "Octopus will not create a local_fs fallback for isolated workspaces."
                )
        execution_metadata.update(
            {
                "workspaceKind": "project_execution",
                "codeSourceKind": project_code_source_kind,
                "warnings": warnings,
            }
        )
        if project_cwd:
            created_from_branch = _current_git_branch(Path(project_cwd))
            created_from_head = _git_commit(Path(project_cwd), "HEAD")
            if created_from_branch:
                execution_metadata["createdFromBranch"] = created_from_branch
            if created_from_head:
                execution_metadata["createdFromHead"] = created_from_head
        expected_branch = execution_branch_name
        if mode == "shared_workspace" and execution_base_ref:
            expected_branch = execution_base_ref
        if expected_branch:
            execution_metadata["expectedBranch"] = expected_branch
        if execution_base_ref:
            execution_metadata["targetRef"] = execution_base_ref
        reusable = await self._find_reusable_execution_workspace(
            org_id=issue.org_id,
            project_id=project.id,
            project_workspace_id=project_workspace_id,
            issue_id=issue.id,
            mode=mode,
            branch_name=execution_branch_name,
        )
        bound_existing = (
            existing
            if existing is not None
            and existing.project_id == project.id
            and existing.project_workspace_id == project_workspace_id
            else None
        )
        if bound_existing is not None:
            self._validate_existing_execution_workspace(bound_existing)
        row = bound_existing or reusable
        workspace_fields = {
            "org_id": issue.org_id,
            "project_id": project.id,
            "project_workspace_id": project_workspace_id,
            "source_issue_id": issue.id if mode == "isolated_workspace" else None,
            "mode": mode,
            "strategy_type": strategy_type,
            "name": f"{project.name} workspace",
            "status": "active",
            "cwd": execution_cwd,
            "repo_url": execution_repo_url,
            "base_ref": execution_base_ref,
            "branch_name": execution_branch_name,
            "provider_type": "git_worktree"
            if strategy_type == "git_worktree"
            else "local_fs",
            "metadata_json": execution_metadata,
        }
        if row is None:
            row = await create_execution_workspace(self._session, workspace_fields)
        else:
            patch: dict[str, Any] = {"last_used_at": datetime.now(UTC)}
            for key, value in workspace_fields.items():
                if key in {"org_id", "project_id", "source_issue_id"}:
                    continue
                if getattr(row, key) != value:
                    patch[key] = value
            row = await update_execution_workspace(self._session, row.id, patch) or row
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

    def _validate_existing_execution_workspace(self, row: ExecutionWorkspace) -> None:
        if row.cwd and not Path(row.cwd).exists():
            raise ValueError(f"Execution workspace cwd '{row.cwd}' does not exist.")
        if row.provider_type == "git_worktree":
            metadata = row.metadata_json if isinstance(row.metadata_json, dict) else {}
            source_cwd = _string(metadata.get("sourceWorkspaceCwd"))
            if not row.cwd or not row.branch_name or not source_cwd:
                raise ValueError(
                    "Git worktree execution workspace is missing cwd, branchName, "
                    "or sourceWorkspaceCwd. Repair or recreate the workspace."
                )
            if Path(row.cwd).exists() and not _is_git_worktree(Path(row.cwd)):
                raise ValueError(
                    f"Execution workspace cwd '{row.cwd}' is not a Git worktree."
                )

    async def _ensure_project_checkout(
        self,
        *,
        org_id: str,
        project_id: str,
        project_workspace: Any,
    ) -> str | None:
        cwd = _string(project_workspace.cwd)
        if cwd:
            path = Path(cwd)
            if not path.exists():
                raise ValueError(f"Project workspace cwd '{cwd}' does not exist.")
            if not path.is_dir():
                raise ValueError(f"Project workspace cwd '{cwd}' is not a directory.")
            return cwd
        repo_url = _string(project_workspace.repo_url)
        if not repo_url:
            return None
        checkout = self._managed_project_checkout_path(
            org_id, project_id, project_workspace.id
        )
        if checkout.exists():
            if _is_git_repository(checkout):
                await update_project_workspace(
                    self._session, project_workspace.id, {"cwd": str(checkout)}
                )
                return str(checkout)
            if any(checkout.iterdir()):
                raise ValueError(
                    f"Managed project checkout path '{checkout}' exists but is not a Git repository"
                )
        checkout.parent.mkdir(parents=True, exist_ok=True)
        ref = _string(project_workspace.default_ref) or _string(
            project_workspace.repo_ref
        )
        args = ["clone"]
        if ref:
            args.extend(["--branch", ref])
        args.extend([repo_url, str(checkout)])
        result = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "git clone failed").strip()
            raise ValueError(f"Failed to prepare managed project checkout: {detail}")
        await update_project_workspace(
            self._session, project_workspace.id, {"cwd": str(checkout)}
        )
        return str(checkout)

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
        _ensure_shared_workspace_branch_matches(workspace)
        workspace = await self._ensure_managed_workspace_paths(workspace)
        services = await self.list_runtime_services_for_workspace(workspace["id"])
        org_root = self._org_workspace_root(issue.org_id)
        agents_dir = org_root / "agents"
        skills_dir = org_root / "skills"
        plans_dir = org_root / "plans"
        artifacts_dir = org_root / "artifacts"
        for path in (
            org_root,
            agents_dir,
            skills_dir,
            plans_dir,
            artifacts_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
        workspace = self._with_organization_workspace_paths(
            workspace=workspace,
            org_root=org_root,
            agents_dir=agents_dir,
            skills_dir=skills_dir,
            plans_dir=plans_dir,
            artifacts_dir=artifacts_dir,
        )
        workspace_cwd = _string(workspace.get("cwd"))
        if workspace_cwd:
            issue_artifacts_dir = (artifacts_dir / "issues" / issue.id).resolve()
            issue_artifacts_dir.mkdir(parents=True, exist_ok=True)
            workspace = cast(
                ExecutionWorkspaceData,
                {**workspace, "issueArtifactsDir": str(issue_artifacts_dir)},
            )
        workspace_env = self._workspace_env(
            workspace=workspace,
            org_root=org_root,
            agents_dir=agents_dir,
            skills_dir=skills_dir,
            plans_dir=plans_dir,
            artifacts_dir=artifacts_dir,
        )
        runtime_context = {
            "octopusWorkspace": workspace,
            "octopusWorkspaces": [workspace],
            "octopusRuntimeServiceIntents": [],
            "octopusRuntimeServices": services,
            "env": workspace_env,
        }
        runtime_context["env"]["OCTOPUS_RUNTIME_SERVICES_JSON"] = _json_dump(services)
        return {
            "issueId": issue.id,
            "projectId": issue.project_id,
            "projectWorkspaceId": workspace["projectWorkspaceId"],
            "executionWorkspaceId": workspace["id"],
            "workspace": runtime_context,
        }

    async def prepare_runtime_context_for_heartbeat(
        self,
        run_id: str,
        context_snapshot: dict[str, Any] | None,
        *,
        org_id: str,
        agent_workspace_key: str,
    ) -> dict[str, Any]:
        """Resolve an issue workspace or isolate an unassigned heartbeat.

        Timer heartbeats frequently have no issue context. They must never leave
        ``cwd`` unset because local adapters would then inherit the server's
        working directory.
        """
        issue_context = await self.prepare_runtime_context_for_run(
            run_id, context_snapshot
        )
        if issue_context is not None:
            return issue_context

        org_root = self._org_workspace_root(org_id)
        agents_dir = org_root / "agents"
        skills_dir = org_root / "skills"
        plans_dir = org_root / "plans"
        artifacts_dir = org_root / "artifacts"
        heartbeat_root = agent_heartbeat_workspace_root(org_id, agent_workspace_key)
        for path in (
            org_root,
            agents_dir,
            skills_dir,
            plans_dir,
            artifacts_dir,
            heartbeat_root,
        ):
            path.mkdir(parents=True, exist_ok=True)

        fallback = self._organization_workspace_fallback(
            _IssueWorkspaceFallback(org_id=org_id, id=run_id),
            cwd=str(heartbeat_root),
            warning=(
                "Heartbeat has no issue workspace. Run is isolated in the "
                f'read-only agent heartbeat workspace "{heartbeat_root}".'
            ),
        )
        fallback.update(
            {
                "mode": "agent_default",
                "strategyType": "adapter_managed",
                "name": "Agent heartbeat workspace",
                "gitWritePolicy": "read_only",
                "metadata": {
                    **(fallback.get("metadata") or {}),
                    "fallback": "agent_heartbeat_workspace",
                    "gitWritePolicy": "read_only",
                },
            }
        )
        workspace = self._with_organization_workspace_paths(
            workspace=fallback,
            org_root=org_root,
            agents_dir=agents_dir,
            skills_dir=skills_dir,
            plans_dir=plans_dir,
            artifacts_dir=artifacts_dir,
        )
        workspace_env = self._workspace_env(
            workspace=workspace,
            org_root=org_root,
            agents_dir=agents_dir,
            skills_dir=skills_dir,
            plans_dir=plans_dir,
            artifacts_dir=artifacts_dir,
        )
        workspace_env["OCTOPUS_GIT_WRITE_POLICY"] = "read_only"
        runtime_context = {
            "octopusWorkspace": workspace,
            "octopusWorkspaces": [workspace],
            "octopusRuntimeServiceIntents": [],
            "octopusRuntimeServices": [],
            "env": workspace_env,
        }
        return {
            "executionWorkspaceId": None,
            "projectWorkspaceId": None,
            "workspace": runtime_context,
            "workspaceFallback": "agent_heartbeat_workspace",
            "gitWritePolicy": "read_only",
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
        for path in (
            org_root,
            agents_dir,
            skills_dir,
            plans_dir,
            artifacts_dir,
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
            )
        )

        workspace_env = self._workspace_env(
            workspace=cast(ExecutionWorkspaceData, workspace),
            org_root=org_root,
            agents_dir=agents_dir,
            skills_dir=skills_dir,
            plans_dir=plans_dir,
            artifacts_dir=artifacts_dir,
        )
        runtime_context = {
            "octopusWorkspace": workspace,
            "octopusWorkspaces": [workspace],
            "octopusRuntimeServiceIntents": [],
            "octopusRuntimeServices": [],
            "env": workspace_env,
        }
        runtime_context["env"]["OCTOPUS_RUNTIME_SERVICES_JSON"] = "[]"
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
            workspace_context.get("octopusWorkspace")
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
            workspace_context.get("octopusWorkspace")
            if isinstance(workspace_context, dict)
            else None
        )
        existing = await list_issue_work_products(self._session, issue.id)
        seen_external_ids = {row.external_id for row in existing if row.external_id}
        stored: list[IssueWorkProductData] = []
        for product in products:
            if not isinstance(product, dict):
                continue
            title = _string(product.get("title"))
            product_type = _string(product.get("type"))
            provider = _string(product.get("provider")) or "octopus"
            if not title or not product_type:
                continue
            external_id = _string(product.get("externalId"))
            # Idempotent capture: a re-scan (backfill after a transient failure)
            # must not duplicate an already-registered artifact for this issue.
            if external_id and external_id in seen_external_ids:
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
            if external_id:
                seen_external_ids.add(external_id)
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
            workspace_context.get("octopusWorkspace")
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
            artifacts_dir = _string(workspace_env.get("OCTOPUS_ORG_ARTIFACTS_DIR"))
        if not artifacts_dir:
            default_artifacts_dir = worktree_root / "artifacts"
            if default_artifacts_dir.is_dir():
                artifacts_dir = str(default_artifacts_dir)
        artifacts_root = Path(artifacts_dir).resolve() if artifacts_dir else None
        if artifacts_dir:
            assert artifacts_root is not None
        workspace_mode = _string(workspace.get("mode"))
        strategy_type = _string(workspace.get("strategyType"))
        shared_workspace = workspace_mode == "shared_workspace" or strategy_type in {
            "project_primary",
            "organization_workspace",
        }
        if shared_workspace:
            issue_artifacts_dir = _string(workspace.get("issueArtifactsDir"))
            issue_artifacts_root = (
                Path(issue_artifacts_dir).resolve()
                if issue_artifacts_dir
                else (artifacts_root / "issues" / issue.id).resolve()
                if artifacts_root is not None
                else None
            )
            if issue_artifacts_root is not None and issue_artifacts_root.is_dir():
                scan_roots.append(("issue_artifacts_scan", issue_artifacts_root))
        else:
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
                        "provider": "octopus",
                        "externalId": f"{source}:{workspace_ref}:{rel_path}",
                        "status": "active",
                        "reviewState": "none",
                        "isPrimary": False,
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
        # Pick the primary deliverable from THIS run's own worktree (newest such
        # file), not "the first file scanned" — which, because the shared org
        # artifacts dir is scanned first and oldest-first, used to surface a stale
        # file from another task as the headline product. Files are appended in
        # ascending mtime per root, so the last worktree-sourced product is newest.
        primary_idx = next(
            (
                i
                for i in range(len(products) - 1, -1, -1)
                if products[i]["metadata"].get("source") == "execution_workspace_scan"
            ),
            len(products) - 1,
        )
        products[primary_idx]["isPrimary"] = True
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
        # Reuse an existing asset with identical content instead of re-archiving:
        # the same generated file is scanned/captured repeatedly (shared org
        # artifacts dir, re-runs), and a fresh put_file each time would mint a new
        # asset id and waste storage for byte-identical content.
        digest = hashlib.sha256(content).hexdigest()
        asset = await get_asset_by_sha256(self._session, org_id, digest)
        if asset is None:
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

    async def _ensure_no_running_adapter_operation(
        self, workspace_id: str, *, action: str
    ) -> None:
        operations = await list_workspace_operations_for_execution_workspace(
            self._session, workspace_id
        )
        for operation in operations:
            metadata = operation.metadata_json or {}
            if (
                operation.status == "running"
                and isinstance(metadata, dict)
                and metadata.get("adapterExecution")
            ):
                raise ValueError(
                    f"Execution workspace cannot be {action} while an adapter operation is running."
                )

    async def _ensure_workspace_can_archive(self, workspace_id: str) -> None:
        row = await get_execution_workspace_by_id(self._session, workspace_id)
        if row is None:
            return
        await self._ensure_no_running_adapter_operation(workspace_id, action="archived")
        if row.provider_type == "git_worktree" and row.cwd:
            cwd = Path(row.cwd)
            if _is_git_worktree(cwd):
                status = _run_git(cwd, "status", "--porcelain")
                if status.returncode == 0 and status.stdout.strip():
                    raise ValueError(
                        "Execution workspace cannot be archived because the Git worktree has uncommitted changes."
                    )

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
                ensure_octopus_workspace_operation_log_dir(),
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
        requested_id: str | None,
    ) -> Any | None:
        workspaces = await list_project_workspaces(self._session, project_id)
        if requested_id:
            return next(
                (workspace for workspace in workspaces if workspace.id == requested_id),
                None,
            )
        primary = next(
            (workspace for workspace in workspaces if workspace.is_primary), None
        )
        if not workspaces:
            return None
        if primary is None:
            raise ValueError(
                "Project has workspaces but no default workspace. Select one before running tasks."
            )
        return primary

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
        if workspace["providerType"] == "git_worktree":
            _ensure_git_worktree(workspace)
        else:
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

    def _managed_project_checkout_path(
        self, org_id: str, project_id: str, workspace_id: str
    ) -> Path:
        return (
            self._org_workspace_root(org_id)
            / "projects"
            / _safe_branch_suffix(project_id[:8])
            / _safe_branch_suffix(workspace_id[:8])
            / "checkout"
        ).resolve()

    def _project_code_source_kind(
        self,
        *,
        org_id: str,
        project_id: str,
        workspace_id: str,
        cwd: str | None,
        had_configured_cwd: bool,
        repo_url: str | None,
    ) -> str:
        if not cwd:
            return "repo_url_pending_checkout" if repo_url else "none"
        try:
            if Path(cwd).resolve() == self._managed_project_checkout_path(
                org_id, project_id, workspace_id
            ):
                return "managed_checkout"
        except OSError:
            pass
        if had_configured_cwd:
            return "local_cwd"
        return "local_cwd"

    def _with_organization_workspace_paths(
        self,
        *,
        workspace: ExecutionWorkspaceData,
        org_root: Path,
        agents_dir: Path,
        skills_dir: Path,
        plans_dir: Path,
        artifacts_dir: Path,
    ) -> ExecutionWorkspaceData:
        enriched = dict(workspace)
        enriched.update(
            {
                "source": workspace["providerType"],
                "strategy": workspace["strategyType"],
                "workspaceId": workspace["id"],
                "workspaceKind": _workspace_kind(workspace),
                "codeSourceKind": _workspace_code_source_kind(workspace),
                "workspaceCwd": workspace.get("cwd"),
                "warnings": _workspace_warnings(workspace),
                "requiresLease": False,
                "canRun": True,
                "failureReason": None,
                "orgWorkspaceRoot": str(org_root),
                "orgAgentsDir": str(agents_dir),
                "orgSkillsDir": str(skills_dir),
                "orgPlansDir": str(plans_dir),
                "orgArtifactsDir": str(artifacts_dir),
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
    ) -> dict[str, str]:
        workspaces_json = _json_dump([workspace])
        services_json = _json_dump([])
        issue_artifacts_dir = _string(workspace.get("issueArtifactsDir"))
        return {
            "OCTOPUS_WORKSPACE_CWD": workspace["cwd"] or "",
            "OCTOPUS_WORKSPACE_SOURCE": workspace["providerType"],
            "OCTOPUS_WORKSPACE_STRATEGY": workspace["strategyType"],
            "OCTOPUS_WORKSPACE_KIND": _workspace_kind(workspace),
            "OCTOPUS_WORKSPACE_CODE_SOURCE": _workspace_code_source_kind(workspace),
            "OCTOPUS_WORKSPACE_WARNINGS_JSON": _json_dump(
                _workspace_warnings(workspace)
            ),
            "OCTOPUS_WORKSPACE_REQUIRES_LEASE": "false",
            "OCTOPUS_WORKSPACE_ID": workspace["id"] or "",
            "OCTOPUS_WORKSPACE_REPO_URL": workspace["repoUrl"] or "",
            "OCTOPUS_WORKSPACE_REPO_REF": workspace["baseRef"] or "",
            "OCTOPUS_WORKSPACE_BRANCH": workspace["branchName"] or "",
            "OCTOPUS_WORKSPACE_WORKTREE_PATH": workspace["cwd"] or "",
            "OCTOPUS_WORKSPACES_JSON": workspaces_json,
            "OCTOPUS_RUNTIME_SERVICE_INTENTS_JSON": "[]",
            "OCTOPUS_RUNTIME_SERVICES_JSON": services_json,
            "OCTOPUS_ORG_WORKSPACE_ROOT": str(org_root),
            "OCTOPUS_ORG_AGENTS_DIR": str(agents_dir),
            "OCTOPUS_ORG_SKILLS_DIR": str(skills_dir),
            "OCTOPUS_ORG_PLANS_DIR": str(plans_dir),
            "OCTOPUS_ORG_ARTIFACTS_DIR": str(artifacts_dir),
            **(
                {"OCTOPUS_ISSUE_ARTIFACTS_DIR": issue_artifacts_dir}
                if issue_artifacts_dir
                else {}
            ),
        }

    async def _find_reusable_execution_workspace(
        self,
        *,
        org_id: str,
        project_id: str,
        project_workspace_id: str | None,
        issue_id: str,
        mode: str,
        branch_name: str | None,
    ) -> ExecutionWorkspace | None:
        issue_scope = issue_id if mode == "isolated_workspace" else None
        rows = await list_execution_workspaces(
            self._session,
            org_id,
            project_id=project_id,
            project_workspace_id=project_workspace_id,
            issue_id=issue_scope,
            reuse_eligible=True,
        )
        for row in rows:
            if row.mode != mode:
                continue
            if mode == "operator_branch" and branch_name is not None:
                if row.branch_name != branch_name:
                    continue
            return row
        return None

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
                    "workspaceKind": "organization_scratch",
                    "codeSourceKind": "none",
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
