from __future__ import annotations

from typing import Any

from ..types import RuntimeEnvironmentTestResult
from .protocol import string


async def test_environment(config: dict[str, Any]) -> RuntimeEnvironmentTestResult:
    url = string(config.get("url"))
    if url is None:
        return RuntimeEnvironmentTestResult(
            agent_runtime_type="http",
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
        agent_runtime_type="http",
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
