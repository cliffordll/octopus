from __future__ import annotations

from typing import Any

from ..common import RuntimeCapabilityMixin, skill_snapshot_from_root
from ..types import (
    RuntimeEnvironmentTestResult,
    RuntimeExecutionContext,
    RuntimeExecutionResult,
)
from .environment import test_environment as test_claude_environment
from .runner import execute as execute_claude


class ClaudeLocalRuntimeAdapter(RuntimeCapabilityMixin):
    type = "claude_local"
    supports_local_agent_jwt = True
    agent_configuration_doc = (
        "Configure cwd, model, effort, maxTurnsPerRun, env and Claude CLI options."
    )
    quota_provider = "anthropic"
    _models = [{"id": "claude-sonnet-4.5", "label": "Claude Sonnet 4.5"}]

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        return await execute_claude(context)

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        return await test_claude_environment(config)

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
            location_label="~/.claude/skills",
        )
