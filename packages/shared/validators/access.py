from __future__ import annotations

from typing import Any

from packages.shared.constants.access import PERMISSION_KEYS


def validate_email_auth(body: dict[str, Any], *, require_name: bool) -> dict[str, str]:
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    name = str(body.get("name") or "").strip()
    if "@" not in email:
        raise ValueError("A valid email is required")
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters")
    if require_name and not name:
        raise ValueError("Name is required")
    return {"email": email, "password": password, "name": name}


def validate_member_grants(body: dict[str, Any]) -> list[dict[str, Any]]:
    raw = body.get("grants")
    if not isinstance(raw, list):
        raise ValueError("grants must be an array")
    grants = []
    for item in raw:
        if (
            not isinstance(item, dict)
            or item.get("permissionKey") not in PERMISSION_KEYS
        ):
            raise ValueError("Unsupported permission grant")
        constraints = item.get("constraints")
        if constraints is not None and not isinstance(constraints, dict):
            raise ValueError("Permission constraints must be an object or null")
        if constraints:
            raise ValueError("Permission constraints are not supported yet")
        grants.append(
            {"permissionKey": item["permissionKey"], "constraints": constraints}
        )
    return grants


def validate_create_invite(body: dict[str, Any]) -> dict[str, Any]:
    allowed = body.get("allowedJoinTypes", "both")
    if allowed not in {"human", "agent", "both"}:
        raise ValueError("allowedJoinTypes must be human, agent, or both")
    defaults = body.get("defaultsPayload")
    if defaults is not None and not isinstance(defaults, dict):
        raise ValueError("defaultsPayload must be an object or null")
    return {"allowedJoinTypes": allowed, "defaultsPayload": defaults}


def validate_hierarchy_manager(body: dict[str, Any]) -> str | None:
    manager_id = body.get("managerId")
    if manager_id is not None and (not isinstance(manager_id, str) or not manager_id):
        raise ValueError("managerId must be a non-empty string or null")
    return manager_id
