from __future__ import annotations

from typing import Any

from ..types import RuntimeEnvironmentTestResult
from .protocol import string


async def test_environment(config: dict[str, Any]) -> RuntimeEnvironmentTestResult:
    command = string(config.get("command")) or "opencode"
    return RuntimeEnvironmentTestResult(
        agent_runtime_type="opencode_local",
        status="ok",
        checks=[
            {
                "id": "command",
                "label": "OpenCode CLI command",
                "status": "ok",
                "message": f"Runtime command is configured: {command}",
                "hint": None,
            }
        ],
    )
