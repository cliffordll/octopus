from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.runtime_providers import (
    create_runtime_model,
    create_runtime_provider,
    delete_runtime_model,
    delete_runtime_models_for_provider,
    delete_runtime_provider,
    get_runtime_model,
    get_runtime_provider,
    list_runtime_models,
    list_runtime_providers,
    update_runtime_model,
    update_runtime_provider,
)
from packages.database.schema import RuntimeModel, RuntimeProvider

REDACTED_API_KEY = "***REDACTED***"


class RuntimeProviderService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_providers(
        self, org_id: str, runtime_type: str
    ) -> list[dict[str, Any]]:
        rows = await list_runtime_providers(
            self._session, org_id, _required_text(runtime_type, "runtimeType")
        )
        return [_to_provider(row) for row in rows]

    async def create_provider(
        self,
        org_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> dict[str, Any]:
        fields = _provider_create_fields(org_id, payload)
        if await get_runtime_provider(
            self._session,
            org_id,
            fields["runtime_type"],
            fields["provider_id"],
        ):
            raise ValueError("Runtime provider already exists")
        row = await create_runtime_provider(self._session, fields)
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_provider.created",
            entity_type="runtime_provider",
            entity_id=row.id,
            details={
                "runtimeType": row.runtime_type,
                "providerId": row.provider_id,
            },
        )
        return _to_provider(row)

    async def update_provider(
        self,
        org_id: str,
        runtime_type: str,
        provider_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> dict[str, Any] | None:
        runtime_type = _required_text(runtime_type, "runtimeType")
        existing = await get_runtime_provider(
            self._session, org_id, runtime_type, provider_id
        )
        if existing is None:
            return None
        values = _provider_update_fields(payload)
        row = (
            await update_runtime_provider(
                self._session, org_id, runtime_type, provider_id, values
            )
            if values
            else existing
        )
        if row is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_provider.updated",
            entity_type="runtime_provider",
            entity_id=row.id,
            details={"runtimeType": runtime_type, "providerId": provider_id},
        )
        return _to_provider(row)

    async def delete_provider(
        self,
        org_id: str,
        runtime_type: str,
        provider_id: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> dict[str, Any] | None:
        runtime_type = _required_text(runtime_type, "runtimeType")
        existing = await get_runtime_provider(
            self._session, org_id, runtime_type, provider_id
        )
        if existing is None:
            return None
        detail = _to_provider(existing)
        await delete_runtime_models_for_provider(
            self._session, org_id, runtime_type, provider_id
        )
        row = await delete_runtime_provider(
            self._session, org_id, runtime_type, provider_id
        )
        if row is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_provider.deleted",
            entity_type="runtime_provider",
            entity_id=row.id,
            details={"runtimeType": runtime_type, "providerId": provider_id},
        )
        return detail

    async def list_models(
        self, org_id: str, runtime_type: str, provider_id: str
    ) -> list[dict[str, Any]]:
        runtime_type = _required_text(runtime_type, "runtimeType")
        await self._require_provider(org_id, runtime_type, provider_id)
        rows = await list_runtime_models(
            self._session, org_id, runtime_type, provider_id
        )
        return [_to_model(row) for row in rows]

    async def create_model(
        self,
        org_id: str,
        runtime_type: str,
        provider_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> dict[str, Any]:
        runtime_type = _required_text(runtime_type, "runtimeType")
        await self._require_provider(org_id, runtime_type, provider_id)
        fields = _model_create_fields(org_id, runtime_type, provider_id, payload)
        if await get_runtime_model(
            self._session,
            org_id,
            runtime_type,
            provider_id,
            fields["model_id"],
        ):
            raise ValueError("Runtime model already exists")
        row = await create_runtime_model(self._session, fields)
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_model.created",
            entity_type="runtime_model",
            entity_id=row.id,
            details={
                "runtimeType": runtime_type,
                "providerId": provider_id,
                "modelId": row.model_id,
            },
        )
        return _to_model(row)

    async def update_model(
        self,
        org_id: str,
        runtime_type: str,
        provider_id: str,
        model_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> dict[str, Any] | None:
        runtime_type = _required_text(runtime_type, "runtimeType")
        existing = await get_runtime_model(
            self._session, org_id, runtime_type, provider_id, model_id
        )
        if existing is None:
            return None
        values = _model_update_fields(payload)
        row = (
            await update_runtime_model(
                self._session, org_id, runtime_type, provider_id, model_id, values
            )
            if values
            else existing
        )
        if row is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_model.updated",
            entity_type="runtime_model",
            entity_id=row.id,
            details={
                "runtimeType": runtime_type,
                "providerId": provider_id,
                "modelId": model_id,
            },
        )
        return _to_model(row)

    async def delete_model(
        self,
        org_id: str,
        runtime_type: str,
        provider_id: str,
        model_id: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> dict[str, Any] | None:
        runtime_type = _required_text(runtime_type, "runtimeType")
        existing = await get_runtime_model(
            self._session, org_id, runtime_type, provider_id, model_id
        )
        if existing is None:
            return None
        detail = _to_model(existing)
        row = await delete_runtime_model(
            self._session, org_id, runtime_type, provider_id, model_id
        )
        if row is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_model.deleted",
            entity_type="runtime_model",
            entity_id=row.id,
            details={
                "runtimeType": runtime_type,
                "providerId": provider_id,
                "modelId": model_id,
            },
        )
        return detail

    async def _require_provider(
        self, org_id: str, runtime_type: str, provider_id: str
    ) -> RuntimeProvider:
        row = await get_runtime_provider(
            self._session, org_id, runtime_type, provider_id
        )
        if row is None:
            raise LookupError("Runtime provider not found")
        return row


