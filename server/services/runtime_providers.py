from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.runtime_providers import (
    create_llm_model,
    create_llm_provider,
    create_llm_provider_binding,
    create_llm_runtime_default,
    delete_llm_model,
    delete_llm_models_for_provider,
    delete_llm_provider,
    delete_llm_provider_bindings,
    get_llm_model,
    get_llm_provider,
    get_llm_provider_binding,
    get_llm_runtime_default,
    list_llm_models,
    list_llm_providers,
    update_llm_model,
    update_llm_provider,
    update_llm_provider_binding,
)
from packages.database.schema import LlmModel, LlmProvider, LlmProviderBinding

REDACTED_API_KEY = "***REDACTED***"
INSTANCE_SCOPE = "instance"
ORGANIZATION_SCOPE = "organization"
AGENT_SCOPE = "agent"
MANAGED_RUNTIME_PROVIDER_TYPES = frozenset(
    {"opencode_local", "codex_local", "claude_local", "openclaw_local"}
)


class RuntimeProviderService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_providers(
        self, org_id: str, runtime_type: str
    ) -> list[dict[str, Any]]:
        del org_id
        _required_text(runtime_type, "runtimeType")
        rows = await list_llm_providers(self._session)
        return [await self._to_provider(row) for row in rows]

    async def list_llm_providers(self) -> list[dict[str, Any]]:
        rows = await list_llm_providers(self._session)
        return [await self._to_provider(row) for row in rows]

    async def create_provider(
        self,
        org_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> dict[str, Any]:
        fields = _provider_create_fields(payload)
        existing = await get_llm_provider(self._session, fields["provider_id"])
        if existing:
            raise ValueError("Runtime provider already exists")
        row = await create_llm_provider(self._session, fields)
        binding = await create_llm_provider_binding(
            self._session,
            _binding_fields(
                row.provider_id,
                payload,
                scope_type=INSTANCE_SCOPE,
                scope_id="",
            ),
        )
        await self._log(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_provider.created",
            entity_id=row.id,
            details={"scope": INSTANCE_SCOPE, "providerId": row.provider_id},
        )
        return _to_provider(row, binding)

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
        provider_id = _required_text(provider_id, "providerId")
        existing = await get_llm_provider(self._session, provider_id)
        if existing is None:
            return None
        provider_values = _provider_update_fields(payload)
        binding_values = _binding_update_fields(payload)
        row = (
            await update_llm_provider(self._session, provider_id, provider_values)
            if provider_values
            else existing
        )
        binding = await get_llm_provider_binding(
            self._session, INSTANCE_SCOPE, "", provider_id
        )
        if binding is None:
            binding = await create_llm_provider_binding(
                self._session,
                _binding_fields(
                    provider_id, {}, scope_type=INSTANCE_SCOPE, scope_id=""
                ),
            )
        if binding_values:
            binding = await update_llm_provider_binding(
                self._session, INSTANCE_SCOPE, "", provider_id, binding_values
            )
        if row is None or binding is None:
            return None
        await self._log(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_provider.updated",
            entity_id=row.id,
            details={"scope": INSTANCE_SCOPE, "providerId": provider_id},
        )
        return _to_provider(row, binding)

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
        existing = await get_llm_provider(self._session, provider_id)
        if existing is None:
            return None
        detail = await self._to_provider(existing)
        await delete_llm_models_for_provider(self._session, provider_id)
        await delete_llm_provider_bindings(self._session, provider_id)
        row = await delete_llm_provider(self._session, provider_id)
        if row is None:
            return None
        await self._log(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_provider.deleted",
            entity_id=row.id,
            details={"scope": INSTANCE_SCOPE, "providerId": provider_id},
        )
        return detail

    async def list_models(
        self, org_id: str, runtime_type: str, provider_id: str
    ) -> list[dict[str, Any]]:
        del org_id
        _required_text(runtime_type, "runtimeType")
        await self._require_provider(provider_id)
        rows = await list_llm_models(self._session, provider_id)
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
        await self._require_provider(provider_id)
        fields = _model_create_fields(provider_id, payload)
        existing = await get_llm_model(self._session, provider_id, fields["model_id"])
        if existing:
            raise ValueError("Runtime model already exists")
        row = await create_llm_model(self._session, fields)
        await self._ensure_default_model(
            runtime_type=runtime_type,
            provider_id=provider_id,
            model_id=row.model_id,
        )
        await self._log(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_model.created",
            entity_id=row.id,
            details={
                "scope": INSTANCE_SCOPE,
                "runtimeType": None,
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
        existing = await get_llm_model(self._session, provider_id, model_id)
        if existing is None:
            return None
        values = _model_update_fields(payload)
        row = (
            await update_llm_model(self._session, provider_id, model_id, values)
            if values
            else existing
        )
        if row is None:
            return None
        await self._log(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_model.updated",
            entity_id=row.id,
            details={
                "scope": INSTANCE_SCOPE,
                "runtimeType": None,
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
        existing = await get_llm_model(self._session, provider_id, model_id)
        if existing is None:
            return None
        detail = _to_model(existing)
        row = await delete_llm_model(self._session, provider_id, model_id)
        if row is None:
            return None
        await self._log(
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="runtime_model.deleted",
            entity_id=row.id,
            details={
                "scope": INSTANCE_SCOPE,
                "runtimeType": None,
                "providerId": provider_id,
                "modelId": model_id,
            },
        )
        return detail

    async def _require_provider(self, provider_id: str) -> LlmProvider:
        row = await get_llm_provider(self._session, provider_id)
        if row is None:
            raise LookupError("Runtime provider not found")
        return row

    async def _ensure_default_model(
        self,
        *,
        runtime_type: str,
        provider_id: str,
        model_id: str,
    ) -> None:
        existing = await get_llm_runtime_default(
            self._session, INSTANCE_SCOPE, "", runtime_type
        )
        if existing is not None:
            return
        await create_llm_runtime_default(
            self._session,
            {
                "id": str(uuid.uuid4()),
                "scope_type": INSTANCE_SCOPE,
                "scope_id": "",
                "runtime_type": runtime_type,
                "provider_id": provider_id,
                "model_id": model_id,
            },
        )

    async def _to_provider(self, provider: LlmProvider) -> dict[str, Any]:
        binding = await get_llm_provider_binding(
            self._session, INSTANCE_SCOPE, "", provider.provider_id
        )
        return _to_provider(provider, binding)

    async def _log(
        self,
        *,
        org_id: str,
        actor_type: str,
        actor_id: str,
        action: str,
        entity_id: str,
        details: dict[str, Any],
    ) -> None:
        if not org_id:
            return
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type="runtime_provider",
            entity_id=entity_id,
            details=details,
        )


async def inject_runtime_provider_config(
    session: AsyncSession,
    *,
    org_id: str,
    runtime_type: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    if runtime_type not in MANAGED_RUNTIME_PROVIDER_TYPES:
        return config
    model_ref = config.get("model")
    if not isinstance(model_ref, str) or "/" not in model_ref:
        default = await get_llm_runtime_default(
            session, ORGANIZATION_SCOPE, org_id, runtime_type
        )
        if default is None:
            default = await get_llm_runtime_default(
                session, INSTANCE_SCOPE, "", runtime_type
            )
        if default is None:
            return config
        provider_id = default.provider_id
        model_id = default.model_id
    else:
        provider_id, model_id = model_ref.split("/", 1)
        provider_id = provider_id.strip()
        model_id = model_id.strip()
    if not provider_id or not model_id:
        return config
    provider = await get_llm_provider(session, provider_id)
    if provider is None:
        return config
    if not provider.enabled:
        raise ValueError(f"Runtime provider is disabled: {provider_id}")
    binding = await get_llm_provider_binding(
        session, ORGANIZATION_SCOPE, org_id, provider_id
    )
    if binding is None:
        binding = await get_llm_provider_binding(
            session, INSTANCE_SCOPE, "", provider_id
        )
    if binding is None:
        return config
    if not binding.enabled:
        raise ValueError(f"Runtime provider is disabled: {provider_id}")
    model = await get_llm_model(session, provider_id, model_id)
    if model is None:
        raise ValueError(f"Runtime model is not configured: {model_ref}")
    if not model.enabled:
        raise ValueError(f"Runtime model is disabled: {model_ref}")

    runtime_context = config.get("_octopus")
    if not isinstance(runtime_context, dict):
        runtime_context = {}
    return {
        **config,
        "_octopus": {
            **runtime_context,
            "runtimeProvider": _to_execution_provider(provider, binding, model),
        },
    }


def _provider_create_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "provider_id": _required_text(payload.get("providerId"), "providerId"),
        "name": _required_text(payload.get("name"), "name"),
        "protocol": _required_text(payload.get("protocol"), "protocol"),
        "npm_package": _optional_text(payload.get("npmPackage"), "npmPackage"),
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
    if "enabled" in payload:
        values["enabled"] = bool(payload.get("enabled"))
    return values


def _binding_fields(
    provider_id: str,
    payload: Mapping[str, Any],
    *,
    scope_type: str,
    scope_id: str,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "scope_type": scope_type,
        "scope_id": scope_id,
        "provider_id": provider_id,
        "base_url": _optional_text(payload.get("baseUrl"), "baseUrl"),
        "api_key": _optional_api_key(payload.get("apiKey")),
        "config_json": _optional_dict(payload.get("config"), "config"),
        "enabled": bool(payload.get("enabled", True)),
        "priority": int(payload.get("priority", 0) or 0),
    }


def _binding_update_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if "baseUrl" in payload:
        values["base_url"] = _optional_text(payload.get("baseUrl"), "baseUrl")
    if "apiKey" in payload and payload.get("apiKey") != REDACTED_API_KEY:
        values["api_key"] = _optional_api_key(payload.get("apiKey"))
    if "config" in payload:
        values["config_json"] = _optional_dict(payload.get("config"), "config")
    if "enabled" in payload:
        values["enabled"] = bool(payload.get("enabled"))
    if "priority" in payload:
        values["priority"] = int(payload.get("priority") or 0)
    return values


def _model_create_fields(
    provider_id: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
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


def _to_provider(
    provider: LlmProvider,
    binding: LlmProviderBinding | None,
) -> dict[str, Any]:
    has_api_key = bool(binding and binding.api_key)
    return {
        "id": provider.id,
        "scope": INSTANCE_SCOPE,
        "orgId": None,
        "runtimeType": None,
        "providerId": provider.provider_id,
        "name": provider.name,
        "protocol": provider.protocol,
        "npmPackage": provider.npm_package,
        "baseUrl": binding.base_url if binding else None,
        "apiKey": REDACTED_API_KEY if has_api_key else None,
        "hasApiKey": has_api_key,
        "config": binding.config_json if binding else {},
        "enabled": provider.enabled and (binding.enabled if binding else True),
        "createdAt": provider.created_at.isoformat(),
        "updatedAt": provider.updated_at.isoformat(),
    }


def _to_model(row: LlmModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "scope": INSTANCE_SCOPE,
        "orgId": None,
        "runtimeType": None,
        "providerId": row.provider_id,
        "modelId": row.model_id,
        "displayName": row.display_name,
        "metadata": row.metadata_json,
        "enabled": row.enabled,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
    }


def _to_execution_provider(
    provider: LlmProvider, binding: LlmProviderBinding, model: LlmModel
) -> dict[str, Any]:
    return {
        "providerId": provider.provider_id,
        "name": provider.name,
        "protocol": provider.protocol,
        "npmPackage": provider.npm_package,
        "baseUrl": binding.base_url,
        "apiKey": binding.api_key,
        "config": binding.config_json,
        "model": {
            "modelId": model.model_id,
            "displayName": model.display_name,
            "metadata": model.metadata_json,
        },
    }
