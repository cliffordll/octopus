from __future__ import annotations

from typing import Any

from ..environment import aggregate_status, local_cli_environment_checks
from ..types import RuntimeEnvironmentTestResult


async def test_environment(config: dict[str, Any]) -> RuntimeEnvironmentTestResult:
    command = _string(config.get("command")) or "codex"
    checks = local_cli_environment_checks(
        config=config,
        command=command,
        command_label="Codex CLI command",
        auth_env_keys=("OPENAI_API_KEY", "OPENROUTER_API_KEY"),
        auth_hint="Set OPENAI_API_KEY/OPENROUTER_API_KEY or use local Codex login in the operator home.",
    )
    return RuntimeEnvironmentTestResult(
        agent_runtime_type="codex_local",
        status=aggregate_status(checks),
        checks=checks,
    )


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
