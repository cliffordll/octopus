from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.api_paths.plugins import (
    PLUGIN_AVAILABLE_PATH,
    PLUGIN_CONFIG_PATH,
    PLUGIN_DISABLE_PATH,
    PLUGIN_ENABLE_PATH,
    PLUGIN_EXAMPLES_PATH,
    PLUGIN_INSTALL_PATH,
    PLUGIN_LIST_PATH,
    PLUGIN_DETAIL_PATH,
)

from ..dependencies.database import get_session
from ..services.plugin_catalog import PluginCatalog, load_plugin_catalog
from ..services.plugin_registry import PluginRegistryService

router = APIRouter(tags=["plugins"])


@router.get(PLUGIN_LIST_PATH)
async def list_plugins_route(
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    return await PluginRegistryService(session).list_plugins()


@router.post(PLUGIN_INSTALL_PATH, status_code=status.HTTP_201_CREATED)
async def install_plugin_route(
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        manifest = body.get("manifest")
        if not isinstance(manifest, dict):
            raise ValueError("'manifest' is required and must be an object")
        return await PluginRegistryService(session).install_plugin(
            manifest=manifest,
            source_type=_required_body_string(body, "sourceType"),
            source_locator=_required_body_string(body, "sourceLocator"),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.delete(PLUGIN_DETAIL_PATH)
async def uninstall_plugin_route(
    pluginId: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await PluginRegistryService(session).uninstall_plugin(pluginId)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.get(PLUGIN_AVAILABLE_PATH)
async def list_available_plugins_route(request: Request) -> dict[str, Any]:
    catalog = _load_catalog(request)
    return _catalog_response(catalog)


@router.get(PLUGIN_EXAMPLES_PATH)
async def list_example_plugins_route(request: Request) -> dict[str, Any]:
    catalog = _load_catalog(request)
    return _catalog_response(catalog, examples_only=True)


@router.post(PLUGIN_ENABLE_PATH)
async def enable_plugin_route(
    pluginId: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        return await PluginRegistryService(session).enable_plugin(pluginId)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(PLUGIN_DISABLE_PATH)
async def disable_plugin_route(
    pluginId: str,
    body: dict[str, Any] | None = Body(default=None),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        reason = body.get("reason") if isinstance(body, dict) else None
        return await PluginRegistryService(session).disable_plugin(
            pluginId,
            reason=reason if isinstance(reason, str) else None,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(PLUGIN_CONFIG_PATH)
async def save_plugin_config_route(
    pluginId: str,
    body: dict[str, Any] = Body(...),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        config_json = body.get("configJson")
        if not isinstance(config_json, dict):
            raise ValueError("'configJson' is required and must be an object")
        return await PluginRegistryService(session).upsert_config(pluginId, config_json)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


def _load_catalog(request: Request) -> PluginCatalog:
    root = getattr(
        request.app.state,
        "plugin_catalog_root",
        Path("packages") / "plugins" / "examples",
    )
    return load_plugin_catalog(root)


def _required_body_string(body: dict[str, Any], field: str) -> str:
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' is required and must be a non-empty string")
    return value


def _catalog_response(
    catalog: PluginCatalog, *, examples_only: bool = False
) -> dict[str, Any]:
    entries = [
        entry for entry in catalog.entries if not examples_only or entry.example is True
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
