from __future__ import annotations

from pathlib import Path
from typing import Any

from packages.database.schema import Agent

MANAGED_INSTRUCTIONS_RUNTIME_TYPES = {
    "codex_local",
    "claude_local",
    "opencode_local",
}

_ENTRY_FILE = "SOUL.md"
_EXPLICIT_INSTRUCTIONS_KEYS = (
    "instructionsRootPath",
    "instructionsFilePath",
    "agentsMdPath",
)


def normalize_instructions_paths(config: dict[str, Any]) -> dict[str, Any]:
    next_config = dict(config)
    for key in _EXPLICIT_INSTRUCTIONS_KEYS:
        value = _string(next_config.get(key))
        if not value:
            continue
        path = Path(value).expanduser()
        if path.is_absolute():
            next_config[key] = str(path)
            continue
        cwd = _string(next_config.get("cwd"))
        if not cwd:
            raise ValueError(
                f"Relative {key} requires agentRuntimeConfig.cwd to be an absolute path"
            )
        cwd_path = Path(cwd).expanduser()
        if not cwd_path.is_absolute():
            raise ValueError(
                "agentRuntimeConfig.cwd must be an absolute path to resolve "
                f"relative {key}"
            )
        next_config[key] = str((cwd_path / path).resolve())
    return next_config


def materialize_default_instructions_for_new_agent(
    row: Agent, agent_home: Path
) -> dict[str, Any] | None:
    if row.agent_runtime_type not in MANAGED_INSTRUCTIONS_RUNTIME_TYPES:
        return None
    config = dict(row.agent_runtime_config)
    if any(_string(config.get(key)) for key in _EXPLICIT_INSTRUCTIONS_KEYS):
        return None

    root = (agent_home / "instructions").resolve()
    files = _default_bundle(row.role)
    prompt_template = _string(config.get("promptTemplate"))
    if prompt_template:
        files[_ENTRY_FILE] = prompt_template
    _write_bundle(root, files)

    next_config = {
        **config,
        "instructionsBundleMode": "managed",
        "instructionsRootPath": str(root),
        "instructionsEntryFile": _ENTRY_FILE,
        "instructionsFilePath": str(root / _ENTRY_FILE),
    }
    next_config.pop("promptTemplate", None)
    next_config.pop("bootstrapPromptTemplate", None)
    return next_config


def _default_bundle(role: str) -> dict[str, str]:
    soul = (
        "# SOUL.md -- CEO Persona\n\nYou are the CEO.\n"
        if role == "ceo"
        else "# SOUL.md -- Agent Persona\n\nYou are an agent in this organization.\n"
    )
    return {
        "MEMORY.md": "# MEMORY.md\n\nDurable memory starts empty.\n",
        "HEARTBEAT.md": "# HEARTBEAT.md\n\nUse heartbeat runs to inspect and advance assigned work.\n",
        _ENTRY_FILE: soul,
        "TOOLS.md": "# TOOLS.md\n\nUse the available control-plane and runtime tools.\n",
    }


def _write_bundle(root: Path, files: dict[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for relative_path, content in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(content, encoding="utf-8")


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
