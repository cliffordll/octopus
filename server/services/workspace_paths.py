from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import tempfile

DEFAULT_INSTANCE_ID = "default"
INSTANCE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _expand_home_prefix(value: str) -> Path:
    if value == "~":
        return Path.home()
    if value.startswith("~/") or value.startswith("~\\"):
        return Path.home() / value[2:]
    return Path(value)


def resolve_octopus_home_dir() -> Path:
    raw_home = os.environ.get("OCTOPUS_HOME", "").strip()
    home = _expand_home_prefix(raw_home) if raw_home else Path.home() / ".octopus"
    return home.resolve()


def resolve_octopus_database_dir() -> Path:
    return (resolve_octopus_instance_root() / "db").resolve()


def resolve_octopus_sqlite_database_path() -> Path:
    return (resolve_octopus_database_dir() / "octopus.db").resolve()


def resolve_default_sqlite_database_url() -> str:
    database_path = resolve_octopus_sqlite_database_path()
    database_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{database_path.as_posix()}"


def resolve_octopus_instance_id() -> str:
    instance_id = (
        os.environ.get("OCTOPUS_INSTANCE_ID", "").strip() or DEFAULT_INSTANCE_ID
    )
    if not INSTANCE_ID_RE.fullmatch(instance_id):
        raise ValueError(f"Invalid OCTOPUS_INSTANCE_ID '{instance_id}'.")
    return instance_id


def resolve_octopus_instance_root() -> Path:
    return (
        resolve_octopus_home_dir() / "instances" / resolve_octopus_instance_id()
    ).resolve()


def resolve_octopus_instance_data_root() -> Path:
    return (resolve_octopus_instance_root() / "data").resolve()


def resolve_octopus_run_log_dir() -> Path:
    raw_dir = os.environ.get("OCTOPUS_RUN_LOG_DIR", "").strip()
    if raw_dir:
        return _expand_home_prefix(raw_dir).resolve()
    return (resolve_octopus_instance_data_root() / "run-logs").resolve()


def legacy_octopus_run_log_dir() -> Path:
    return (resolve_octopus_home_dir() / "run-logs").resolve()


def ensure_octopus_run_log_dir() -> Path:
    return _ensure_canonical_paths(
        resolve_octopus_run_log_dir(),
        [legacy_octopus_run_log_dir()],
    )


def resolve_octopus_server_log_dir() -> Path:
    raw_dir = os.environ.get("OCTOPUS_LOG_DIR", "").strip()
    if raw_dir:
        return _expand_home_prefix(raw_dir).resolve()
    return (resolve_octopus_instance_root() / "logs").resolve()


def resolve_octopus_storage_dir() -> Path:
    raw_dir = os.environ.get("OCTOPUS_STORAGE_DIR", "").strip()
    if raw_dir:
        return _expand_home_prefix(raw_dir).resolve()
    return (resolve_octopus_instance_data_root() / "storage").resolve()


def legacy_octopus_storage_dir() -> Path:
    return (resolve_octopus_home_dir() / "storage").resolve()


def ensure_octopus_storage_dir() -> Path:
    return _ensure_canonical_paths(
        resolve_octopus_storage_dir(),
        [legacy_octopus_storage_dir()],
    )


def resolve_octopus_workspace_operation_log_dir() -> Path:
    raw_dir = os.environ.get("OCTOPUS_WORKSPACE_OPERATION_LOG_DIR", "").strip()
    if raw_dir:
        return _expand_home_prefix(raw_dir).resolve()
    return (resolve_octopus_server_log_dir() / "workspace-operation-logs").resolve()


def legacy_octopus_workspace_operation_log_dir() -> Path:
    return (resolve_octopus_home_dir() / "workspace-operation-logs").resolve()


def ensure_octopus_workspace_operation_log_dir() -> Path:
    return _ensure_canonical_paths(
        resolve_octopus_workspace_operation_log_dir(),
        [legacy_octopus_workspace_operation_log_dir()],
    )


def organization_workspace_relative_path(org_id: str) -> str:
    return f"organizations/{org_id}/workspaces"


def organization_workspace_root(org_id: str) -> Path:
    return (
        resolve_octopus_instance_root() / organization_workspace_relative_path(org_id)
    ).resolve()


def legacy_organization_workspace_root(org_id: str) -> Path:
    return (
        resolve_octopus_home_dir() / organization_workspace_relative_path(org_id)
    ).resolve()


