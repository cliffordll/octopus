from __future__ import annotations

from collections.abc import Mapping
import re
from typing import Any, cast

from ..types.organization_skill import (
    OrganizationSkillCreatePayload,
    OrganizationSkillFileUpdatePayload,
    OrganizationSkillImportPayload,
    OrganizationSkillScanLocalPayload,
)

_CREATE_FIELDS = {"name", "slug", "description", "markdown"}
_FILE_UPDATE_FIELDS = {"path", "content"}
_IMPORT_FIELDS = {"sourcePath", "slug", "name", "description", "overwrite"}
_SCAN_LOCAL_FIELDS = {"rootPath", "importDiscovered", "overwrite"}
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def validate_create_organization_skill(
    payload: Mapping[str, Any],
) -> OrganizationSkillCreatePayload:
    _reject_unknown_fields(payload, _CREATE_FIELDS)
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("'name' is required and must be a non-empty string")
    result: dict[str, Any] = {"name": name.strip()}
    if "slug" in payload:
        slug = payload["slug"]
        if slug is None:
            result["slug"] = None
        elif isinstance(slug, str) and slug.strip():
            normalized = slug.strip()
            if not _SLUG_RE.fullmatch(normalized):
                raise ValueError(
                    "'slug' must contain lowercase letters, numbers, '-' or '_'"
                )
            result["slug"] = normalized
        else:
            raise ValueError("'slug' must be a non-empty string or null")
    if "description" in payload:
        result["description"] = _nullable_trimmed_string(payload, "description")
    if "markdown" in payload:
        markdown = payload["markdown"]
        if markdown is not None and not isinstance(markdown, str):
            raise ValueError("'markdown' must be a string or null")
        result["markdown"] = markdown
    return cast(OrganizationSkillCreatePayload, result)


def validate_update_organization_skill_file(
    payload: Mapping[str, Any],
) -> OrganizationSkillFileUpdatePayload:
    _reject_unknown_fields(payload, _FILE_UPDATE_FIELDS)
    path = payload.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("'path' is required and must be a non-empty string")
    content = payload.get("content")
    if not isinstance(content, str):
        raise ValueError("'content' is required and must be a string")
    return {"path": path.strip(), "content": content}


def validate_import_organization_skill(
    payload: Mapping[str, Any],
) -> OrganizationSkillImportPayload:
    _reject_unknown_fields(payload, _IMPORT_FIELDS)
    source_path = payload.get("sourcePath")
    if not isinstance(source_path, str) or not source_path.strip():
        raise ValueError("'sourcePath' is required and must be a non-empty string")
    result: dict[str, Any] = {"sourcePath": source_path.strip()}
    if "slug" in payload:
        slug = payload["slug"]
        if slug is None:
            result["slug"] = None
        elif isinstance(slug, str) and slug.strip():
            normalized = slug.strip()
            if not _SLUG_RE.fullmatch(normalized):
                raise ValueError(
                    "'slug' must contain lowercase letters, numbers, '-' or '_'"
                )
            result["slug"] = normalized
        else:
            raise ValueError("'slug' must be a non-empty string or null")
    if "name" in payload:
        result["name"] = _nullable_trimmed_string(payload, "name")
    if "description" in payload:
        result["description"] = _nullable_trimmed_string(payload, "description")
    if "overwrite" in payload:
        overwrite = payload["overwrite"]
        if not isinstance(overwrite, bool):
            raise ValueError("'overwrite' must be a boolean")
        result["overwrite"] = overwrite
    return cast(OrganizationSkillImportPayload, result)


def validate_scan_local_organization_skills(
    payload: Mapping[str, Any],
) -> OrganizationSkillScanLocalPayload:
    _reject_unknown_fields(payload, _SCAN_LOCAL_FIELDS)
    root_path = payload.get("rootPath")
    if not isinstance(root_path, str) or not root_path.strip():
        raise ValueError("'rootPath' is required and must be a non-empty string")
    result: dict[str, Any] = {"rootPath": root_path.strip()}
    if "importDiscovered" in payload:
        import_discovered = payload["importDiscovered"]
        if not isinstance(import_discovered, bool):
            raise ValueError("'importDiscovered' must be a boolean")
        result["importDiscovered"] = import_discovered
    if "overwrite" in payload:
        overwrite = payload["overwrite"]
        if not isinstance(overwrite, bool):
            raise ValueError("'overwrite' must be a boolean")
        result["overwrite"] = overwrite
    return cast(OrganizationSkillScanLocalPayload, result)


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: set[str]) -> None:
    for field in payload:
        if field not in allowed:
            raise ValueError(f"Unsupported field: '{field}'")


def _nullable_trimmed_string(payload: Mapping[str, Any], field: str) -> str | None:
    value = payload[field]
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"'{field}' must be a string or null")
    return value.strip() or None
