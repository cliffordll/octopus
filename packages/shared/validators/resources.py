from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ..constants.project import ORGANIZATION_RESOURCE_KINDS
from ..types.resource import (
    CreateOrganizationResourcePayload,
    UpdateOrganizationResourcePayload,
)

_ORGANIZATION_RESOURCE_FIELDS = {
    "name",
    "kind",
    "locator",
    "description",
    "metadata",
}


def validate_create_organization_resource(
    payload: Mapping[str, Any],
) -> CreateOrganizationResourcePayload:
    _reject_unknown_fields(payload)
    result = _validate_resource_fields(payload, require_name=True, require_locator=True)
    if "kind" not in result:
        raise ValueError(
            f"'kind' is required and must be one of {list(ORGANIZATION_RESOURCE_KINDS)}"
        )
    return cast(CreateOrganizationResourcePayload, result)


def validate_update_organization_resource(
    payload: Mapping[str, Any],
) -> UpdateOrganizationResourcePayload:
    _reject_unknown_fields(payload)
    return cast(
        UpdateOrganizationResourcePayload,
        _validate_resource_fields(payload, require_name=False, require_locator=False),
    )


def _reject_unknown_fields(payload: Mapping[str, Any]) -> None:
    for field in payload:
        if field not in _ORGANIZATION_RESOURCE_FIELDS:
            raise ValueError(f"Unsupported field: '{field}'")


def _validate_resource_fields(
    payload: Mapping[str, Any],
    *,
    require_name: bool,
    require_locator: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field, required in (("name", require_name), ("locator", require_locator)):
        if field not in payload:
            if required:
                raise ValueError(
                    f"'{field}' is required and must be a non-empty string"
                )
            continue
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"'{field}' must be a non-empty string when provided")
        result[field] = value.strip()

    if "kind" in payload:
        if payload["kind"] not in ORGANIZATION_RESOURCE_KINDS:
            raise ValueError(
                f"'kind' must be one of {list(ORGANIZATION_RESOURCE_KINDS)}"
            )
        result["kind"] = payload["kind"]

    if "description" in payload:
        description = payload["description"]
        if description is None:
            result["description"] = None
        elif isinstance(description, str):
            result["description"] = description.strip() or None
        else:
            raise ValueError("'description' must be a string or null")

    if "metadata" in payload:
        metadata = payload["metadata"]
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("'metadata' must be an object or null")
        result["metadata"] = metadata

    return result