def legacy_organization_workspace_roots(org_id: str) -> list[Path]:
    instance_root = resolve_octopus_instance_root()
    home = resolve_octopus_home_dir()
    paths = [
        legacy_organization_workspace_root(org_id),
        (home / "workspaces" / org_id).resolve(),
        (instance_root / "workspaces" / org_id).resolve(),
        (
            instance_root / "workspaces" / "organizations" / org_id / "workspaces"
        ).resolve(),
    ]
    legacy_instance_workspace_root = (instance_root / "workspaces").resolve()
    if _looks_like_workspace_root(legacy_instance_workspace_root):
        paths.append(legacy_instance_workspace_root)
    return paths


def ensure_organization_workspace_root(org_id: str) -> Path:
    return _ensure_canonical_paths(
        organization_workspace_root(org_id),
        legacy_organization_workspace_roots(org_id),
    )


def _ensure_canonical_paths(canonical: Path, legacy_paths: list[Path]) -> Path:
    for legacy in legacy_paths:
        _merge_legacy_path(canonical, legacy)
    canonical.mkdir(parents=True, exist_ok=True)
    return canonical


def _merge_legacy_path(canonical: Path, legacy: Path) -> None:
    if legacy == canonical:
        canonical.mkdir(parents=True, exist_ok=True)
        return

    if legacy.exists():
        canonical.parent.mkdir(parents=True, exist_ok=True)
        if not canonical.exists():
            shutil.move(str(legacy), str(canonical))
        else:
            _merge_directory_contents(legacy, canonical)
            _remove_empty_parents(
                legacy,
                stop_at=resolve_octopus_home_dir(),
            )


def _merge_directory_contents(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if not destination.exists():
            shutil.move(str(child), str(destination))
        elif child.is_dir() and destination.is_dir():
            _merge_directory_contents(child, destination)

    try:
        source.rmdir()
    except OSError:
        pass


def _remove_empty_parents(path: Path, *, stop_at: Path) -> None:
    current = path.parent
    stop = stop_at.resolve()
    while current != stop and current != current.parent:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def _looks_like_workspace_root(path: Path) -> bool:
    if not path.is_dir():
        return False
    workspace_markers = {
        "agents",
        "artifacts",
        "executions",
        "plans",
        "skills",
    }
    return any((path / marker).exists() for marker in workspace_markers)


def agent_workspace_root(org_id: str, workspace_key: str) -> Path:
    return (
        ensure_organization_workspace_root(org_id) / "agents" / workspace_key
    ).resolve()


def agent_heartbeat_workspace_root(org_id: str, workspace_key: str) -> Path:
    """Return a heartbeat cwd that cannot be discovered as a parent Git repo."""
    _validate_workspace_component("organization id", org_id)
    _validate_workspace_component("agent workspace key", workspace_key)
    configured = os.environ.get("OCTOPUS_SANDBOX_DIR", "").strip()
    sandbox_base = (
        _expand_home_prefix(configured)
        if configured
        else Path.home() / ".octopus-sandboxes"
    )
    instance_base = (sandbox_base / resolve_octopus_instance_id()).resolve()
    candidate = (
        instance_base
        / "organizations"
        / org_id
        / "agents"
        / workspace_key
        / "heartbeat-workspace"
    ).resolve()
    if not candidate.is_relative_to(instance_base):
        raise ValueError("Heartbeat workspace resolves outside the sandbox root")
    if _has_git_ancestor(candidate):
        instance_base = (
            Path(tempfile.gettempdir())
            / "octopus-sandboxes"
            / resolve_octopus_instance_id()
        ).resolve()
        candidate = (
            instance_base
            / "organizations"
            / org_id
            / "agents"
            / workspace_key
            / "heartbeat-workspace"
        ).resolve()
        if not candidate.is_relative_to(instance_base) or _has_git_ancestor(candidate):
            raise ValueError("No heartbeat sandbox root is isolated from Git")
    return candidate


def _has_git_ancestor(path: Path) -> bool:
    return any((parent / ".git").exists() for parent in (path, *path.parents))


def _validate_workspace_component(label: str, value: str) -> None:
    if not value or value in {".", ".."} or "/" in value or "\\" in value:
        raise ValueError(f"Invalid {label} for heartbeat sandbox")
