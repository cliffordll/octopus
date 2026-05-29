from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
import uuid

from ..constants.agent import (
    AGENT_ROLES,
    AGENT_RUNTIME_TYPES,
    AGENT_STATUSES,
    DEFAULT_AGENT_ROLE,
    DEFAULT_AGENT_RUNTIME_TYPE,
)
from ..types.agent import (
    CreateAgentPayload,
    ResetAgentSessionPayload,
    UpdateAgentPayload,
)

_CREATE_FIELDS = {
    "name",
    "role",
    "title",
    "icon",
    "reportsTo",
    "capabilities",
    "desiredSkills",
    "agentRuntimeType",
    "agentRuntimeConfig",
    "runtimeConfig",
    "budgetMonthlyCents",
    "permissions",
    "metadata",
}
_UPDATE_FIELDS = (_CREATE_FIELDS - {"permissions"}) | {
    "replaceAgentRuntimeConfig",
    "status",
    "spentMonthlyCents",
}


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: set[str]) -> None:
    for field in payload:
        if field not in allowed:
            raise ValueError(f"Unsupported field: '{field}'")


def _nullable_string(payload: Mapping[str, Any], field: str) -> None:
    if (
        field in payload
        and payload[field] is not None
        and not isinstance(payload[field], str)
    ):
        raise ValueError(f"'{field}' must be a string or null")


def _record(payload: Mapping[str, Any], field: str) -> None:
    if field in payload and not isinstance(payload[field], dict):
        raise ValueError(f"'{field}' must be an object")


def _nonnegative_integer(payload: Mapping[str, Any], field: str) -> None:
    if field in payload:
        value = payload[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"'{field}' must be a non-negative integer")


def _validate_common(payload: Mapping[str, Any]) -> None:
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("'name' must be a non-empty string")
    if "role" in payload and payload["role"] not in AGENT_ROLES:
        raise ValueError(f"'role' must be one of {list(AGENT_ROLES)}")
    if (
        "agentRuntimeType" in payload
        and payload["agentRuntimeType"] not in AGENT_RUNTIME_TYPES
    ):
        raise ValueError(
            f"'agentRuntimeType' must be one of {list(AGENT_RUNTIME_TYPES)}"
        )
    for field in ("title", "icon", "capabilities"):
        _nullable_string(payload, field)
    if "reportsTo" in payload and payload["reportsTo"] is not None:
        try:
            uuid.UUID(str(payload["reportsTo"]))
        except ValueError as exc:
            raise ValueError("'reportsTo' must be a UUID or null") from exc
    for field in ("agentRuntimeConfig", "runtimeConfig"):
        _record(payload, field)
    _nonnegative_integer(payload, "budgetMonthlyCents")
    if "metadata" in payload and payload["metadata"] is not None:
        _record(payload, "metadata")
    if "desiredSkills" in payload:
        skills = payload["desiredSkills"]
        if not isinstance(skills, list) or any(
            not isinstance(skill, str) or not skill for skill in skills
        ):
            raise ValueError("'desiredSkills' must be an array of non-empty strings")


def validate_create_agent(payload: Mapping[str, Any]) -> CreateAgentPayload:
    _reject_unknown_fields(payload, _CREATE_FIELDS)
    _validate_common(payload)
    result = dict(payload)
    result.setdefault("role", DEFAULT_AGENT_ROLE)
    result.setdefault("agentRuntimeType", DEFAULT_AGENT_RUNTIME_TYPE)
    result.setdefault("agentRuntimeConfig", {})
    result.setdefault("runtimeConfig", {})
    result.setdefault("budgetMonthlyCents", 0)
    return cast(CreateAgentPayload, result)


def validate_update_agent(payload: Mapping[str, Any]) -> UpdateAgentPayload:
    _reject_unknown_fields(payload, _UPDATE_FIELDS)
    _validate_common(payload)
    if "status" in payload and payload["status"] not in AGENT_STATUSES:
        raise ValueError(f"'status' must be one of {list(AGENT_STATUSES)}")
    _nonnegative_integer(payload, "spentMonthlyCents")
    if "replaceAgentRuntimeConfig" in payload and not isinstance(
        payload["replaceAgentRuntimeConfig"], bool
    ):
        raise ValueError("'replaceAgentRuntimeConfig' must be a boolean")
    return cast(UpdateAgentPayload, dict(payload))


def validate_reset_agent_session(
    payload: Mapping[str, Any],
) -> ResetAgentSessionPayload:
    _reject_unknown_fields(payload, {"taskKey"})
    _nullable_string(payload, "taskKey")
    result = dict(payload)
    if isinstance(result.get("taskKey"), str):
        result["taskKey"] = result["taskKey"].strip() or None
    return cast(ResetAgentSessionPayload, result)


