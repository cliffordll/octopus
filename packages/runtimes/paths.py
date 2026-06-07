from __future__ import annotations

import os
from pathlib import Path
import shutil

DEFAULT_INSTANCE_ID = "default"


def resolve_octopus_home_dir() -> Path:
    raw_home = os.environ.get("OCTOPUS_HOME", "").strip()
    return (
        _expand_home_prefix(raw_home).resolve()
        if raw_home
        else (Path.home() / ".octopus").resolve()
    )


def resolve_octopus_instance_id() -> str:
    return os.environ.get("OCTOPUS_INSTANCE_ID", "").strip() or DEFAULT_INSTANCE_ID


def resolve_octopus_instance_root() -> Path:
    return (
        resolve_octopus_home_dir() / "instances" / resolve_octopus_instance_id()
    ).resolve()


def resolve_managed_runtime_home(
    runtime_type: str, *, org_id: str, agent_id: str
) -> Path:
    org_root = resolve_octopus_instance_root() / "organizations" / org_id
    if runtime_type == "codex_local":
        return (org_root / "codex-home" / "agents" / agent_id).resolve()
    return (org_root / _runtime_home_dir_name(runtime_type)).resolve()


def ensure_managed_runtime_home(
    runtime_type: str, *, org_id: str, agent_id: str
) -> Path:
    canonical = resolve_managed_runtime_home(
        runtime_type, org_id=org_id, agent_id=agent_id
    )
    return _ensure_canonical_paths(
        canonical,
        legacy_managed_runtime_homes(runtime_type, org_id=org_id, agent_id=agent_id),
    )


def legacy_managed_runtime_home(
    runtime_type: str, *, org_id: str, agent_id: str
) -> Path:
    return (
        resolve_octopus_home_dir() / "runtime-homes" / runtime_type / org_id / agent_id
    ).resolve()


def legacy_managed_runtime_homes(
    runtime_type: str, *, org_id: str, agent_id: str
) -> list[Path]:
    return [
        legacy_managed_runtime_home(runtime_type, org_id=org_id, agent_id=agent_id),
        (
            resolve_octopus_instance_root()
            / "runtime-homes"
            / runtime_type
            / org_id
            / agent_id
        ).resolve(),
    ]


def _runtime_home_dir_name(runtime_type: str) -> str:
    normalized = runtime_type.removesuffix("_local").replace("_", "-")
    return f"{normalized}-home"


def _expand_home_prefix(value: str) -> Path:
    if value == "~":
        return Path.home()
    if value.startswith("~/") or value.startswith("~\\"):
        return Path.home() / value[2:]
    return Path(value)


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
            _remove_empty_parents(legacy, stop_at=resolve_octopus_home_dir())


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
