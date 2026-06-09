from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


DEFAULT_CLIENT_ID = "octopus-gateway-client"
DEFAULT_CLIENT_MODE = "agent"
DEFAULT_CLIENT_VERSION = "octopus"
DEFAULT_ROLE = "operator"
DEFAULT_SCOPES = ["operator.admin"]
DEFAULT_PROTOCOL_VERSION = 3


@dataclass(frozen=True)
class ResolvedAuth:
    present: bool
    headers: dict[str, str]
    token: str | None = None
    password: str | None = None


def validate_gateway_url(value: Any) -> tuple[bool, str, str | None]:
    url = _string(value)
    if url is None:
        return False, "openclaw_gateway_url_missing", None
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return False, "openclaw_gateway_url_invalid", None
    if parsed.scheme not in {"ws", "wss"}:
        return False, "openclaw_gateway_url_protocol_invalid", None
    return True, "openclaw_gateway_url_valid", None


def resolve_auth(config: dict[str, Any]) -> ResolvedAuth:
    headers = _string_map(config.get("headers"))
    token = (
        _string(config.get("authToken"))
        or _string(config.get("token"))
        or _case_insensitive_header(headers, "x-openclaw-token")
        or _case_insensitive_header(headers, "x-openclaw-auth")
    )
    authorization = _case_insensitive_header(headers, "authorization")
    password = _string(config.get("password"))
    if token is None and authorization is not None:
        token = authorization.removeprefix("Bearer ").strip() or authorization
    if token is not None and authorization is None:
        headers["Authorization"] = f"Bearer {token}"
    return ResolvedAuth(
        present=token is not None or password is not None,
        headers=headers,
        token=token,
        password=password,
    )


def build_connect_payload(config: dict[str, Any], *, request_id: str) -> dict[str, Any]:
    auth = resolve_auth(config)
    payload: dict[str, Any] = {
        "protocol": DEFAULT_PROTOCOL_VERSION,
        "client": {
            "id": _string(config.get("clientId")) or DEFAULT_CLIENT_ID,
            "mode": _string(config.get("clientMode")) or DEFAULT_CLIENT_MODE,
            "version": _string(config.get("clientVersion")) or DEFAULT_CLIENT_VERSION,
        },
        "role": _string(config.get("role")) or DEFAULT_ROLE,
        "scopes": _string_list(config.get("scopes")) or list(DEFAULT_SCOPES),
    }
    auth_payload: dict[str, str] = {}
    if auth.token is not None:
        auth_payload["token"] = auth.token
    if auth.password is not None:
        auth_payload["password"] = auth.password
    if auth_payload:
        payload["auth"] = auth_payload
    if config.get("disableDeviceAuth") is True:
        payload["disableDeviceAuth"] = True
    return {"type": "req", "id": request_id, "method": "connect", "payload": payload}


def resolve_session_key(
    config: dict[str, Any], *, run_id: str, issue_id: str | None
) -> str:
    strategy = _string(config.get("sessionKeyStrategy")) or "issue"
    if strategy == "fixed":
        fixed = _string(config.get("sessionKey"))
        return fixed or f"octopus:run:{run_id}"
    if strategy == "run":
        return f"octopus:run:{run_id}"
    if issue_id:
        return f"octopus:issue:{issue_id}"
    return f"octopus:run:{run_id}"


def build_agent_payload(
    config: dict[str, Any],
    *,
    request_id: str,
    run_id: str,
    agent_id: str,
    org_id: str,
    agent_name: str,
    task_message: str,
    issue_id: str | None,
) -> dict[str, Any]:
    payload = _object(config.get("payloadTemplate"))
    payload["message"] = _string(payload.get("message")) or task_message
    payload["idempotencyKey"] = run_id
    payload["sessionKey"] = resolve_session_key(
        config, run_id=run_id, issue_id=issue_id
    )
    payload["rudder"] = {
        "runId": run_id,
        "agentId": agent_id,
        "orgId": org_id,
        "agentName": agent_name,
        "issueId": issue_id,
    }
    workspace_runtime = _object_or_none(config.get("workspaceRuntime"))
    if workspace_runtime is not None:
        payload["workspaceRuntime"] = workspace_runtime
    return {"type": "req", "id": request_id, "method": "agent", "payload": payload}


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def _case_insensitive_header(headers: dict[str, str], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return _string(value)
    return None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _object_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None
