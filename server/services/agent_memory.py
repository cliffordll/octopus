from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import shutil
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import get_agent_by_id
from packages.database.schema import Agent
from packages.shared.types.agent import (
    AgentMemoryFileDetail,
    AgentMemoryFileEntry,
    AgentMemoryFileList,
)

from .workspace_paths import agent_workspace_root

AgentMemoryLayer = Literal["memory", "life"]

_VALID_LAYERS = {"memory", "life"}
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


class AgentMemoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_files(
        self, agent_id: str, *, layer: str, directory_path: str = ""
    ) -> AgentMemoryFileList | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        root = _memory_root(row, _normalize_layer(layer))
        root.mkdir(parents=True, exist_ok=True)
        target, normalized = _resolve_within_root(root, directory_path, allow_root=True)
        if not target.is_dir():
            raise FileNotFoundError("Agent memory directory not found")
        entries: list[AgentMemoryFileEntry] = []
        for child in target.iterdir():
            if _is_ignored(child, root):
                continue
            stat = child.stat()
            entries.append(
                {
                    "name": child.name,
                    "path": _to_portable_path(child.relative_to(root)),
                    "isDirectory": child.is_dir(),
                    "size": None if child.is_dir() else stat.st_size,
                    "updatedAt": _mtime_iso(stat.st_mtime),
                }
            )
        entries.sort(key=lambda item: (not item["isDirectory"], item["name"].lower()))
        return {
            "agentId": row.id,
            "orgId": row.org_id,
            "layer": layer,
            "rootPath": str(root),
            "directoryPath": normalized,
            "entries": entries,
            "message": "This folder is empty." if not entries else None,
        }

    async def read_file(
        self, agent_id: str, *, layer: str, file_path: str
    ) -> AgentMemoryFileDetail | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        normalized_layer = _normalize_layer(layer)
        root = _memory_root(row, normalized_layer)
        root.mkdir(parents=True, exist_ok=True)
        target, normalized = _resolve_within_root(root, file_path)
        if not target.is_file():
            raise FileNotFoundError("Agent memory file not found")
        content = target.read_text(encoding="utf-8")
        stat = target.stat()
        return {
            "agentId": row.id,
            "orgId": row.org_id,
            "layer": normalized_layer,
            "rootPath": str(root),
            "filePath": normalized,
            "content": content,
            "size": stat.st_size,
            "updatedAt": _mtime_iso(stat.st_mtime),
        }

    async def write_file(
        self,
        agent_id: str,
        *,
        layer: str,
        file_path: str,
        content: str,
        actor_type: str,
        actor_id: str,
    ) -> AgentMemoryFileDetail | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        normalized_layer = _normalize_layer(layer)
        root = _memory_root(row, normalized_layer)
        root.mkdir(parents=True, exist_ok=True)
        target, normalized = _resolve_within_root(root, file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.memory_file_updated",
            entity_type="agent",
            entity_id=row.id,
            details={
                "layer": normalized_layer,
                "path": normalized,
                "size": len(content),
            },
        )
        return await self.read_file(
            row.id, layer=normalized_layer, file_path=normalized
        )

    async def delete_file(
        self,
        agent_id: str,
        *,
        layer: str,
        file_path: str,
        actor_type: str,
        actor_id: str,
    ) -> AgentMemoryFileList | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        normalized_layer = _normalize_layer(layer)
        root = _memory_root(row, normalized_layer)
        root.mkdir(parents=True, exist_ok=True)
        target, normalized = _resolve_within_root(root, file_path)
        if not target.exists():
            raise FileNotFoundError("Agent memory file not found")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.memory_file_deleted",
            entity_type="agent",
            entity_id=row.id,
            details={"layer": normalized_layer, "path": normalized},
        )
        parent = Path(normalized).parent.as_posix()
        if parent == ".":
            parent = ""
        return await self.list_files(
            row.id, layer=normalized_layer, directory_path=parent
        )


def _normalize_layer(layer: str) -> AgentMemoryLayer:
    if layer not in _VALID_LAYERS:
        raise ValueError("'layer' must be one of ['memory', 'life']")
    return layer  # type: ignore[return-value]


def _memory_root(row: Agent, layer: AgentMemoryLayer) -> Path:
    workspace_key = row.workspace_key or _slug(row.name or row.id)
    root = agent_workspace_root(row.org_id, workspace_key).resolve()
    for dirname in ("instructions", "skills", "life", "memory"):
        (root / dirname).mkdir(parents=True, exist_ok=True)
    return (root / layer).resolve()


def _slug(value: str) -> str:
    return value.strip().lower().replace(" ", "-") or "agent"


def _resolve_within_root(
    root: Path, requested_path: str, *, allow_root: bool = False
) -> tuple[Path, str]:
    normalized = _normalize_relative_path(requested_path, allow_root=allow_root)
    target = (root / normalized).resolve() if normalized else root.resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(
            "Agent memory path must stay within the selected layer"
        ) from exc
    return target, normalized


def _normalize_relative_path(value: str, *, allow_root: bool) -> str:
    normalized = Path(value.strip().replace("\\", "/"))
    parts = normalized.parts
    if normalized.is_absolute() or ".." in parts:
        raise ValueError("Agent memory path must stay within the selected layer")
    text = normalized.as_posix().strip("/")
    if text in {"", "."}:
        if allow_root:
            return ""
        raise ValueError("Agent memory file path is required")
    return text


def _to_portable_path(value: Path) -> str:
    return value.as_posix() if str(value) != "." else ""


def _is_ignored(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    if path.name in _IGNORED_FILE_NAMES:
        return True
    return any(part in _IGNORED_DIR_NAMES for part in relative.parts)


def _mtime_iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat()
