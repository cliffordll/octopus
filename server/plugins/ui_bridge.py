from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from packages.shared.constants.plugins import PluginUiSlotType

from .registry import PluginRegistryService
from .worker_manager import PluginWorkerManager


class PluginUiBridge:
    def __init__(
        self,
        registry: PluginRegistryService,
        *,
        worker_manager: PluginWorkerManager | None = None,
    ) -> None:
        self._registry = registry
        self._worker_manager = worker_manager

    async def list_contributions(
        self,
        *,
        slot_type: PluginUiSlotType | None = None,
        entity_type: str | None = None,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for plugin in await self._registry.list_plugins(status="ready"):
            manifest = plugin["manifest"]
            for slot in manifest.get("ui", {}).get("slots", []):
                if slot_type is not None and slot.get("type") != slot_type:
                    continue
                if not _slot_matches_entity(slot, entity_type):
                    continue
                items.append(
                    {
                        **slot,
                        "pluginId": plugin["id"],
                        "pluginKey": plugin["pluginKey"],
                        "pluginDisplayName": plugin["displayName"],
                        "assetBaseUrl": f"/api/plugins/{plugin['id']}/static/",
                    }
                )
        items.sort(
            key=lambda item: (item.get("order", 0), item["pluginKey"], item["id"])
        )
        return {"items": items}

    async def get_data(
        self,
        plugin_id: str,
        *,
        key: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        plugin = await self._ready_plugin(plugin_id)
        if self._worker_manager is None:
            raise LookupError("Plugin worker manager is not configured")
        result = await self._worker_manager.get_data(
            plugin_id,
            key=key,
            context=context,
        )
        return {
            "pluginId": plugin["id"],
            "pluginKey": plugin["pluginKey"],
            "key": key,
            "result": result,
        }

    async def perform_action(
        self,
        plugin_id: str,
        *,
        key: str,
        input_json: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        plugin = await self._ready_plugin(plugin_id)
        if self._worker_manager is None:
            raise LookupError("Plugin worker manager is not configured")
        result = await self._worker_manager.perform_action(
            plugin_id,
            key=key,
            input_json=input_json,
            context=context,
        )
        return {
            "pluginId": plugin["id"],
            "pluginKey": plugin["pluginKey"],
            "key": key,
            "result": result,
        }

    async def static_asset_path(self, plugin_id: str, asset_path: str) -> Path:
        plugin = await self._ready_plugin(plugin_id)
        manifest = plugin["manifest"]
        ui_entrypoint = manifest.get("entrypoints", {}).get("ui")
        if not isinstance(ui_entrypoint, str) or not ui_entrypoint.strip():
            raise LookupError("Plugin does not declare a UI entrypoint")
        root = _resolve_plugin_path(plugin["sourceLocator"], ui_entrypoint)
        asset = (root / asset_path).resolve()
        if root != asset and root not in asset.parents:
            raise ValueError("Plugin asset path escapes the UI entrypoint")
        if not asset.is_file():
            raise LookupError("Plugin UI asset not found")
        return asset

    async def stream_events(self, plugin_id: str) -> AsyncIterator[str]:
        plugin = await self._ready_plugin(plugin_id)
        payload = {
            "type": "plugin.ui.ready",
            "pluginId": plugin["id"],
            "pluginKey": plugin["pluginKey"],
        }
        yield f"event: plugin.ui.ready\ndata: {json.dumps(payload, separators=(',', ':'))}\n\n"

    async def _ready_plugin(self, plugin_id: str) -> dict[str, Any]:
        plugin = await self._registry.get_plugin(plugin_id)
        if plugin["status"] != "ready":
            raise ValueError("Plugin is not ready")
        return plugin


def _resolve_plugin_path(source_locator: str, entrypoint: str) -> Path:
    source_root = Path(source_locator)
    if not source_root.is_absolute():
        source_root = Path.cwd() / source_root
    normalized_entrypoint = entrypoint.removeprefix("./")
    return (source_root / normalized_entrypoint).resolve()


def _slot_matches_entity(slot: dict[str, Any], entity_type: str | None) -> bool:
    if entity_type is None:
        return True
    entity_types = slot.get("entityTypes")
    return isinstance(entity_types, list) and entity_type in entity_types
