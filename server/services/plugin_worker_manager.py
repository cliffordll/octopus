from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol


class PluginWorkerHandle(Protocol):
    def call(
        self, method: str, params: dict[str, Any]
    ) -> Awaitable[dict[str, Any]]: ...


class PluginWorkerManager:
    def __init__(self) -> None:
        self._workers: dict[str, PluginWorkerHandle] = {}

    def register_worker(self, plugin_id: str, worker: PluginWorkerHandle) -> None:
        self._workers[plugin_id] = worker

    def unregister_worker(self, plugin_id: str) -> None:
        self._workers.pop(plugin_id, None)

    def is_running(self, plugin_id: str) -> bool:
        return plugin_id in self._workers

    async def call(
        self, plugin_id: str, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        worker = self._workers.get(plugin_id)
        if worker is None:
            raise LookupError("Plugin worker is not running")
        return await worker.call(method, params)

    async def validate_config(
        self, plugin_id: str, config: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.call(plugin_id, "validateConfig", {"config": config})

    async def handle_webhook(
        self,
        plugin_id: str,
        *,
        endpoint_key: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return await self.call(
            plugin_id,
            "handleWebhook",
            {
                "endpointKey": endpoint_key,
                "payload": payload,
                "headers": headers or {},
            },
        )


PluginWorkerFactory = Callable[[str], PluginWorkerHandle]
