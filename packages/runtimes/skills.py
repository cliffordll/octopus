from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any


def skill_snapshot_from_root(
    *,
    runtime_type: str,
    config: dict[str, Any],
    desired_skills: list[str],
    mode: str,
    location_label: str,
    skills_home: Path | None = None,
    materialize: bool = False,
    installed_detail: str | None = None,
    missing_detail: str | None = None,
    external_conflict_detail: str | None = None,
    external_detail: str | None = None,
    persistent_materialization: bool = False,
) -> dict[str, Any]:
    root = config.get("skillsRootPath")
    desired = set(desired_skills)
    available: list[Path] = []
    warnings: list[str] = []
    seen_keys: set[str] = set()
    if isinstance(root, str) and root.strip():
        root_path = Path(root)
        if root_path.exists() and root_path.is_dir():
            for skill_dir in _skill_dirs(root_path):
                available.append(skill_dir)
                seen_keys.add(skill_dir.name)
        else:
            warnings.append(f"skillsRootPath does not exist: {root}")
    for skill_dir in _skill_dirs(_bundled_skills_root()):
        if skill_dir.name in seen_keys:
            continue
        available.append(skill_dir)
    if materialize and skills_home is not None:
        _materialize_desired_skills(skills_home, available, desired, warnings)
    entries = _skill_entries(
        available,
        desired=desired,
        skills_home=skills_home,
        location_label=location_label,
        installed_detail=installed_detail,
        missing_detail=missing_detail,
        external_conflict_detail=external_conflict_detail,
        external_detail=external_detail,
        persistent_materialization=persistent_materialization,
        warnings=warnings,
    )
    return {
        "agentRuntimeType": runtime_type,
        "supported": True,
        "mode": mode,
        "desiredSkills": desired_skills,
        "entries": entries,
        "warnings": warnings,
    }


def _bundled_skills_root() -> Path:
    return Path(__file__).resolve().parents[2] / "server" / "skills" / "bundled"


def _skill_dirs(root_path: Path) -> list[Path]:
    if not root_path.exists() or not root_path.is_dir():
        return []
    return [
        skill_dir
        for skill_dir in sorted(root_path.iterdir(), key=lambda item: item.name)
        if skill_dir.is_dir() and skill_dir.joinpath("SKILL.md").is_file()
    ]


def _skill_entries(
    available: list[Path],
    *,
    desired: set[str],
    skills_home: Path | None,
    location_label: str,
    installed_detail: str | None,
    missing_detail: str | None,
    external_conflict_detail: str | None,
    external_detail: str | None,
    persistent_materialization: bool,
    warnings: list[str],
) -> list[dict[str, Any]]:
    installed = _read_installed_skill_targets(skills_home) if skills_home else {}
    entries: list[dict[str, Any]] = []
    available_by_key = {skill_dir.name: skill_dir for skill_dir in available}
    available_names = set(available_by_key)
    bundled_root = _bundled_skills_root()
    for skill_dir in available:
        is_bundled = skill_dir.parent == bundled_root
        entries.append(
            _skill_entry(
                skill_dir,
                desired=skill_dir.name in desired,
                skills_home=skills_home,
                installed_target=installed.get(skill_dir.name)
                if persistent_materialization
                else None,
                location_label="bundled skills" if is_bundled else location_label,
                source_class="bundled" if is_bundled else "organization",
                origin="bundled" if is_bundled else "organization_managed",
                origin_label="Bundled skill" if is_bundled else "Organization skill",
                read_only=is_bundled,
                installed_detail=installed_detail,
                missing_detail=missing_detail,
                external_conflict_detail=external_conflict_detail,
                external_detail=external_detail,
                persistent_materialization=persistent_materialization,
            )
        )
    for desired_skill in desired:
        if desired_skill in available_by_key:
            continue
        warnings.append(f'Desired skill "{desired_skill}" is not available.')
        entries.append(_missing_skill_entry(desired_skill))
    for name, installed_target in installed.items():
        if name in available_names:
            continue
        entries.append(
            {
                **_base_skill_entry(
                    key=name,
                    runtime_name=name,
                    desired=False,
                    state="external",
                    managed=False,
                ),
                "origin": "user_installed",
                "originLabel": "User-installed",
                "locationLabel": location_label,
                "readOnly": True,
                "sourcePath": None,
                "targetPath": str(installed_target),
                "workspaceEditPath": None,
                "detail": external_detail,
            }
        )
    return sorted(entries, key=lambda entry: entry["key"])


def _skill_entry(
    skill_dir: Path,
    *,
    desired: bool,
    skills_home: Path | None,
    installed_target: Path | None,
    location_label: str,
    source_class: str,
    origin: str,
    origin_label: str,
    read_only: bool,
    installed_detail: str | None,
    missing_detail: str | None,
    external_conflict_detail: str | None,
    external_detail: str | None,
    persistent_materialization: bool,
) -> dict[str, Any]:
    description = _skill_description(skill_dir.joinpath("SKILL.md"))
    state = "configured" if desired else "available"
    managed = True
    detail = None
    target_path = (
        str(skills_home / skill_dir.name)
        if persistent_materialization and skills_home is not None
        else None
    )
    if installed_target is not None:
        if _same_path(installed_target, skill_dir):
            state = "installed" if desired else "stale"
            detail = installed_detail if desired else None
        else:
            state = "external"
            managed = False
            detail = external_conflict_detail if desired else external_detail
    elif desired and persistent_materialization and skills_home is not None:
        state = "missing"
        detail = missing_detail
    return {
        **_base_skill_entry(
            key=skill_dir.name,
            runtime_name=skill_dir.name,
            desired=desired,
            state=state,
            managed=managed,
        ),
        "description": description,
        "sourceClass": source_class,
        "origin": origin,
        "originLabel": origin_label,
        "locationLabel": location_label,
        "readOnly": read_only,
        "sourcePath": str(skill_dir),
        "targetPath": target_path,
        "workspaceEditPath": str(skill_dir.joinpath("SKILL.md")),
        "detail": detail,
    }


def _base_skill_entry(
    *,
    key: str,
    runtime_name: str | None,
    desired: bool,
    state: str,
    managed: bool,
) -> dict[str, Any]:
    return {
        "key": key,
        "selectionKey": key,
        "runtimeName": runtime_name,
        "description": None,
        "desired": desired,
        "configurable": True,
        "alwaysEnabled": False,
        "managed": managed,
        "state": state,
    }


def _missing_skill_entry(key: str) -> dict[str, Any]:
    return {
        **_base_skill_entry(
            key=key, runtime_name=None, desired=True, state="missing", managed=True
        ),
        "sourceClass": "adapter_home",
        "origin": "external_unknown",
        "originLabel": "External or unavailable",
        "locationLabel": None,
        "readOnly": False,
        "sourcePath": None,
        "targetPath": None,
        "workspaceEditPath": None,
        "detail": "This desired skill is not available from configured or bundled skills.",
    }


_SOURCE_MARKER = ".octopus-source"


def _read_installed_skill_targets(skills_home: Path | None) -> dict[str, Path]:
    if skills_home is None or not skills_home.exists() or not skills_home.is_dir():
        return {}
    installed: dict[str, Path] = {}
    for entry in skills_home.iterdir():
        if entry.name in {".system", "skills.json"}:
            continue
        target = _resolve_installed_target(entry)
        installed[entry.name] = target
    return installed


def _resolve_installed_target(entry: Path) -> Path:
    if entry.is_symlink():
        link_target = os.readlink(entry)
        target = Path(link_target)
        return target if target.is_absolute() else (entry.parent / target).resolve()
    marker = entry / _SOURCE_MARKER
    if marker.is_file():
        try:
            value = marker.read_text(encoding="utf-8").strip()
        except OSError:
            value = ""
        if value:
            return Path(value)
    return entry


def _materialize_desired_skills(
    skills_home: Path,
    available: list[Path],
    desired: set[str],
    warnings: list[str],
) -> None:
    by_key = {skill_dir.name: skill_dir for skill_dir in available}
    for key in sorted(desired):
        source = by_key.get(key)
        if source is None:
            continue
        target = skills_home / source.name
        try:
            _ensure_skill_link_or_copy(source, target)
        except OSError as exc:
            warnings.append(f'Could not materialize skill "{key}": {exc}')


def _ensure_skill_link_or_copy(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        if _same_path(_resolve_installed_target(target), source):
            return
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(source, target_is_directory=True)
    except OSError:
        shutil.copytree(source, target)
        (target / _SOURCE_MARKER).write_text(str(source), encoding="utf-8")


def _same_path(left: Path, right: Path) -> bool:
    try:
        resolved_left = left.resolve()
        resolved_right = right.resolve()
    except OSError:
        resolved_left = Path(os.path.abspath(str(left)))
        resolved_right = Path(os.path.abspath(str(right)))
    return _normalized_path_text(resolved_left) == _normalized_path_text(resolved_right)


def _normalized_path_text(path: Path) -> str:
    value = os.path.normcase(os.path.abspath(str(path)))
    if value.startswith("\\\\?\\"):
        value = value[4:]
    return value


def _skill_description(skill_file: Path) -> str | None:
    try:
        lines = skill_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        return value
    return None
