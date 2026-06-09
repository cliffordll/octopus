from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from packages.shared.types.plugins import PluginManifest
from packages.shared.validators.plugins import validate_plugin_manifest


@dataclass(frozen=True)
class PluginCatalogEntry:
    plugin_id: str
    display_name: str
    version: str
    source_path: Path
    manifest_path: Path
    readme_path: Path | None
    example: bool
    manifest: PluginManifest


@dataclass(frozen=True)
class PluginCatalogError:
    plugin_id: str
    manifest_path: Path
    message: str


@dataclass(frozen=True)
class PluginCatalog:
    entries: list[PluginCatalogEntry]
    errors: list[PluginCatalogError]


def load_plugin_catalog(root: str | Path) -> PluginCatalog:
    root_path = Path(root)
    entries: list[PluginCatalogEntry] = []
    errors: list[PluginCatalogError] = []
    if not root_path.exists():
        return PluginCatalog(entries=[], errors=[])
    for manifest_path in sorted(root_path.rglob("manifest.json")):
        if "node_modules" in manifest_path.parts:
            continue
        try:
            raw = _read_manifest(manifest_path)
            manifest = validate_plugin_manifest(raw)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(
                PluginCatalogError(
                    plugin_id=_raw_plugin_id(manifest_path),
                    manifest_path=manifest_path,
                    message=str(exc),
                )
            )
            continue
        entries.append(
            PluginCatalogEntry(
                plugin_id=manifest["id"],
                display_name=manifest["displayName"],
                version=manifest["version"],
                source_path=manifest_path.parent,
                manifest_path=manifest_path,
                readme_path=_readme_path(manifest_path.parent),
                example=True,
                manifest=manifest,
            )
        )
    return PluginCatalog(entries=entries, errors=errors)


def _read_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Plugin manifest must be an object")
    return data


def _raw_plugin_id(path: Path) -> str:
    try:
        data = _read_manifest(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return path.parent.name
    plugin_id = data.get("id")
    return plugin_id if isinstance(plugin_id, str) and plugin_id.strip() else path.parent.name


def _readme_path(plugin_dir: Path) -> Path | None:
    readme = plugin_dir / "README.md"
    return readme if readme.exists() else None
