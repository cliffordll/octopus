from __future__ import annotations

from typing import Any

from ..environment import (
    aggregate_status,
    cli_hello_probe_check,
    local_cli_environment_checks,
)
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
    checks.append(
        await cli_hello_probe_check(
            config,
            command=command,
            label="Codex CLI hello probe",
            default_args=["--version"],
        )
    )
    return RuntimeEnvironmentTestResult(
        agent_runtime_type="codex_local",
        status=aggregate_status(checks),
        checks=checks,
    )


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
