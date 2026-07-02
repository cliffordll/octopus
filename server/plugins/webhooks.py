from __future__ import annotations

from typing import Any

from .registry import PluginRegistryService
from .worker_manager import PluginWorkerManager


class PluginWebhookDispatcher:
    def __init__(
        self,
        registry: PluginRegistryService,
        *,
        worker_manager: PluginWorkerManager | None = None,
    ) -> None:
        self._registry = registry
        self._worker_manager = worker_manager

    async def receive(
        self,
        plugin_id: str,
        *,
        endpoint_key: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        plugin = await self._ready_plugin(plugin_id)
        self._require_declared_endpoint(plugin, endpoint_key)
        if self._worker_manager is None or not self._worker_manager.is_running(
            plugin_id
        ):
            delivery = await self._registry.record_webhook_delivery(
                plugin_id,
                endpoint_key=endpoint_key,
                request_json=payload,
                status="received",
            )
            await self._registry.add_log(
                plugin_id,
                level="info",
                message="Webhook received",
                details_json={"endpointKey": endpoint_key},
            )
            return delivery
        try:
            response = await self._worker_manager.handle_webhook(
                plugin_id,
                endpoint_key=endpoint_key,
                payload=payload,
                headers=headers,
            )
        except Exception as exc:
            await self._registry.add_log(
                plugin_id,
                level="error",
                message="Webhook failed",
                details_json={"endpointKey": endpoint_key, "error": str(exc)},
            )
            return await self._registry.record_webhook_delivery(
                plugin_id,
                endpoint_key=endpoint_key,
                request_json=payload,
                status="failed",
                error=str(exc),
            )
        await self._registry.add_log(
            plugin_id,
            level="info",
            message="Webhook handled",
            details_json={"endpointKey": endpoint_key},
        )
        return await self._registry.record_webhook_delivery(
            plugin_id,
            endpoint_key=endpoint_key,
            request_json=payload,
            status="succeeded",
            response_json=response,
        )

    async def _ready_plugin(self, plugin_id: str) -> dict[str, Any]:
        plugin = await self._registry.get_plugin(plugin_id)
        if plugin["status"] != "ready":
            raise ValueError("Plugin is not ready")
        capabilities = plugin["manifest"].get("capabilities", [])
        if "webhooks.receive" not in capabilities:
            raise PermissionError("Plugin capability is not declared: webhooks.receive")
        return plugin

    def _require_declared_endpoint(
        self,
        plugin: dict[str, Any],
        endpoint_key: str,
    ) -> None:
        endpoints = {
            webhook.get("endpointKey")
            for webhook in plugin["manifest"].get("webhooks", [])
            if isinstance(webhook, dict)
        }
        if endpoint_key not in endpoints:
            raise LookupError("Plugin webhook endpoint not found")
