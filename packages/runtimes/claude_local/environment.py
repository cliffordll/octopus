from __future__ import annotations

from typing import Any

from ..environment import (
    aggregate_status,
    cli_hello_probe_check,
    local_cli_environment_checks,
)
from ..types import RuntimeEnvironmentTestResult
from .protocol import string


async def test_environment(config: dict[str, Any]) -> RuntimeEnvironmentTestResult:
    command = string(config.get("command")) or "claude"
    checks = local_cli_environment_checks(
        config=config,
        command=command,
        command_label="Claude CLI command",
        auth_env_keys=("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"),
        auth_hint="Set ANTHROPIC_API_KEY/CLAUDE_API_KEY or run Claude CLI login in the operator home.",
    )
    checks.append(
        await cli_hello_probe_check(
            config,
            command=command,
            label="Claude CLI hello probe",
            default_args=["--version"],
        )
    )
    return RuntimeEnvironmentTestResult(
        agent_runtime_type="claude_local",
        status=aggregate_status(checks),
        checks=checks,
    )
