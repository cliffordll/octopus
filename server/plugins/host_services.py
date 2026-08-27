from __future__ import annotations

from typing import Any

from packages.shared.constants.plugins import PluginCapability

from .registry import PluginRegistryService


class PluginHostServices:
    def __init__(self, registry: PluginRegistryService, plugin_id: str) -> None:
        self._registry = registry
        self._plugin_id = plugin_id
        self._plugin: dict[str, Any] | None = None

    async def get_config(self) -> dict[str, Any]:
        await self._require_ready()
        return await self._registry.get_config(self._plugin_id)

    async def get_state(self, key: str) -> dict[str, Any] | None:
        await self._require_capability("plugin.state.read")
        return await self._registry.get_state(self._plugin_id, key)

    async def set_state(self, key: str, value_json: Any) -> dict[str, Any]:
        await self._require_capability("plugin.state.write")
        return await self._registry.set_state(self._plugin_id, key, value_json)

    async def add_log(
        self,
        *,
        level: str,
        message: str,
        details_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._require_capability("activity.log.write")
        return await self._registry.add_log(
            self._plugin_id,
            level=level,
            message=message,
            details_json=details_json,
        )

    async def upsert_entity_mapping(
        self,
        *,
        external_type: str,
        external_id: str,
        local_type: str,
        local_id: str,
        metadata_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._require_entity_mapping_capability(local_type)
        return await self._registry.upsert_entity_mapping(
            self._plugin_id,
            external_type=external_type,
            external_id=external_id,
            local_type=local_type,
            local_id=local_id,
            metadata_json=metadata_json,
        )

    async def list_entity_mappings(
        self,
        *,
        external_type: str | None = None,
        local_type: str | None = None,
    ) -> list[dict[str, Any]]:
        await self._require_entity_mapping_capability(local_type)
        return await self._registry.list_entity_mappings(
            self._plugin_id,
            external_type=external_type,
            local_type=local_type,
        )

    async def _require_entity_mapping_capability(self, local_type: str | None) -> None:
        if local_type == "issue":
            await self._require_capability("issues.read")
            return
        if local_type == "project":
            await self._require_capability("projects.read")
            return
        await self._require_ready()

    async def _require_capability(self, capability: PluginCapability) -> dict[str, Any]:
        plugin = await self._require_ready()
        capabilities = plugin["manifest"].get("capabilities", [])
        if capability not in capabilities:
            raise PermissionError(f"Plugin capability is not declared: {capability}")
        return plugin

    async def _require_ready(self) -> dict[str, Any]:
        if self._plugin is None:
            self._plugin = await self._registry.get_plugin(self._plugin_id)
        if self._plugin["status"] != "ready":
            raise ValueError("Plugin is not ready")
        return self._plugin
