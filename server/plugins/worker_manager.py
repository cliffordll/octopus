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

    async def activate_plugin(
        self,
        plugin_id: str,
        worker: PluginWorkerHandle,
        *,
        manifest: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        self.register_worker(plugin_id, worker)
        try:
            return await worker.call(
                "activate",
                {
                    "pluginId": plugin_id,
                    "manifest": manifest,
                    "config": config,
                },
            )
        except Exception:
            self.unregister_worker(plugin_id)
            raise

    async def deactivate_plugin(self, plugin_id: str) -> dict[str, Any]:
        worker = self._workers.get(plugin_id)
        if worker is None:
            return {"deactivated": False}
        try:
            return await worker.call("deactivate", {"pluginId": plugin_id})
        finally:
            self.unregister_worker(plugin_id)

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

    async def get_data(
        self,
        plugin_id: str,
        *,
        key: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.call(
            plugin_id,
            "getData",
            {
                "key": key,
                "context": context,
            },
        )

    async def perform_action(
        self,
        plugin_id: str,
        *,
        key: str,
        input_json: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.call(
            plugin_id,
            "performAction",
            {
                "key": key,
                "input": input_json,
                "context": context,
            },
        )

    async def run_job(
        self,
        plugin_id: str,
        *,
        job_id: str,
        job_key: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return await self.call(
            plugin_id,
            "runJob",
            {
                "jobId": job_id,
                "jobKey": job_key,
                "context": context,
            },
        )


PluginWorkerFactory = Callable[[str], PluginWorkerHandle]
