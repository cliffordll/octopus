from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

from ..environment import aggregate_status
from ..types import RuntimeEnvironmentTestResult
from .protocol import resolve_auth, validate_gateway_url

ProbeFunc = Callable[[str, dict[str, Any]], Awaitable[dict[str, str | None]]]


async def test_environment(
    config: dict[str, Any], *, probe: ProbeFunc | None = None
) -> RuntimeEnvironmentTestResult:
    url = config.get("url")
    url_check = _url_check(url)
    checks: list[dict[str, str | None]] = [url_check]
    if url_check["status"] != "ok":
        checks.append(_auth_check(config))
        checks.append(_probe_skipped("OpenClaw Gateway probe requires a valid URL."))
        return RuntimeEnvironmentTestResult(
            agent_runtime_type="openclaw_gateway",
            status=aggregate_status(checks),
            checks=checks,
        )

    plaintext_check = _plaintext_remote_ws_check(str(url))
    if plaintext_check is not None:
        checks.append(plaintext_check)
    checks.append(_auth_check(config))
    if config.get("liveProbe") is True:
        checks.append(await (probe or probe_gateway)(str(url), config))
    else:
        checks.append(
            _probe_skipped(
                "OpenClaw Gateway live probe was not requested.",
                hint="Set agentRuntimeConfig.liveProbe=true to verify Gateway reachability.",
            )
        )
    return RuntimeEnvironmentTestResult(
        agent_runtime_type="openclaw_gateway",
        status=aggregate_status(checks),
        checks=checks,
    )


async def probe_gateway(url: str, config: dict[str, Any]) -> dict[str, str | None]:
    timeout_sec = _timeout_seconds(config.get("probeTimeoutSec"), default=5.0)
    try:
        import websockets
    except ImportError:
        return {
            "id": "probe",
            "label": "OpenClaw Gateway probe",
            "status": "failed",
            "code": "openclaw_gateway_probe_error",
            "message": "Python package 'websockets' is required for OpenClaw Gateway probe.",
            "hint": "Install the websockets dependency.",
        }

    try:
        async with asyncio.timeout(timeout_sec):
            async with websockets.connect(  # type: ignore[attr-defined]
                url,
                additional_headers=resolve_auth(config).headers,
            ) as websocket:
                raw = await websocket.recv()
                frame = _decode_frame(raw)
                if frame.get("type") != "connect.challenge":
                    return {
                        "id": "probe",
                        "label": "OpenClaw Gateway probe",
                        "status": "failed",
                        "code": "openclaw_gateway_probe_failed",
                        "message": "OpenClaw Gateway did not send connect.challenge.",
                        "hint": "Verify the endpoint is an OpenClaw Gateway WebSocket.",
                    }
                return {
                    "id": "probe",
                    "label": "OpenClaw Gateway probe",
                    "status": "warning",
                    "code": "openclaw_gateway_probe_challenge_only",
                    "message": "OpenClaw Gateway challenge was received.",
                    "hint": "Execution will complete the full connect handshake.",
                }
    except TimeoutError:
        return {
            "id": "probe",
            "label": "OpenClaw Gateway probe",
            "status": "failed",
            "code": "openclaw_gateway_probe_failed",
            "message": f"OpenClaw Gateway probe timed out after {timeout_sec:g}s.",
            "hint": "Check Gateway reachability or increase probeTimeoutSec.",
        }
    except Exception as exc:
        return {
            "id": "probe",
            "label": "OpenClaw Gateway probe",
            "status": "failed",
            "code": "openclaw_gateway_probe_error",
            "message": f"OpenClaw Gateway probe failed: {exc}",
            "hint": "Check Gateway URL, TLS, DNS, proxy, and auth configuration.",
        }


def _url_check(value: Any) -> dict[str, str | None]:
    ok, code, _ = validate_gateway_url(value)
    if ok:
        return {
            "id": "url",
            "label": "OpenClaw Gateway URL",
            "status": "ok",
            "code": code,
            "message": "OpenClaw Gateway URL is valid.",
            "hint": None,
        }
    messages = {
        "openclaw_gateway_url_missing": "OpenClaw Gateway requires agentRuntimeConfig.url.",
        "openclaw_gateway_url_invalid": "OpenClaw Gateway URL must be absolute.",
        "openclaw_gateway_url_protocol_invalid": "OpenClaw Gateway URL must use ws:// or wss://.",
    }
    return {
        "id": "url",
        "label": "OpenClaw Gateway URL",
        "status": "failed",
        "code": code,
        "message": messages[code],
        "hint": "Set agentRuntimeConfig.url to the OpenClaw Gateway WebSocket endpoint.",
    }


def _auth_check(config: dict[str, Any]) -> dict[str, str | None]:
    auth = resolve_auth(config)
    if auth.present:
        return {
            "id": "auth",
            "label": "OpenClaw Gateway auth",
            "status": "ok",
            "code": "openclaw_gateway_auth_present",
            "message": "OpenClaw Gateway auth configuration is present.",
            "hint": None,
        }
    return {
        "id": "auth",
        "label": "OpenClaw Gateway auth",
        "status": "warning",
        "code": "openclaw_gateway_auth_missing",
        "message": "OpenClaw Gateway auth configuration was not found.",
        "hint": "Set authToken, token, password, or an OpenClaw auth header when the Gateway requires credentials.",
    }


def _plaintext_remote_ws_check(url: str) -> dict[str, str | None] | None:
    parsed = urlparse(url)
    if parsed.scheme != "ws":
        return None
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "127.0.0.1", "::1"}:
        return None
    return {
        "id": "plaintext",
        "label": "OpenClaw Gateway transport",
        "status": "warning",
        "code": "openclaw_gateway_plaintext_remote_ws",
        "message": "Remote OpenClaw Gateway uses plaintext ws://.",
        "hint": "Use wss:// for non-local Gateway endpoints.",
    }


def _probe_skipped(message: str, *, hint: str | None = None) -> dict[str, str | None]:
    return {
        "id": "probe",
        "label": "OpenClaw Gateway probe",
        "status": "skipped",
        "code": None,
        "message": message,
        "hint": hint,
    }


def _timeout_seconds(value: Any, *, default: float) -> float:
    return float(value) if isinstance(value, int | float) and value > 0 else default


def _decode_frame(raw: Any) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode(errors="replace")
    if not isinstance(raw, str):
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}
