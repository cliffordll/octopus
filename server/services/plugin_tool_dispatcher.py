from __future__ import annotations

from typing import Any

from packages.shared.constants.plugins import PLUGIN_CAPABILITIES

from .plugin_registry import PluginRegistryService
from .plugin_worker_manager import PluginWorkerManager


class PluginToolDispatcher:
    def __init__(
        self,
        registry: PluginRegistryService,
        worker_manager: PluginWorkerManager,
    ) -> None:
        self._registry = registry
        self._worker_manager = worker_manager

    async def discover_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for plugin in await self._registry.list_plugins(status="ready"):
            manifest = plugin["manifest"]
            capabilities = manifest.get("capabilities", [])
            if "agent.tools.register" not in capabilities:
                continue
            for tool in manifest.get("tools", []):
                tools.append(
                    {
                        "pluginId": plugin["id"],
                        "pluginKey": plugin["pluginKey"],
                        "name": tool["name"],
                        "displayName": tool["displayName"],
                        "description": tool["description"],
                        "parametersSchema": tool.get("parametersSchema", {}),
                    }
                )
        return tools

    async def execute_tool(
        self,
        plugin_id: str,
        tool_name: str,
        parameters: dict[str, Any],
        *,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        plugin = await self._registry.get_plugin(plugin_id)
        if plugin["status"] != "ready":
            raise ValueError("Plugin is not ready")
        manifest = plugin["manifest"]
        capabilities = manifest.get("capabilities", [])
        if "agent.tools.register" not in capabilities:
            raise ValueError("Plugin does not register agent tools")
        tools = {tool["name"]: tool for tool in manifest.get("tools", [])}
        if tool_name not in tools:
            raise LookupError("Plugin tool not found")
        if "agent.tools.register" not in PLUGIN_CAPABILITIES:
            raise RuntimeError("Plugin tool capability is not configured")
        return await self._worker_manager.call(
            plugin_id,
            "executeTool",
            {
                "toolName": tool_name,
                "parameters": parameters,
                "context": context,
            },
        )
