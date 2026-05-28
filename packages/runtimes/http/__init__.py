from __future__ import annotations

import json
from typing import Any

import httpx

from ..common import RuntimeCapabilityMixin
from ..types import (
    RuntimeEnvironmentTestResult,
    RuntimeExecutionContext,
    RuntimeExecutionResult,
)


class HttpRuntimeAdapter(RuntimeCapabilityMixin):
    type = "http"

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        url = _string(context.config.get("url"))
        if url is None:
            raise ValueError("HTTP adapter missing url")
        method = (_string(context.config.get("method")) or "POST").upper()
        headers = _string_map(context.config.get("headers"))
        timeout = context.config.get("timeoutSec", 30)
        timeout_sec = float(timeout) if isinstance(timeout, (float, int)) else 30.0
        payload = dict(context.config.get("payloadTemplate", {}))
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
                response = await client.request(
                    method, url, headers=headers, json=payload
                )
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
            "body": _json_or_text(text),
        }
        return RuntimeExecutionResult(
            exit_code=0 if response.status_code < 400 else response.status_code,
            error_message=None
            if response.status_code < 400
            else f"HTTP request failed with status {response.status_code}",
            result_json=result_json,
        )

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        url = _string(config.get("url"))
        if url is None:
            return RuntimeEnvironmentTestResult(
                agent_runtime_type=self.type,
                status="failed",
                checks=[
                    {
                        "id": "url",
                        "label": "HTTP endpoint",
                        "status": "failed",
                        "message": "HTTP adapter requires agentRuntimeConfig.url.",
                        "hint": "Set url to the endpoint the adapter should invoke.",
                    }
                ],
            )
        return RuntimeEnvironmentTestResult(
            agent_runtime_type=self.type,
            status="ok",
            checks=[
                {
                    "id": "url",
                    "label": "HTTP endpoint",
                    "status": "ok",
                    "message": "HTTP endpoint is configured.",
                    "hint": None,
                }
            ],
        )


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


def _json_or_text(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value
