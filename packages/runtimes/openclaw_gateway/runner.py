from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any, Protocol

from ..instructions import runtime_prompt_from_config
from ..types import RuntimeExecutionContext, RuntimeExecutionResult
from .protocol import (
    build_agent_payload,
    build_connect_payload,
    resolve_auth,
    validate_gateway_url,
)


class GatewayWebSocket(Protocol):
    async def send(self, payload: str) -> None: ...

    async def recv(self) -> str | bytes: ...


Connector = Callable[
    [str, dict[str, str]], AbstractAsyncContextManager[GatewayWebSocket]
]


async def execute(
    context: RuntimeExecutionContext, *, connector: Connector | None = None
) -> RuntimeExecutionResult:
    url = context.config.get("url")
    ok, code, _ = validate_gateway_url(url)
    if not ok:
        return RuntimeExecutionResult(
            exit_code=None,
            error_message=code,
            result_json={"error": code},
        )
    timeout_sec = _timeout_seconds(context.config.get("timeoutSec"), default=120.0)
    wait_timeout_sec = (
        _timeout_seconds(context.config.get("waitTimeoutMs"), default=120000.0) / 1000
    )
    message_ids = _MessageIds()
    connector = connector or _connect
    await context.on_log("openclaw", "[openclaw-gateway] connecting to Gateway\n")
    try:
        async with asyncio.timeout(timeout_sec):
            async with connector(str(url), resolve_auth(context.config).headers) as ws:
                challenge = _decode_frame(await ws.recv())
                if challenge.get("type") != "connect.challenge":
                    return _failure("openclaw_gateway_probe_failed")
                connect_id = message_ids.next()
                await _send(
                    ws, build_connect_payload(context.config, request_id=connect_id)
                )
                connect_response = await _wait_for_response(
                    ws, connect_id, context=context, timeout_sec=wait_timeout_sec
                )
                if _is_error(connect_response):
                    return _gateway_failure(connect_response)
                agent_id = message_ids.next()
                agent_frame = build_agent_payload(
                    context.config,
                    request_id=agent_id,
                    run_id=context.run_id,
                    agent_id=context.agent_id,
                    org_id=context.org_id,
                    agent_name=context.agent_name,
                    task_message=runtime_prompt_from_config(context.config),
                    issue_id=_issue_id(context.config),
                )
                await _send(ws, agent_frame)
                wait_id = message_ids.next()
                await _send(
                    ws,
                    {
                        "type": "req",
                        "id": wait_id,
                        "method": "agent.wait",
                        "payload": {
                            "idempotencyKey": context.run_id,
                            "sessionKey": _session_key_from_sent_payload(agent_frame),
                        },
                    },
                )
                wait_response = await _wait_for_response(
                    ws, wait_id, context=context, timeout_sec=wait_timeout_sec
                )
                if _is_error(wait_response):
                    return _gateway_failure(wait_response)
                return _success(wait_response)
    except TimeoutError:
        return RuntimeExecutionResult(
            exit_code=None,
            timed_out=True,
            error_message="openclaw_gateway_wait_timeout",
            result_json={"error": "openclaw_gateway_wait_timeout"},
        )
    except Exception as exc:
        return RuntimeExecutionResult(
            exit_code=None,
            error_message=str(exc),
            result_json={"error": str(exc)},
        )


def _connect(
    url: str, headers: dict[str, str]
) -> AbstractAsyncContextManager[GatewayWebSocket]:
    import websockets

    return websockets.connect(url, additional_headers=headers)  # type: ignore[return-value]


async def _send(ws: GatewayWebSocket, frame: dict[str, Any]) -> None:
    await ws.send(json.dumps(frame, separators=(",", ":")))


async def _wait_for_response(
    ws: GatewayWebSocket,
    request_id: str,
    *,
    context: RuntimeExecutionContext,
    timeout_sec: float,
) -> dict[str, Any]:
    async with asyncio.timeout(timeout_sec):
        while True:
            frame = _decode_frame(await ws.recv())
            if _is_agent_event(frame):
                await _log_agent_event(context, frame)
                continue
            if frame.get("id") == request_id:
                return frame


async def _log_agent_event(
    context: RuntimeExecutionContext, frame: dict[str, Any]
) -> None:
    payload = frame.get("payload")
    data = payload if isinstance(payload, dict) else {}
    stream = data.get("stream") if isinstance(data.get("stream"), str) else "event"
    await context.on_log(
        "openclaw",
        (
            f"[openclaw-gateway:event] run={context.run_id} stream={stream} "
            f"data={json.dumps(data, separators=(',', ':'))}\n"
        ),
    )


def _success(frame: dict[str, Any]) -> RuntimeExecutionResult:
    payload = _object(frame.get("payload"))
    meta = _object(payload.get("meta"))
    summary = _string(payload.get("summary")) or _string(payload.get("message")) or ""
    result_json: dict[str, Any] = {
        "provider": "openclaw",
        "summary": summary,
        "meta": meta,
    }
    usage = _object_or_none(payload.get("usage"))
    runtime_services = _list_of_objects(meta.get("runtimeServices"))
    return RuntimeExecutionResult(
        exit_code=0,
        usage_json=usage,
        result_json=result_json,
        runtime_services=runtime_services,
    )


def _failure(code: str) -> RuntimeExecutionResult:
    return RuntimeExecutionResult(
        exit_code=None,
        error_message=code,
        result_json={"error": code},
    )


def _gateway_failure(frame: dict[str, Any]) -> RuntimeExecutionResult:
    payload = _object(frame.get("payload"))
    code = (
        _string(payload.get("code"))
        or _string(frame.get("code"))
        or "openclaw_gateway_error"
    )
    message = _string(payload.get("message")) or code
    return RuntimeExecutionResult(
        exit_code=None,
        error_message=message,
        result_json={"error": code, "message": message},
    )


def _decode_frame(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode(errors="replace")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _is_agent_event(frame: dict[str, Any]) -> bool:
    frame_type = frame.get("type")
    method = frame.get("method")
    return (frame_type == "event" and method == "agent") or frame_type == "event agent"


def _is_error(frame: dict[str, Any]) -> bool:
    return (
        frame.get("type") == "error" or _object(frame.get("payload")).get("ok") is False
    )


def _timeout_seconds(value: Any, *, default: float) -> float:
    return float(value) if isinstance(value, int | float) and value > 0 else default


def _issue_id(config: dict[str, Any]) -> str | None:
    octopus = config.get("_octopus")
    if not isinstance(octopus, dict):
        return None
    context = octopus.get("context")
    if not isinstance(context, dict):
        return None
    issue = context.get("issue")
    if not isinstance(issue, dict):
        return None
    return _string(issue.get("id"))


def _session_key_from_sent_payload(frame: dict[str, Any]) -> str:
    payload = _object(frame.get("payload"))
    return _string(payload.get("sessionKey")) or ""


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _object(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _object_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _list_of_objects(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    return [dict(item) for item in value if isinstance(item, dict)]


class _MessageIds:
    def __init__(self) -> None:
        self._next = 1

    def next(self) -> str:
        value = f"openclaw-{self._next}"
        self._next += 1
        return value