def _provider_create_fields(org_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "runtime_type": _required_text(payload.get("runtimeType"), "runtimeType"),
        "provider_id": _required_text(payload.get("providerId"), "providerId"),
        "name": _required_text(payload.get("name"), "name"),
        "protocol": _required_text(payload.get("protocol"), "protocol"),
        "npm_package": _optional_text(payload.get("npmPackage"), "npmPackage"),
        "base_url": _optional_text(payload.get("baseUrl"), "baseUrl"),
        "api_key": _optional_api_key(payload.get("apiKey")),
        "config_json": _optional_dict(payload.get("config"), "config"),
        "enabled": bool(payload.get("enabled", True)),
    }


def _provider_update_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "name" in payload:
        values["name"] = _required_text(payload.get("name"), "name")
    if "protocol" in payload:
        values["protocol"] = _required_text(payload.get("protocol"), "protocol")
    if "npmPackage" in payload:
        values["npm_package"] = _optional_text(payload.get("npmPackage"), "npmPackage")
    if "baseUrl" in payload:
        values["base_url"] = _optional_text(payload.get("baseUrl"), "baseUrl")
    if "apiKey" in payload and payload.get("apiKey") != REDACTED_API_KEY:
        values["api_key"] = _optional_api_key(payload.get("apiKey"))
    if "config" in payload:
        values["config_json"] = _optional_dict(payload.get("config"), "config")
    if "enabled" in payload:
        values["enabled"] = bool(payload.get("enabled"))
    return values


def _model_create_fields(
    org_id: str, runtime_type: str, provider_id: str, payload: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "org_id": org_id,
        "runtime_type": runtime_type,
        "provider_id": provider_id,
        "model_id": _required_text(payload.get("modelId"), "modelId"),
        "display_name": _optional_text(payload.get("displayName"), "displayName"),
        "metadata_json": _optional_dict(payload.get("metadata"), "metadata"),
        "enabled": bool(payload.get("enabled", True)),
    }


def _model_update_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "displayName" in payload:
        values["display_name"] = _optional_text(
            payload.get("displayName"), "displayName"
        )
    if "metadata" in payload:
        values["metadata_json"] = _optional_dict(payload.get("metadata"), "metadata")
    if "enabled" in payload:
        values["enabled"] = bool(payload.get("enabled"))
    return values


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()


def _optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    return text or None


def _optional_api_key(value: object) -> str | None:
    return _optional_text(value, "apiKey")


def _optional_dict(value: object, field: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return dict(value)


def _to_provider(row: RuntimeProvider) -> dict[str, Any]:
    has_api_key = bool(row.api_key)
    return {
        "id": row.id,
        "orgId": row.org_id,
        "runtimeType": row.runtime_type,
        "providerId": row.provider_id,
        "name": row.name,
        "protocol": row.protocol,
        "npmPackage": row.npm_package,
        "baseUrl": row.base_url,
        "apiKey": REDACTED_API_KEY if has_api_key else None,
        "hasApiKey": has_api_key,
        "config": row.config_json,
        "enabled": row.enabled,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }


def _to_model(row: RuntimeModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "orgId": row.org_id,
        "runtimeType": row.runtime_type,
        "providerId": row.provider_id,
        "modelId": row.model_id,
        "displayName": row.display_name,
        "metadata": row.metadata_json,
        "enabled": row.enabled,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }
