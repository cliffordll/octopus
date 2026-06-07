from __future__ import annotations

import os
from pathlib import Path
import re
import shutil

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


def resolve_octopus_database_dir() -> Path:
    return (resolve_octopus_instance_root() / "db").resolve()


def resolve_octopus_sqlite_database_path() -> Path:
    return (resolve_octopus_database_dir() / "octopus.db").resolve()


def resolve_default_sqlite_database_url() -> str:
    return f"sqlite+aiosqlite:///{resolve_octopus_sqlite_database_path().as_posix()}"


def resolve_octopus_instance_data_root() -> Path:
    return (resolve_octopus_instance_root() / "data").resolve()


def resolve_octopus_run_log_dir() -> Path:
    raw_dir = os.environ.get("OCTOPUS_RUN_LOG_DIR", "").strip()
    if raw_dir:
        return _expand_home_prefix(raw_dir).resolve()
    return (resolve_octopus_instance_data_root() / "run-logs").resolve()


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
    return _ensure_canonical_path(
        resolve_octopus_storage_dir(),
        legacy_octopus_storage_dir(),
    )


def resolve_octopus_workspace_operation_log_dir() -> Path:
    raw_dir = os.environ.get("OCTOPUS_WORKSPACE_OPERATION_LOG_DIR", "").strip()
    if raw_dir:
        return _expand_home_prefix(raw_dir).resolve()
    return (resolve_octopus_server_log_dir() / "workspace-operation-logs").resolve()


def legacy_octopus_workspace_operation_log_dir() -> Path:
    return (resolve_octopus_home_dir() / "workspace-operation-logs").resolve()


def ensure_octopus_workspace_operation_log_dir() -> Path:
    return _ensure_canonical_path(
        resolve_octopus_workspace_operation_log_dir(),
        legacy_octopus_workspace_operation_log_dir(),
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


def ensure_organization_workspace_root(org_id: str) -> Path:
    return _ensure_canonical_path(
        organization_workspace_root(org_id),
        legacy_organization_workspace_root(org_id),
    )


def _ensure_canonical_path(canonical: Path, legacy: Path) -> Path:
    if legacy == canonical:
        canonical.mkdir(parents=True, exist_ok=True)
        return canonical

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
    canonical.mkdir(parents=True, exist_ok=True)
    return canonical


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


def agent_workspace_root(org_id: str, workspace_key: str) -> Path:
    return (
        ensure_organization_workspace_root(org_id) / "agents" / workspace_key
    ).resolve()
