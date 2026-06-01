from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import get_agent_by_id, update_agent
from packages.database.schema import Agent
from packages.shared.types.agent import (
    AgentInstructionsBundle,
    AgentInstructionsFileDetail,
    AgentInstructionsFileSummary,
    AgentInstructionsPathResult,
)

MANAGED_INSTRUCTIONS_RUNTIME_TYPES = {
    "codex_local",
    "claude_local",
    "opencode_local",
}

_ENTRY_FILE = "SOUL.md"
_MEMORY_FILE = "MEMORY.md"
_DEFAULT_BUNDLE_FILES = ("MEMORY.md", "HEARTBEAT.md", _ENTRY_FILE, "TOOLS.md")
_ONBOARDING_ROOT = Path(__file__).resolve().parents[1] / "onboarding"
_PROMPT_TEMPLATE_FILE = "promptTemplate.legacy.md"
_EXPLICIT_INSTRUCTIONS_KEYS = (
    "instructionsRootPath",
    "instructionsFilePath",
    "agentsMdPath",
)
_MODE_KEY = "instructionsBundleMode"
_ROOT_KEY = "instructionsRootPath"
_ENTRY_KEY = "instructionsEntryFile"
_FILE_KEY = "instructionsFilePath"
_PROMPT_KEY = "promptTemplate"
_BOOTSTRAP_PROMPT_KEY = "bootstrapPromptTemplate"
_IGNORED_FILE_NAMES = {".DS_Store", "Thumbs.db", "Desktop.ini"}
_IGNORED_DIR_NAMES = {
    ".git",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}


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


class AgentInstructionsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def update_path(
        self,
        agent_id: str,
        payload: dict[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> AgentInstructionsPathResult | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        key = payload.get("agentRuntimeConfigKey") or _FILE_KEY
        path = payload.get("path")
        config = dict(row.agent_runtime_config)
        if path is None:
            config.pop(str(key), None)
            for bundle_key in (_MODE_KEY, _ROOT_KEY, _ENTRY_KEY):
                config.pop(bundle_key, None)
            resolved_path = None
        else:
            resolved_path = str(_resolve_instructions_file_path(str(path), config))
            config[str(key)] = resolved_path
            config = _sync_bundle_config_from_file_path(row, config)
        updated = await update_agent(
            self._session, row.id, {"agent_runtime_config": config}
        )
        if updated is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.instructions_path_updated",
            entity_type="agent",
            entity_id=row.id,
            details={
                "agentRuntimeConfigKey": key,
                "path": resolved_path,
                "cleared": path is None,
            },
        )
        return {
            "agentId": row.id,
            "agentRuntimeType": row.agent_runtime_type,
            "agentRuntimeConfigKey": str(key),
            "path": resolved_path,
        }

    async def get_bundle(self, agent_id: str) -> AgentInstructionsBundle | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        row = await self._reconcile_bundle(row)
        return _bundle(row)

    async def update_bundle(
        self,
        agent_id: str,
        payload: dict[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> AgentInstructionsBundle | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        state = _bundle_state(row)
        exported_files = _export_files(row)
        mode = payload.get("mode") or state["mode"] or "managed"
        entry_file = _normalize_relative_file_path(
            payload.get("entryFile") or state["entryFile"]
        )
        if mode == "managed":
            root = _managed_instructions_root(row)
        else:
            root_value = _string(payload.get("rootPath")) or state["rootPath"]
            if not root_value:
                raise ValueError(
                    "External instructions bundles require an absolute rootPath"
                )
            root = Path(root_value).expanduser().resolve()
            if not root.is_absolute():
                raise ValueError(
                    "External instructions bundles require an absolute rootPath"
                )
        root.mkdir(parents=True, exist_ok=True)
        existing_files = _list_files(root) if root.is_dir() else []
        if not existing_files and exported_files:
            _write_bundle(root, exported_files)
        entry_path = _resolve_path_within_root(root, entry_file)
        if not entry_path.exists():
            entry_path.parent.mkdir(parents=True, exist_ok=True)
            entry_path.write_text(
                exported_files.get(entry_file)
                or exported_files.get(str(state["entryFile"]))
                or "",
                encoding="utf-8",
            )
        config = _apply_bundle_config(
            dict(row.agent_runtime_config),
            mode=str(mode),
            root=root,
            entry_file=entry_file,
            clear_legacy_prompt_template=bool(payload.get("clearLegacyPromptTemplate")),
        )
        updated = await update_agent(
            self._session, row.id, {"agent_runtime_config": config}
        )
        if updated is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.instructions_bundle_updated",
            entity_type="agent",
            entity_id=row.id,
            details={
                "mode": mode,
                "rootPath": str(root),
                "entryFile": entry_file,
                "clearLegacyPromptTemplate": bool(
                    payload.get("clearLegacyPromptTemplate")
                ),
            },
        )
        return _bundle(updated)

    async def read_file(
        self, agent_id: str, relative_path: str
    ) -> AgentInstructionsFileDetail | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        row = await self._reconcile_bundle(row)
        return _read_file(row, relative_path)

    async def write_file(
        self,
        agent_id: str,
        payload: dict[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> AgentInstructionsFileDetail | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        config = await self._ensure_writable_bundle(row, payload)
        updated = await update_agent(
            self._session, row.id, {"agent_runtime_config": config}
        )
        if updated is None:
            return None
        relative_path = _normalize_relative_file_path(str(payload["path"]))
        root = _bundle_root(updated)
        if root is None:
            raise ValueError("Agent instructions bundle is not configured")
        target = _resolve_path_within_root(root, relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(payload["content"]), encoding="utf-8")
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.instructions_file_updated",
            entity_type="agent",
            entity_id=row.id,
            details={"path": relative_path, "size": len(str(payload["content"]))},
        )
        return _read_file(updated, relative_path)

    async def delete_file(
        self,
        agent_id: str,
        relative_path: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> AgentInstructionsBundle | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        normalized = _normalize_relative_file_path(relative_path)
        state = _bundle_state(row)
        if normalized == state["entryFile"]:
            raise ValueError("Cannot delete the bundle entry file")
        root = _bundle_root(row)
        if root is None:
            raise FileNotFoundError("Agent instructions bundle is not configured")
        target = _resolve_path_within_root(root, normalized)
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        config = _sync_bundle_config_from_file_path(row, dict(row.agent_runtime_config))
        updated = await update_agent(
            self._session, row.id, {"agent_runtime_config": config}
        )
        effective = updated or row
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.instructions_file_deleted",
            entity_type="agent",
            entity_id=row.id,
            details={"path": normalized},
        )
        return _bundle(effective)

    async def _ensure_writable_bundle(
        self, row: Agent, payload: dict[str, Any]
    ) -> dict[str, Any]:
        state = _bundle_state(row)
        if state["rootPath"] is not None and state["mode"] is not None:
            config = dict(row.agent_runtime_config)
            if payload.get("clearLegacyPromptTemplate"):
                config.pop(_PROMPT_KEY, None)
                config.pop(_BOOTSTRAP_PROMPT_KEY, None)
            return config
        root = _managed_instructions_root(row)
        root.mkdir(parents=True, exist_ok=True)
        entry_file = str(state["entryFile"])
        entry = _resolve_path_within_root(root, entry_file)
        files = _default_bundle(row.role)
        legacy_instructions = _legacy_instructions(row, state)
        if legacy_instructions:
            files[entry_file] = legacy_instructions
        _write_bundle(root, files)
        if not entry.exists() or entry.stat().st_size == 0:
            entry.parent.mkdir(parents=True, exist_ok=True)
            entry.write_text(
                files.get(entry_file) or files.get(_ENTRY_FILE) or "",
                encoding="utf-8",
            )
        return _apply_bundle_config(
            dict(row.agent_runtime_config),
            mode="managed",
            root=root,
            entry_file=entry_file,
            clear_legacy_prompt_template=bool(payload.get("clearLegacyPromptTemplate")),
        )

    async def _reconcile_bundle(self, row: Agent) -> Agent:
        state = _bundle_state(row)
        if state["mode"] == "managed" and isinstance(state["rootPath"], Path):
            _write_bundle(state["rootPath"], _default_bundle(row.role))
        if (
            state["mode"] == "managed"
            and state["rootPath"] is None
            and (
                state["legacyPromptTemplateActive"]
                or state["legacyBootstrapPromptTemplateActive"]
            )
        ):
            config = await self._ensure_writable_bundle(
                row, {"clearLegacyPromptTemplate": True}
            )
            updated = await update_agent(
                self._session, row.id, {"agent_runtime_config": config}
            )
            return updated or row
        return row


def _default_bundle(role: str) -> dict[str, str]:
    bundle_role = "ceo" if role == "ceo" else "default"
    fallback_soul = (
        "# SOUL.md -- CEO Persona\n\nYou are the CEO.\n"
        if bundle_role == "ceo"
        else "# SOUL.md -- Agent Persona\n\nYou are an agent in this organization.\n"
    )
    fallback = {
        "MEMORY.md": "# MEMORY.md\n\nRecord stable preferences, operating patterns, and lessons learned here.\n",
        "HEARTBEAT.md": "# HEARTBEAT.md\n\nUse heartbeat runs to inspect and advance assigned work.\n",
        _ENTRY_FILE: fallback_soul,
        "TOOLS.md": "# TOOLS.md\n\nUse the available control-plane and runtime tools.\n",
    }
    files: dict[str, str] = {}
    for file_name in _DEFAULT_BUNDLE_FILES:
        path = _ONBOARDING_ROOT / bundle_role / file_name
        try:
            files[file_name] = path.read_text(encoding="utf-8")
        except OSError:
            files[file_name] = fallback[file_name]
    return files


def _write_bundle(root: Path, files: dict[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    for relative_path, content in files.items():
        target = root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or target.stat().st_size == 0:
            target.write_text(content, encoding="utf-8")


def _export_files(row: Agent) -> dict[str, str]:
    state = _bundle_state(row)
    root = state["rootPath"]
    if isinstance(root, Path) and root.is_dir():
        files = {
            relative_path: _resolve_path_within_root(root, relative_path).read_text(
                encoding="utf-8"
            )
            for relative_path in _list_files(root)
        }
        if files:
            return files
    content = _legacy_instructions(row, state)
    return {
        str(state["entryFile"]): content
        or "_No SOUL instructions were resolved from current agent config._"
    }


def _legacy_instructions(row: Agent, state: dict[str, Any]) -> str:
    config = state["config"]
    file_path = _string(config.get(_FILE_KEY))
    if file_path:
        try:
            resolved = _resolve_instructions_file_path(file_path, config)
            if resolved.is_file():
                return resolved.read_text(encoding="utf-8")
        except (OSError, ValueError):
            pass
    return _string(config.get(_PROMPT_KEY)) or ""


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _agent_home_root(row: Agent) -> Path:
    workspace_key = _slug(row.workspace_key or row.name or row.id)
    return (
        Path.cwd()
        / ".octopus"
        / "workspaces"
        / f"org_{row.org_id}"
        / "agents"
        / workspace_key
    ).resolve()


def _managed_instructions_root(row: Agent) -> Path:
    return (_agent_home_root(row) / "instructions").resolve()


def _slug(value: str) -> str:
    return value.strip().lower().replace(" ", "-") or "agent"


def _normalize_relative_file_path(value: str) -> str:
    normalized = Path(value.replace("\\", "/"))
    parts = normalized.parts
    if normalized.is_absolute() or not parts or ".." in parts:
        raise ValueError("Instructions file path must stay within the bundle root")
    text = normalized.as_posix().strip("/")
    if not text or text == ".":
        raise ValueError("Instructions file path must stay within the bundle root")
    return text


def _resolve_path_within_root(root: Path, relative_path: str) -> Path:
    normalized = _normalize_relative_file_path(relative_path)
    target = (root / normalized).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(
            "Instructions file path must stay within the bundle root"
        ) from exc
    return target


def _resolve_instructions_file_path(value: str, config: dict[str, Any]) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path.resolve()
    cwd = _string(config.get("cwd"))
    if not cwd:
        raise ValueError(
            "Legacy relative instructionsFilePath requires agentRuntimeConfig.cwd to be set to an absolute path"
        )
    cwd_path = Path(cwd).expanduser()
    if not cwd_path.is_absolute():
        raise ValueError(
            "agentRuntimeConfig.cwd must be an absolute path to resolve relative instructions path"
        )
    return (cwd_path / path).resolve()


def _bundle_state(row: Agent) -> dict[str, Any]:
    config = dict(row.agent_runtime_config)
    root = _string(config.get(_ROOT_KEY))
    file_path = _string(config.get(_FILE_KEY))
    entry_file = _string(config.get(_ENTRY_KEY)) or _ENTRY_FILE
    mode = (
        config.get(_MODE_KEY)
        if config.get(_MODE_KEY) in {"managed", "external"}
        else None
    )
    warnings: list[str] = []
    if not root and file_path:
        try:
            resolved = _resolve_instructions_file_path(file_path, config)
            root = str(resolved.parent)
            entry_file = resolved.name
            mode = (
                "managed"
                if resolved == (_managed_instructions_root(row) / entry_file).resolve()
                or _is_relative_to(resolved, _managed_instructions_root(row))
                else "external"
            )
        except ValueError as exc:
            warnings.append(str(exc))
    normalized_entry = _normalize_relative_file_path(entry_file)
    root_path = Path(root).expanduser().resolve() if root else None
    return {
        "config": config,
        "mode": mode,
        "rootPath": root_path,
        "entryFile": normalized_entry,
        "resolvedEntryPath": (root_path / normalized_entry).resolve()
        if root_path is not None
        else None,
        "warnings": warnings,
        "legacyPromptTemplateActive": bool(_string(config.get(_PROMPT_KEY))),
        "legacyBootstrapPromptTemplateActive": bool(
            _string(config.get(_BOOTSTRAP_PROMPT_KEY))
        ),
    }


def _bundle_root(row: Agent) -> Path | None:
    return _bundle_state(row)["rootPath"]


def _sync_bundle_config_from_file_path(
    row: Agent, config: dict[str, Any]
) -> dict[str, Any]:
    file_path = _string(config.get(_FILE_KEY))
    next_config = dict(config)
    if not file_path:
        next_config.pop(_MODE_KEY, None)
        next_config.pop(_ROOT_KEY, None)
        next_config.pop(_ENTRY_KEY, None)
        return next_config
    resolved = _resolve_instructions_file_path(file_path, next_config)
    mode = (
        "managed"
        if resolved == (_managed_instructions_root(row) / resolved.name).resolve()
        or _is_relative_to(resolved, _managed_instructions_root(row))
        else "external"
    )
    return _apply_bundle_config(
        next_config, mode=mode, root=resolved.parent, entry_file=resolved.name
    )


def _apply_bundle_config(
    config: dict[str, Any],
    *,
    mode: str,
    root: Path,
    entry_file: str,
    clear_legacy_prompt_template: bool = False,
) -> dict[str, Any]:
    next_config = {
        **config,
        _MODE_KEY: mode,
        _ROOT_KEY: str(root),
        _ENTRY_KEY: entry_file,
        _FILE_KEY: str((root / entry_file).resolve()),
    }
    if clear_legacy_prompt_template:
        next_config.pop(_PROMPT_KEY, None)
        next_config.pop(_BOOTSTRAP_PROMPT_KEY, None)
    return next_config


def _bundle(row: Agent) -> AgentInstructionsBundle:
    state = _bundle_state(row)
    root = state["rootPath"]
    files: list[AgentInstructionsFileSummary] = []
    if isinstance(root, Path) and root.is_dir():
        for relative_path in _list_files(root):
            files.append(_file_summary(root, relative_path, state["entryFile"]))
    if state["legacyPromptTemplateActive"]:
        legacy = _string(state["config"].get(_PROMPT_KEY)) or ""
        files.append(
            {
                "path": _PROMPT_TEMPLATE_FILE,
                "size": len(legacy),
                "language": "markdown",
                "markdown": True,
                "isEntryFile": False,
                "editable": True,
                "deprecated": True,
                "virtual": True,
            }
        )
    files.sort(key=lambda file: file["path"])
    resolved_entry = state["resolvedEntryPath"]
    return {
        "agentId": row.id,
        "orgId": row.org_id,
        "mode": state["mode"],
        "rootPath": str(root) if root is not None else None,
        "managedRootPath": str(_managed_instructions_root(row)),
        "entryFile": str(state["entryFile"]),
        "resolvedEntryPath": str(resolved_entry)
        if resolved_entry is not None
        else None,
        "editable": root is not None,
        "warnings": list(state["warnings"]),
        "legacyPromptTemplateActive": bool(state["legacyPromptTemplateActive"]),
        "legacyBootstrapPromptTemplateActive": bool(
            state["legacyBootstrapPromptTemplateActive"]
        ),
        "files": files,
    }


def _list_files(root: Path) -> list[str]:
    output: list[str] = []
    for path in root.rglob("*"):
        if path.is_dir() and path.name in _IGNORED_DIR_NAMES:
            continue
        if not path.is_file() or path.name in _IGNORED_FILE_NAMES:
            continue
        relative = path.relative_to(root).as_posix()
        if any(part in _IGNORED_DIR_NAMES for part in Path(relative).parts):
            continue
        output.append(relative)
    return sorted(output)


def _file_summary(
    root: Path, relative_path: str, entry_file: str
) -> AgentInstructionsFileSummary:
    stat = _resolve_path_within_root(root, relative_path).stat()
    return {
        "path": relative_path,
        "size": stat.st_size,
        "language": _language(relative_path),
        "markdown": relative_path.lower().endswith(".md"),
        "isEntryFile": relative_path == entry_file,
        "editable": True,
        "deprecated": False,
        "virtual": False,
    }


def _read_file(row: Agent, relative_path: str) -> AgentInstructionsFileDetail:
    state = _bundle_state(row)
    normalized = _normalize_relative_file_path(relative_path)
    if normalized == _PROMPT_TEMPLATE_FILE:
        content = _string(state["config"].get(_PROMPT_KEY))
        if content is None:
            raise FileNotFoundError("Instructions file not found")
        return {
            "path": _PROMPT_TEMPLATE_FILE,
            "size": len(content),
            "language": "markdown",
            "markdown": True,
            "isEntryFile": False,
            "editable": True,
            "deprecated": True,
            "virtual": True,
            "content": content,
        }
    root = state["rootPath"]
    if not isinstance(root, Path):
        raise FileNotFoundError("Agent instructions bundle is not configured")
    target = _resolve_path_within_root(root, normalized)
    if not target.is_file():
        raise FileNotFoundError("Instructions file not found")
    content = target.read_text(encoding="utf-8")
    return {
        **_file_summary(root, normalized, str(state["entryFile"])),
        "content": content,
    }


def _language(relative_path: str) -> str:
    lower = relative_path.lower()
    if lower.endswith(".md"):
        return "markdown"
    if lower.endswith(".json"):
        return "json"
    if lower.endswith((".yaml", ".yml")):
        return "yaml"
    if lower.endswith(".py"):
        return "python"
    if lower.endswith(".toml"):
        return "toml"
    return "text"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True
