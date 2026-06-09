from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from packages.shared.api_paths.plugins import (
    PLUGIN_AVAILABLE_PATH,
    PLUGIN_EXAMPLES_PATH,
    PLUGIN_LIST_PATH,
)

from ..services.plugin_catalog import PluginCatalog, load_plugin_catalog

router = APIRouter(tags=["plugins"])


@router.get(PLUGIN_LIST_PATH)
async def list_plugins_route(request: Request) -> dict[str, Any]:
    catalog = _load_catalog(request)
    return _catalog_response(catalog)


@router.get(PLUGIN_AVAILABLE_PATH)
async def list_available_plugins_route(request: Request) -> dict[str, Any]:
    catalog = _load_catalog(request)
    return _catalog_response(catalog)


@router.get(PLUGIN_EXAMPLES_PATH)
async def list_example_plugins_route(request: Request) -> dict[str, Any]:
    catalog = _load_catalog(request)
    return _catalog_response(catalog, examples_only=True)


def _load_catalog(request: Request) -> PluginCatalog:
    root = getattr(
        request.app.state,
        "plugin_catalog_root",
        Path("packages") / "plugins" / "examples",
    )
    return load_plugin_catalog(root)


def _catalog_response(
    catalog: PluginCatalog, *, examples_only: bool = False
) -> dict[str, Any]:
    entries = [
        entry
        for entry in catalog.entries
        if not examples_only or entry.example is True
    ]
    return {
        "items": [
            {
                "id": entry.plugin_id,
                "displayName": entry.display_name,
                "version": entry.version,
                "sourcePath": str(entry.source_path),
                "example": entry.example,
                "manifest": entry.manifest,
            }
            for entry in entries
        ],
        "errors": [
            {
                "id": error.plugin_id,
                "manifestPath": str(error.manifest_path),
                "message": error.message,
            }
            for error in catalog.errors
        ],
    }
