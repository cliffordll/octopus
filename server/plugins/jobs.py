from __future__ import annotations

from typing import Any

from .registry import PluginRegistryService
from .worker_manager import PluginWorkerManager


class PluginJobCoordinator:
    def __init__(
        self,
        registry: PluginRegistryService,
        *,
        worker_manager: PluginWorkerManager | None = None,
    ) -> None:
        self._registry = registry
        self._worker_manager = worker_manager

    async def trigger(
        self,
        plugin_id: str,
        job_id: str,
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._ready_plugin(plugin_id)
        job = await self._find_job(plugin_id, job_id)
        if self._worker_manager is None or not self._worker_manager.is_running(
            plugin_id
        ):
            return await self._registry.record_job_run(
                plugin_id,
                job_id,
                status="queued",
            )
        try:
            output = await self._worker_manager.run_job(
                plugin_id,
                job_id=job_id,
                job_key=job["jobKey"],
                context=context or {},
            )
        except Exception as exc:
            return await self._registry.record_job_run(
                plugin_id,
                job_id,
                status="failed",
                error=str(exc),
            )
        await self._registry.add_log(
            plugin_id,
            level="info",
            message="Job completed",
            details_json={"jobKey": job["jobKey"]},
        )
        return await self._registry.record_job_run(
            plugin_id,
            job_id,
            status="succeeded",
            output_json=output,
        )

    async def _ready_plugin(self, plugin_id: str) -> dict[str, Any]:
        plugin = await self._registry.get_plugin(plugin_id)
        if plugin["status"] != "ready":
            raise ValueError("Plugin is not ready")
        capabilities = plugin["manifest"].get("capabilities", [])
        if "jobs.schedule" not in capabilities:
            raise PermissionError("Plugin capability is not declared: jobs.schedule")
        return plugin

    async def _find_job(self, plugin_id: str, job_id: str) -> dict[str, Any]:
        for job in await self._registry.list_jobs(plugin_id):
            if job["id"] == job_id:
                return job
        raise LookupError("Plugin job not found")
