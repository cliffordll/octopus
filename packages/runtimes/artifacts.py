from __future__ import annotations

import mimetypes
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import RuntimeExecutionContext, RuntimeExecutionResult


@dataclass(frozen=True)
class RuntimeArtifactEvidence:
    """Runtime-native evidence that files were written during one execution."""

    written_paths: tuple[str, ...]
    declared_paths: tuple[str, ...] = ()
    primary_paths: tuple[str, ...] = ()
    source: str = "runtime_file_event"


class RuntimeArtifactsCollector:
    """Normalize trusted runtime file events into Octopus work products."""

    _EXCLUDED_PARTS = {
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

    def collect(
        self,
        context: RuntimeExecutionContext,
        result: RuntimeExecutionResult,
    ) -> list[dict[str, Any]]:
        existing = list(result.work_products or [])
        evidence = self._evidence_from_result(result)
        if evidence is None:
            return existing
        discovered = self._collect_evidence(context, evidence)
        return self._merge(existing, discovered)

    def _evidence_from_result(
        self, result: RuntimeExecutionResult
    ) -> RuntimeArtifactEvidence | None:
        payload = result.result_json
        raw = payload.get("artifactEvidence") if isinstance(payload, dict) else None
        if not isinstance(raw, Mapping):
            return None
        written_paths = self._string_tuple(raw.get("writtenPaths"))
        if not written_paths:
            return None
        source = raw.get("source")
        return RuntimeArtifactEvidence(
            written_paths=written_paths,
            declared_paths=self._string_tuple(raw.get("declaredPaths")),
            primary_paths=self._string_tuple(raw.get("primaryPaths")),
            source=source.strip()
            if isinstance(source, str) and source.strip()
            else "runtime_file_event",
        )

    def _collect_evidence(
        self,
        context: RuntimeExecutionContext,
        evidence: RuntimeArtifactEvidence,
    ) -> list[dict[str, Any]]:
        workspace_root = self._workspace_root(context)
        if workspace_root is None:
            return []
        declared = self._normalized_relative_paths(
            workspace_root, evidence.declared_paths
        )
        primary = self._normalized_relative_paths(
            workspace_root, evidence.primary_paths
        )
        candidates: list[tuple[str, Path, bytes]] = []
        seen: set[str] = set()
        for value in evidence.written_paths:
            path = self._resolve_path(workspace_root, value)
            if path is None or not path.is_file():
                continue
            rel_path = path.relative_to(workspace_root).as_posix()
            if rel_path in seen or self._is_excluded(rel_path):
                continue
            try:
                content = path.read_bytes()
            except OSError:
                continue
            if not content:
                continue
            seen.add(rel_path)
            candidates.append((rel_path, path, content))
        if not candidates:
            return []

        primary_path = next((rel for rel, _, _ in candidates if rel in primary), None)
        if primary_path is None:
            primary_path = next(
                (rel for rel, _, _ in candidates if rel in declared),
                candidates[0][0] if len(candidates) == 1 else None,
            )

        workspace_ref = self._workspace_ref(context)
        return [
            {
                "title": rel_path,
                "type": "document"
                if path.suffix.lower() in {".md", ".txt"}
                else "artifact",
                "provider": "octopus",
                "externalId": f"runtime_artifact:{workspace_ref}:{rel_path}",
                "status": "active",
                "reviewState": "none",
                "isPrimary": rel_path == primary_path,
                "summary": "File written by the runtime during this run.",
                "content": content,
                "contentType": mimetypes.guess_type(path.name)[0]
                or "application/octet-stream",
                "filename": path.name,
                "metadata": {
                    "source": evidence.source,
                    "workspacePath": rel_path,
                    "byteSize": len(content),
                },
            }
            for rel_path, path, content in candidates
        ]

    @staticmethod
    def _merge(
        existing: list[dict[str, Any]], discovered: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        merged = list(existing)
        paths = {
            path
            for product in existing
            if isinstance((metadata := product.get("metadata")), dict)
            and isinstance((path := metadata.get("workspacePath")), str)
        }
        for product in discovered:
            metadata = product.get("metadata")
            path = metadata.get("workspacePath") if isinstance(metadata, dict) else None
            if isinstance(path, str) and path not in paths:
                merged.append(product)
                paths.add(path)
        return merged

    @staticmethod
    def _string_tuple(value: object) -> tuple[str, ...]:
        if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
            return ()
        return tuple(
            item.strip() for item in value if isinstance(item, str) and item.strip()
        )

    @classmethod
    def _normalized_relative_paths(
        cls, root: Path, values: tuple[str, ...]
    ) -> set[str]:
        normalized: set[str] = set()
        for value in values:
            path = cls._resolve_path(root, value)
            if path is not None:
                normalized.add(path.relative_to(root).as_posix())
        return normalized

    @staticmethod
    def _resolve_path(root: Path, value: str) -> Path | None:
        try:
            candidate = Path(value).expanduser()
            path = (
                candidate if candidate.is_absolute() else root / candidate
            ).resolve()
            path.relative_to(root)
        except (OSError, ValueError):
            return None
        return path

    @staticmethod
    def _workspace_root(context: RuntimeExecutionContext) -> Path | None:
        workspace_context = context.workspace
        workspace: Mapping[str, Any] | None = None
        if isinstance(workspace_context, Mapping):
            candidate = workspace_context.get("octopusWorkspace")
            workspace = (
                candidate if isinstance(candidate, Mapping) else workspace_context
            )
        cwd = workspace.get("cwd") if workspace is not None else None
        if not isinstance(cwd, str) or not cwd.strip():
            cwd = context.config.get("cwd")
        if not isinstance(cwd, str) or not cwd.strip():
            return None
        try:
            root = Path(cwd).expanduser().resolve()
        except OSError:
            return None
        return root if root.is_dir() else None

    @staticmethod
    def _workspace_ref(context: RuntimeExecutionContext) -> str:
        workspace_context = context.workspace
        if isinstance(workspace_context, Mapping):
            workspace = workspace_context.get("octopusWorkspace")
            if isinstance(workspace, Mapping):
                workspace_id = workspace.get("id")
                if isinstance(workspace_id, str) and workspace_id.strip():
                    return workspace_id.strip()
        return context.run_id

    @classmethod
    def _is_excluded(cls, rel_path: str) -> bool:
        return bool(set(Path(rel_path).parts) & cls._EXCLUDED_PARTS)
