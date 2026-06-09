from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from jsonschema import Draft202012Validator, SchemaError

from ..constants.plugins import PLUGIN_CAPABILITIES, PLUGIN_UI_SLOT_TYPES
from ..types.plugins import PluginManifest

_MANIFEST_FIELDS = {
    "id",
    "apiVersion",
    "version",
    "displayName",
    "description",
    "author",
    "categories",
    "capabilities",
    "entrypoints",
    "instanceConfigSchema",
    "ui",
    "jobs",
    "webhooks",
    "tools",
}


def validate_plugin_manifest(payload: Mapping[str, Any]) -> PluginManifest:
    _reject_unknown_fields(payload, allowed_fields=_MANIFEST_FIELDS)
    result = dict(payload)
    _required_string(payload, "id")
    if payload.get("apiVersion") != 1:
        raise ValueError("'apiVersion' must be 1")
    _required_string(payload, "version")
    _required_string(payload, "displayName")
    for field in ("description", "author"):
        _optional_string(payload, field)
    _validate_string_list(payload, "categories", required=False)
    _validate_capabilities(payload)
    _validate_entrypoints(payload)
    _validate_json_schema(payload, "instanceConfigSchema")
    _validate_ui(payload)
    _validate_jobs(payload)
    _validate_webhooks(payload)
    _validate_tools(payload)
    return cast(PluginManifest, result)


def _reject_unknown_fields(
    payload: Mapping[str, Any], *, allowed_fields: set[str]
) -> None:
    for field in payload:
        if field not in allowed_fields:
            raise ValueError(f"Unsupported field: '{field}'")


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"'{field}' is required and must be a non-empty string")
    return value


def _optional_string(payload: Mapping[str, Any], field: str) -> None:
    if field in payload and not isinstance(payload[field], str):
        raise ValueError(f"'{field}' must be a string")


def _validate_string_list(
    payload: Mapping[str, Any], field: str, *, required: bool
) -> None:
    if field not in payload:
        if required:
            raise ValueError(f"'{field}' is required")
        return
    value = payload[field]
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"'{field}' must be an array of strings")


def _validate_capabilities(payload: Mapping[str, Any]) -> None:
    _validate_string_list(payload, "capabilities", required=True)
    allowed = set(PLUGIN_CAPABILITIES)
    for capability in payload["capabilities"]:
        if capability not in allowed:
            raise ValueError(f"Unsupported plugin capability: '{capability}'")


def _validate_entrypoints(payload: Mapping[str, Any]) -> None:
    entrypoints = payload.get("entrypoints")
    if not isinstance(entrypoints, Mapping):
        raise ValueError("'entrypoints' is required and must be an object")
    if "worker" not in entrypoints and "ui" not in entrypoints:
        raise ValueError("'entrypoints' must define worker or ui")
    for key in ("worker", "ui"):
        if key in entrypoints:
            value = entrypoints[key]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"'entrypoints.{key}' must be a non-empty string")


def _validate_json_schema(payload: Mapping[str, Any], field: str) -> None:
    if field not in payload:
        return
    value = payload[field]
    if not isinstance(value, Mapping):
        raise ValueError(f"'{field}' must be a JSON schema object")
    try:
        Draft202012Validator.check_schema(value)
    except SchemaError as exc:
        raise ValueError(f"'{field}' must be a valid JSON schema") from exc


def _validate_ui(payload: Mapping[str, Any]) -> None:
    if "ui" not in payload:
        return
    ui = payload["ui"]
    if not isinstance(ui, Mapping):
        raise ValueError("'ui' must be an object")
    slots = ui.get("slots", [])
    if not isinstance(slots, list):
        raise ValueError("'ui.slots' must be an array")
    allowed_slot_types = set(PLUGIN_UI_SLOT_TYPES)
    for slot in slots:
        if not isinstance(slot, Mapping):
            raise ValueError("'ui.slots' entries must be objects")
        slot_type = slot.get("type")
        if slot_type not in allowed_slot_types:
            raise ValueError(f"Unsupported plugin UI slot type: '{slot_type}'")
        _required_string(slot, "id")
        _required_string(slot, "displayName")
        _required_string(slot, "exportName")
        if "routePath" in slot:
            _optional_string(slot, "routePath")
        if "entityTypes" in slot:
            if not isinstance(slot["entityTypes"], list) or not all(
                isinstance(item, str) for item in slot["entityTypes"]
            ):
                raise ValueError("'ui.slots.entityTypes' must be an array of strings")
        if "order" in slot and not isinstance(slot["order"], int):
            raise ValueError("'ui.slots.order' must be an integer")


def _validate_jobs(payload: Mapping[str, Any]) -> None:
    if "jobs" not in payload:
        return
    jobs = payload["jobs"]
    if not isinstance(jobs, list):
        raise ValueError("'jobs' must be an array")
    for job in jobs:
        if not isinstance(job, Mapping):
            raise ValueError("'jobs' entries must be objects")
        _required_string(job, "jobKey")
        _required_string(job, "displayName")
        if "description" in job:
            _optional_string(job, "description")
        if "schedule" in job:
            _optional_string(job, "schedule")


def _validate_webhooks(payload: Mapping[str, Any]) -> None:
    if "webhooks" not in payload:
        return
    webhooks = payload["webhooks"]
    if not isinstance(webhooks, list):
        raise ValueError("'webhooks' must be an array")
    for webhook in webhooks:
        if not isinstance(webhook, Mapping):
            raise ValueError("'webhooks' entries must be objects")
        _required_string(webhook, "endpointKey")
        _required_string(webhook, "displayName")
        if "description" in webhook:
            _optional_string(webhook, "description")


def _validate_tools(payload: Mapping[str, Any]) -> None:
    if "tools" not in payload:
        return
    tools = payload["tools"]
    if not isinstance(tools, list):
        raise ValueError("'tools' must be an array")
    for tool in tools:
        if not isinstance(tool, Mapping):
            raise ValueError("'tools' entries must be objects")
        _required_string(tool, "name")
        _required_string(tool, "displayName")
        _required_string(tool, "description")
        _validate_json_schema(tool, "parametersSchema")
