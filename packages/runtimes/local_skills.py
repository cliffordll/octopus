from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any

from .paths import ensure_managed_runtime_home
from .skills import skill_snapshot_from_root
from .types import RuntimeExecutionContext


async def prepare_managed_home(
    *,
    runtime_type: str,
    context: RuntimeExecutionContext,
    env: dict[str, str],
) -> Path:
    home = _default_home(runtime_type, context)
    home.mkdir(parents=True, exist_ok=True)
    operator_home = _operator_home(env)
    linked = _sync_local_cli_credential_home_entries(operator_home, home)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    configure_managed_profile_env(env, home)
    env["OCTOPUS_OPERATOR_HOME"] = str(operator_home)
    if linked:
        await context.on_log(
            "stdout",
            (
                f"[octopus] Shared {len(linked)} local CLI credential "
                f"entr{'y' if len(linked) == 1 else 'ies'} into managed HOME "
                f"{home}: {', '.join(linked)}\n"
            ),
        )
    return home


def configure_managed_profile_env(env: dict[str, str], home: Path) -> None:
    env["APPDATA"] = str(home / "AppData" / "Roaming")
    env["LOCALAPPDATA"] = str(home / "AppData" / "Local")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_CACHE_HOME"] = str(home / ".cache")
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    for key in (
        "APPDATA",
        "LOCALAPPDATA",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_DATA_HOME",
    ):
        Path(env[key]).mkdir(parents=True, exist_ok=True)


def desired_skills_from_config(config: dict[str, Any]) -> list[str]:
    context = config.get("_octopus")
    if isinstance(context, dict):
        desired = _string_list(context.get("desiredSkills"))
        if desired:
            return desired
    return _string_list(config.get("desiredSkills"))


def materialize_runtime_skills(
    *,
    runtime_type: str,
    config: dict[str, Any],
    desired_skills: list[str],
    skills_home: Path,
    location_label: str,
) -> list[dict[str, str | None]]:
    if not desired_skills:
        return []
    _clear_desired_targets(skills_home, desired_skills)
    snapshot = skill_snapshot_from_root(
        runtime_type=runtime_type,
        config=config,
        desired_skills=desired_skills,
        mode="ephemeral",
        location_label=location_label,
        skills_home=skills_home,
        materialize=True,
    )
    return [
        {
            "key": entry["key"],
            "runtimeName": entry["runtimeName"],
            "name": entry["key"],
            "description": entry.get("description"),
        }
        for entry in snapshot["entries"]
        if entry.get("desired") is True and isinstance(entry.get("runtimeName"), str)
    ]


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item.strip()]
    return []


def _clear_desired_targets(skills_home: Path, desired_skills: list[str]) -> None:
    for key in desired_skills:
        target = skills_home / _desired_runtime_name(key)
        if target.is_symlink() or target.is_file():
            target.unlink(missing_ok=True)
        elif target.exists():
            shutil.rmtree(target, ignore_errors=True)


def _desired_runtime_name(value: str) -> str:
    normalized = value.strip()
    if normalized.startswith("agent:"):
        return _desired_runtime_name(normalized.removeprefix("agent:"))
    if normalized.startswith("org:"):
        return _desired_runtime_name(normalized.removeprefix("org:"))
    if normalized.startswith("skills/"):
        return normalized.removeprefix("skills/")
    if normalized.startswith("organization/"):
        return normalized.rsplit("/", 1)[-1]
    return normalized


def _default_home(runtime_type: str, context: RuntimeExecutionContext) -> Path:
    return (
        ensure_managed_runtime_home(
            runtime_type,
            org_id=context.org_id,
            agent_id=context.agent_id,
        )
        / "home"
    )


def _operator_home(env: dict[str, str]) -> Path:
    return Path(
        _string(env.get("OCTOPUS_OPERATOR_HOME"))
        or _string(os.environ.get("OCTOPUS_OPERATOR_HOME"))
        or _string(os.environ.get("HOME"))
        or _string(env.get("HOME"))
        or str(Path.home())
    ).expanduser()


_LOCAL_CLI_CREDENTIAL_HOME_ENTRIES = (
    ".aws",
    ".azure",
    ".config/gh",
    ".config/gcloud",
    ".config/op",
    ".config/opencode",
    ".config/vercel",
    ".config/configstore",
    ".docker",
    ".fly",
    ".git-credentials",
    ".gnupg",
    ".kube",
    ".netrc",
    ".npmrc",
    ".ssh",
    ".local/share/opencode/auth.json",
    ".vercel",
    "Library/Application Support/gh",
    "Library/Application Support/com.heroku.cli",
)

_OVERWRITE_MANAGED_HOME_ENTRIES = frozenset(
    {
        ".config/opencode",
        ".local/share/opencode/auth.json",
    }
)

_COPY_MANAGED_HOME_ENTRIES = frozenset(
    {
        # Runtime config is mutable per agent. Copy it so DB materialization in the
        # managed home cannot write through a symlink into the operator home.
        ".config/opencode",
    }
)


def _sync_local_cli_credential_home_entries(
    source_home: Path, target_home: Path
) -> list[str]:
    if _same_path(source_home, target_home):
        return []
    linked: list[str] = []
    for relative_entry in _LOCAL_CLI_CREDENTIAL_HOME_ENTRIES:
        source = source_home / Path(relative_entry)
        if not source.exists():
            continue
        target = target_home / Path(relative_entry)
        if _ensure_link_or_copy(
            source,
            target,
            overwrite=relative_entry in _OVERWRITE_MANAGED_HOME_ENTRIES,
            force_copy=relative_entry in _COPY_MANAGED_HOME_ENTRIES,
        ):
            linked.append(relative_entry)
    return linked


def _ensure_link_or_copy(
    source: Path, target: Path, *, overwrite: bool = False, force_copy: bool = False
) -> bool:
    if target.is_symlink():
        try:
            linked = Path(os.readlink(target))
        except OSError:
            linked = Path()
        resolved = linked if linked.is_absolute() else (target.parent / linked)
        if _same_path(resolved, source):
            return False
        target.unlink(missing_ok=True)
    elif target.exists():
        if not overwrite:
            return False
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if force_copy:
        try:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            return True
        except OSError:
            return False
    try:
        target.symlink_to(source, target_is_directory=source.is_dir())
        return True
    except OSError:
        try:
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
            return True
        except OSError:
            return False


def _same_path(left: Path, right: Path) -> bool:
    try:
        return os.path.normcase(str(left.resolve())) == os.path.normcase(
            str(right.resolve())
        )
    except OSError:
        return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(
            os.path.abspath(str(right))
        )


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
