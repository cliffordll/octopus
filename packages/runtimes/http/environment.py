from __future__ import annotations

from typing import Any

from ..environment import aggregate_status, http_live_probe_check, http_url_check
from ..types import RuntimeEnvironmentTestResult


async def test_environment(config: dict[str, Any]) -> RuntimeEnvironmentTestResult:
    checks = [http_url_check(config.get("url"))]
    checks.append(await http_live_probe_check(config))
    return RuntimeEnvironmentTestResult(
        agent_runtime_type="http",
        status=aggregate_status(checks),
        checks=checks,
    )
