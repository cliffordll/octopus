from __future__ import annotations

from typing import Any

from ..environment import (
    aggregate_status,
    cli_hello_probe_check,
    local_cli_environment_checks,
)
from ..types import RuntimeEnvironmentTestResult


async def test_environment(config: dict[str, Any]) -> RuntimeEnvironmentTestResult:
    command = _string(config.get("command")) or "openclaw"
    checks = local_cli_environment_checks(
        config=config,
        command=command,
        command_label="OpenClaw CLI command",
        auth_env_keys=("OPENAI_API_KEY", "OPENROUTER_API_KEY"),
        auth_hint=(
            "Platform models are injected via the runtime-provider catalog "
            "(OPENAI_API_KEY/OPENAI_BASE_URL). Set them or bind a provider model."
        ),
    )
    checks.append(
        await cli_hello_probe_check(
            config,
            command=command,
            label="OpenClaw CLI hello probe",
            default_args=["--version"],
        )
    )
    return RuntimeEnvironmentTestResult(
        agent_runtime_type="openclaw_local",
        status=aggregate_status(checks),
        checks=checks,
    )


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
