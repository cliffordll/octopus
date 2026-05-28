from __future__ import annotations

from typing import Any

import httpx

from ..types import RuntimeExecutionContext, RuntimeExecutionResult
from .protocol import json_or_text, payload_template, string, string_map


async def execute(context: RuntimeExecutionContext) -> RuntimeExecutionResult:
    url = string(context.config.get("url"))
    if url is None:
        raise ValueError("HTTP adapter missing url")
    method = (string(context.config.get("method")) or "POST").upper()
    headers = string_map(context.config.get("headers"))
    timeout = context.config.get("timeoutSec", 30)
    timeout_sec = float(timeout) if isinstance(timeout, (float, int)) else 30.0
    payload = payload_template(context.config.get("payloadTemplate"))
    payload.update(
        {
            "runId": context.run_id,
            "agentId": context.agent_id,
            "orgId": context.org_id,
            "agentName": context.agent_name,
        }
    )
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            response = await client.request(method, url, headers=headers, json=payload)
    except httpx.TimeoutException:
        return RuntimeExecutionResult(
            exit_code=None,
            timed_out=True,
            error_message=f"Timed out after {timeout_sec:g}s",
        )
    except httpx.HTTPError as exc:
        return RuntimeExecutionResult(
            exit_code=None,
            error_message=str(exc),
            result_json={"error": str(exc)},
        )

    text = response.text
    await context.on_log("http", text)
    result_json: dict[str, Any] = {
        "statusCode": response.status_code,
        "headers": dict(response.headers),
        "body": json_or_text(text),
    }
    return RuntimeExecutionResult(
        exit_code=0 if response.status_code < 400 else response.status_code,
        error_message=None
        if response.status_code < 400
        else f"HTTP request failed with status {response.status_code}",
        result_json=result_json,
    )
