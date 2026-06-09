from __future__ import annotations

from typing import Any

from ..common import RuntimeCapabilityMixin
from ..types import (
    RuntimeEnvironmentTestResult,
    RuntimeExecutionContext,
    RuntimeExecutionResult,
)
from .environment import test_environment as test_openclaw_environment
from .runner import execute as execute_openclaw


class OpenClawGatewayRuntimeAdapter(RuntimeCapabilityMixin):
    type = "openclaw_gateway"
    agent_configuration_doc = (
        "Configure url, authToken, headers, payloadTemplate, sessionKeyStrategy, "
        "timeoutSec and waitTimeoutMs for the OpenClaw Gateway WebSocket endpoint."
    )

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        return await execute_openclaw(context)

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        return await test_openclaw_environment(config)

    async def list_models(
        self, config: dict[str, Any] | None = None
    ) -> list[dict[str, str]]:
        return []

    async def list_skills(
        self, config: dict[str, Any], desired_skills: list[str] | None = None
    ) -> dict[str, Any]:
        return _unsupported_skill_snapshot(desired_skills or [])

    async def sync_skills(
        self, config: dict[str, Any], desired_skills: list[str]
    ) -> dict[str, Any]:
        return _unsupported_skill_snapshot(desired_skills)

    async def get_metadata(self) -> dict[str, Any]:
        metadata = await super().get_metadata()
        metadata["capabilities"]["models"] = False
        metadata["capabilities"]["skills"] = False
        return metadata


def _unsupported_skill_snapshot(desired_skills: list[str]) -> dict[str, Any]:
    return {
        "agentRuntimeType": "openclaw_gateway",
        "supported": False,
        "mode": "unsupported",
        "desiredSkills": desired_skills,
        "entries": [],
        "warnings": ["OpenClaw Gateway does not implement Octopus skill sync."],
    }
