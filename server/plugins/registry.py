from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.schema import (
    Plugin,
    PluginConfig,
    PluginJob,
    PluginJobRun,
    PluginLog,
    PluginState,
    PluginWebhookDelivery,
)
from packages.shared.constants.plugins import PLUGIN_STATUSES
from packages.shared.types.plugins import PluginManifest
from packages.shared.validators.plugins import validate_plugin_manifest


class PluginRegistryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def install_plugin(
        self,
        *,
        manifest: dict[str, Any],
        source_type: str,
        source_locator: str,
    ) -> dict[str, Any]:
        validated = validate_plugin_manifest(manifest)
        existing = await self._get_by_key(validated["id"])
        fields = {
            "plugin_key": validated["id"],
            "display_name": validated["displayName"],
            "version": validated["version"],
            "source_type": source_type,
            "source_locator": source_locator,
            "manifest_json": dict(validated),
            "status": "installed",
            "enabled_at": None,
            "disabled_at": None,
            "uninstalled_at": None,
            "updated_at": _now(),
        }
        if existing is None:
            row = Plugin(**fields)
            self._session.add(row)
            await self._session.flush()
            await self._sync_jobs(row.id, validated)
            return _plugin_summary(row)
        for key, value in fields.items():
            setattr(existing, key, value)
        await self._session.flush()
        await self._sync_jobs(existing.id, validated)
        return _plugin_summary(existing)

    async def list_plugins(self, *, status: str | None = None) -> list[dict[str, Any]]:
        if status is not None and status not in PLUGIN_STATUSES:
            raise ValueError(f"Unsupported plugin status: '{status}'")
        statement = select(Plugin).order_by(Plugin.created_at.desc(), Plugin.id.desc())
        if status is not None:
            statement = statement.where(Plugin.status == status)
        result = await self._session.execute(statement)
        return [_plugin_summary(row) for row in result.scalars().all()]

    async def get_plugin(self, plugin_id: str) -> dict[str, Any]:
        return _plugin_summary(await self._get_plugin(plugin_id))

    async def enable_plugin(self, plugin_id: str) -> dict[str, Any]:
        row = await self._get_plugin(plugin_id)
        timestamp = _now()
        row.status = "ready"
        row.enabled_at = timestamp
        row.disabled_at = None
        row.uninstalled_at = None
        row.updated_at = timestamp
        await self._session.flush()
        return _plugin_summary(row)

    async def disable_plugin(
        self, plugin_id: str, *, reason: str | None = None
    ) -> dict[str, Any]:
        row = await self._get_plugin(plugin_id)
        timestamp = _now()
        row.status = "disabled"
        row.disabled_at = timestamp
        row.updated_at = timestamp
        await self._session.flush()
        return _plugin_summary(row)

    async def uninstall_plugin(self, plugin_id: str) -> dict[str, Any]:
        row = await self._get_plugin(plugin_id)
        timestamp = _now()
        row.status = "uninstalled"
        row.uninstalled_at = timestamp
        row.updated_at = timestamp
        await self._session.flush()
        return _plugin_summary(row)

    async def upsert_config(
        self, plugin_id: str, config_json: dict[str, Any]
    ) -> dict[str, Any]:
        await self._get_plugin(plugin_id)
        result = await self._session.execute(
            select(PluginConfig).where(PluginConfig.plugin_id == plugin_id)
        )
        row = result.scalar_one_or_none()
        timestamp = _now()
        if row is None:
            row = PluginConfig(plugin_id=plugin_id, config_json=config_json)
            self._session.add(row)
        else:
            row.config_json = config_json
            row.updated_at = timestamp
        await self._session.flush()
        return {
            "id": row.id,
            "pluginId": row.plugin_id,
            "configJson": row.config_json,
            "createdAt": _iso(row.created_at),
            "updatedAt": _iso(row.updated_at),
        }

    async def set_state(
        self, plugin_id: str, key: str, value_json: Any
    ) -> dict[str, Any]:
        await self._get_plugin(plugin_id)
        if not key.strip():
            raise ValueError("'key' must be a non-empty string")
        result = await self._session.execute(
            select(PluginState).where(
                PluginState.plugin_id == plugin_id, PluginState.key == key
            )
        )
        row = result.scalar_one_or_none()
        timestamp = _now()
        if row is None:
            row = PluginState(plugin_id=plugin_id, key=key, value_json=value_json)
            self._session.add(row)
        else:
            row.value_json = value_json
            row.updated_at = timestamp
        await self._session.flush()
        return {
            "id": row.id,
            "pluginId": row.plugin_id,
            "key": row.key,
            "valueJson": row.value_json,
            "createdAt": _iso(row.created_at),
            "updatedAt": _iso(row.updated_at),
        }

    async def list_jobs(self, plugin_id: str) -> list[dict[str, Any]]:
        await self._get_plugin(plugin_id)
        result = await self._session.execute(
            select(PluginJob)
            .where(PluginJob.plugin_id == plugin_id)
            .order_by(PluginJob.created_at.asc(), PluginJob.id.asc())
        )
        return [_job_summary(row) for row in result.scalars().all()]

    async def record_job_run(
        self,
        plugin_id: str,
        job_id: str,
        *,
        status: str = "queued",
        output_json: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        await self._get_plugin(plugin_id)
        job = await self._session.get(PluginJob, job_id)
        if job is None or job.plugin_id != plugin_id:
            raise LookupError("Plugin job not found")
        row = PluginJobRun(
            plugin_id=plugin_id,
            job_id=job_id,
            status=status,
            output_json=output_json,
            error=error,
        )
        self._session.add(row)
        await self._session.flush()
        return _job_run_summary(row)

    async def record_webhook_delivery(
        self,
        plugin_id: str,
        *,
        endpoint_key: str,
        request_json: dict[str, Any] | None,
        status: str = "received",
        response_json: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        await self._get_plugin(plugin_id)
        row = PluginWebhookDelivery(
            plugin_id=plugin_id,
            webhook_key=endpoint_key,
            request_json=request_json,
            status=status,
            response_json=response_json,
            error=error,
        )
        self._session.add(row)
        await self._session.flush()
        return _webhook_delivery_summary(row)

    async def add_log(
        self,
        plugin_id: str,
        *,
        level: str,
        message: str,
        details_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._get_plugin(plugin_id)
        row = PluginLog(
            plugin_id=plugin_id,
            level=level,
            message=message,
            details_json=details_json,
        )
        self._session.add(row)
        await self._session.flush()
        return _log_summary(row)

    async def list_logs(self, plugin_id: str) -> list[dict[str, Any]]:
        await self._get_plugin(plugin_id)
        result = await self._session.execute(
            select(PluginLog)
            .where(PluginLog.plugin_id == plugin_id)
            .order_by(PluginLog.created_at.desc(), PluginLog.id.desc())
        )
        return [_log_summary(row) for row in result.scalars().all()]

    async def _get_plugin(self, plugin_id: str) -> Plugin:
        row = await self._session.get(Plugin, plugin_id)
        if row is None:
            raise LookupError("Plugin not found")
        return row

    async def _get_by_key(self, plugin_key: str) -> Plugin | None:
        result = await self._session.execute(
            select(Plugin).where(Plugin.plugin_key == plugin_key)
        )
        return result.scalar_one_or_none()

    async def _sync_jobs(self, plugin_id: str, manifest: PluginManifest) -> None:
        for job in manifest.get("jobs", []):
            job_key = job.get("jobKey")
            display_name = job.get("displayName")
            if not isinstance(job_key, str) or not isinstance(display_name, str):
                raise ValueError("Plugin job manifest is missing required fields")
            result = await self._session.execute(
                select(PluginJob).where(
                    PluginJob.plugin_id == plugin_id,
                    PluginJob.job_key == job_key,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                self._session.add(
                    PluginJob(
                        plugin_id=plugin_id,
                        job_key=job_key,
                        display_name=display_name,
                        schedule=job.get("schedule"),
                    )
                )
            else:
                row.display_name = display_name
                row.schedule = job.get("schedule")
                row.updated_at = _now()
        await self._session.flush()


def _plugin_summary(row: Plugin) -> dict[str, Any]:
    manifest = cast(PluginManifest, row.manifest_json)
    return {
        "id": row.id,
        "pluginKey": row.plugin_key,
        "displayName": row.display_name,
        "version": row.version,
        "status": row.status,
        "sourceType": row.source_type,
        "sourceLocator": row.source_locator,
        "manifest": manifest,
        "installedAt": _iso(row.installed_at),
        "enabledAt": _iso(row.enabled_at),
        "disabledAt": _iso(row.disabled_at),
        "uninstalledAt": _iso(row.uninstalled_at),
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
    }


def _job_summary(row: PluginJob) -> dict[str, Any]:
    return {
        "id": row.id,
        "pluginId": row.plugin_id,
        "jobKey": row.job_key,
        "displayName": row.display_name,
        "schedule": row.schedule,
        "enabled": row.enabled,
        "createdAt": _iso(row.created_at),
        "updatedAt": _iso(row.updated_at),
    }


def _job_run_summary(row: PluginJobRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "pluginId": row.plugin_id,
        "jobId": row.job_id,
        "status": row.status,
        "outputJson": row.output_json,
        "error": row.error,
        "startedAt": _iso(row.started_at),
        "finishedAt": _iso(row.finished_at),
        "createdAt": _iso(row.created_at),
    }


def _webhook_delivery_summary(row: PluginWebhookDelivery) -> dict[str, Any]:
    return {
        "id": row.id,
        "pluginId": row.plugin_id,
        "webhookKey": row.webhook_key,
        "status": row.status,
        "requestJson": row.request_json,
        "responseJson": row.response_json,
        "error": row.error,
        "durationMs": row.duration_ms,
        "startedAt": _iso(row.started_at),
        "finishedAt": _iso(row.finished_at),
        "createdAt": _iso(row.created_at),
    }


def _log_summary(row: PluginLog) -> dict[str, Any]:
    return {
        "id": row.id,
        "pluginId": row.plugin_id,
        "level": row.level,
        "message": row.message,
        "detailsJson": row.details_json,
        "createdAt": _iso(row.created_at),
    }


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