def validate_test_agent_runtime_environment(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    _reject_unknown_fields(payload, {"agentRuntimeConfig"})
    _record(payload, "agentRuntimeConfig")
    return {"agentRuntimeConfig": dict(payload.get("agentRuntimeConfig", {}))}


def validate_agent_skills_sync(payload: Mapping[str, Any]) -> dict[str, list[str]]:
    _reject_unknown_fields(payload, {"desiredSkills"})
    skills = payload.get("desiredSkills", [])
    if not isinstance(skills, list) or any(
        not isinstance(skill, str) or not skill.strip() for skill in skills
    ):
        raise ValueError("'desiredSkills' must be an array of non-empty strings")
    deduped: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        normalized = skill.strip()
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return {"desiredSkills": deduped}


def validate_agent_skills_enable(payload: Mapping[str, Any]) -> dict[str, list[str]]:
    _reject_unknown_fields(payload, {"skills"})
    skills = payload.get("skills", [])
    if not isinstance(skills, list) or any(
        not isinstance(skill, str) or not skill.strip() for skill in skills
    ):
        raise ValueError("'skills' must be an array of non-empty strings")
    deduped: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        normalized = skill.strip()
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    if not deduped:
        raise ValueError("'skills' must contain at least one skill")
    return {"skills": deduped}


def validate_agent_private_skill(payload: Mapping[str, Any]) -> dict[str, Any]:
    _reject_unknown_fields(payload, {"name", "slug", "description", "markdown"})
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("'name' must be a non-empty string")
    for field in ("slug", "description", "markdown"):
        if (
            field in payload
            and payload[field] is not None
            and not isinstance(payload[field], str)
        ):
            raise ValueError(f"'{field}' must be a string or null")
    slug = payload.get("slug")
    return {
        "name": name.strip(),
        "slug": slug.strip() if isinstance(slug, str) else None,
        "description": payload.get("description"),
        "markdown": payload.get("markdown"),
    }


def validate_update_agent_instructions_path(
    payload: Mapping[str, Any],
) -> dict[str, str | None]:
    _reject_unknown_fields(payload, {"path", "agentRuntimeConfigKey"})
    path = payload.get("path")
    if path is not None and (not isinstance(path, str) or not path.strip()):
        raise ValueError("'path' must be a non-empty string or null")
    key = payload.get("agentRuntimeConfigKey")
    if key is not None and (not isinstance(key, str) or not key.strip()):
        raise ValueError("'agentRuntimeConfigKey' must be a non-empty string")
    return {
        "path": path.strip() if isinstance(path, str) else None,
        **(
            {"agentRuntimeConfigKey": key.strip()}
            if isinstance(key, str) and key.strip()
            else {}
        ),
    }


def validate_update_agent_instructions_bundle(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    _reject_unknown_fields(
        payload, {"mode", "rootPath", "entryFile", "clearLegacyPromptTemplate"}
    )
    result: dict[str, Any] = {}
    mode = payload.get("mode")
    if mode is not None:
        if mode not in {"managed", "external"}:
            raise ValueError("'mode' must be one of ['managed', 'external']")
        result["mode"] = mode
    root_path = payload.get("rootPath")
    if root_path is not None:
        if not isinstance(root_path, str) or not root_path.strip():
            raise ValueError("'rootPath' must be a non-empty string or null")
        result["rootPath"] = root_path.strip()
    elif "rootPath" in payload:
        result["rootPath"] = None
    entry_file = payload.get("entryFile")
    if entry_file is not None:
        if not isinstance(entry_file, str) or not entry_file.strip():
            raise ValueError("'entryFile' must be a non-empty string")
        result["entryFile"] = entry_file.strip()
    if "clearLegacyPromptTemplate" in payload:
        if not isinstance(payload["clearLegacyPromptTemplate"], bool):
            raise ValueError("'clearLegacyPromptTemplate' must be a boolean")
        result["clearLegacyPromptTemplate"] = payload["clearLegacyPromptTemplate"]
    return result


def validate_upsert_agent_instructions_file(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    _reject_unknown_fields(payload, {"path", "content", "clearLegacyPromptTemplate"})
    path = payload.get("path")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("'path' is required and must be a non-empty string")
    content = payload.get("content")
    if not isinstance(content, str):
        raise ValueError("'content' is required and must be a string")
    if "clearLegacyPromptTemplate" in payload and not isinstance(
        payload["clearLegacyPromptTemplate"], bool
    ):
        raise ValueError("'clearLegacyPromptTemplate' must be a boolean")
    return {
        "path": path.strip(),
        "content": content,
        **(
            {"clearLegacyPromptTemplate": payload["clearLegacyPromptTemplate"]}
            if "clearLegacyPromptTemplate" in payload
            else {}
        ),
    }
