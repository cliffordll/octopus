from __future__ import annotations

import os
from pathlib import Path
import re
import shutil

from sqlalchemy.engine import make_url

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
    home = (
        _expand_home_prefix(raw_home)
        if raw_home
        else _default_octopus_home_from_database_url() or Path.home() / ".octopus"
    )
    return home.resolve()


def _default_octopus_home_from_database_url() -> Path | None:
    raw_database_url = os.environ.get(
        "OCTOPUS_DATABASE_URL", "sqlite+aiosqlite:///./octopus.db"
    ).strip()
    if not raw_database_url:
        return None
    try:
        url = make_url(raw_database_url)
    except Exception:
        return None
    if url.get_backend_name() != "sqlite":
        return None
    database = url.database
    if not database or database == ":memory:":
        return None
    return Path(database).expanduser().parent / ".octopus"


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
