from __future__ import annotations

from typing import Any

from ..common import RuntimeCapabilityMixin, skill_snapshot_from_root
from ..types import (
    RuntimeEnvironmentTestResult,
    RuntimeExecutionContext,
    RuntimeExecutionResult,
)
from .environment import test_environment as test_opencode_environment
from .runner import execute as execute_opencode


class OpenCodeLocalRuntimeAdapter(RuntimeCapabilityMixin):
    type = "opencode_local"
    supports_local_agent_jwt = True
    agent_configuration_doc = (
        "Configure cwd, model, variant, env and OpenCode CLI options."
    )
    _models = [{"id": "opencode/default", "label": "OpenCode Default"}]

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        return await execute_opencode(context)

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        return await test_opencode_environment(config)

    async def list_models(self) -> list[dict[str, str]]:
        return self._models

    def _skill_snapshot(
        self, config: dict[str, Any], desired_skills: list[str]
    ) -> dict[str, Any]:
        return skill_snapshot_from_root(
            runtime_type=self.type,
            config=config,
            desired_skills=desired_skills,
            mode="ephemeral",
            location_label="Claude-compatible skills home",
        )
