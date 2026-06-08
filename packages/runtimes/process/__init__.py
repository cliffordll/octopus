from __future__ import annotations

from ..common import RuntimeCapabilityMixin
from ..environment import aggregate_status, cli_hello_probe_check
from ..types import (
    RuntimeEnvironmentTestResult,
    RuntimeExecutionContext,
    RuntimeExecutionResult,
)
from .runner import execute as execute_process


class ProcessRuntimeAdapter(RuntimeCapabilityMixin):
    type = "process"

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        return await execute_process(context)

    async def test_environment(self, config: dict) -> RuntimeEnvironmentTestResult:
        command = config.get("command")
        checks: list[dict[str, str | None]]
        if not isinstance(command, str) or not command.strip():
            checks = [
                {
                    "id": "command",
                    "label": "Process command",
                    "status": "failed",
                    "message": "Process adapter requires agentRuntimeConfig.command.",
                    "hint": "Set command to an executable.",
                }
            ]
        else:
            checks = [
                {
                    "id": "command",
                    "label": "Process command",
                    "status": "ok",
                    "message": f"Process command is configured: {command.strip()}",
                    "hint": None,
                }
            ]
            checks.append(
                await cli_hello_probe_check(
                    config,
                    command=command.strip(),
                    label="Process CLI hello probe",
                    default_args=[],
                )
            )
        return RuntimeEnvironmentTestResult(
            agent_runtime_type=self.type,
            status=aggregate_status(checks),
            checks=checks,
        )
