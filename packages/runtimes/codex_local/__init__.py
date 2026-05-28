from __future__ import annotations

from typing import Any

from ..common import RuntimeCapabilityMixin
from ..types import (
    RuntimeEnvironmentTestResult,
    RuntimeExecutionContext,
    RuntimeExecutionResult,
)
from .environment import test_environment as test_codex_environment
from .runner import execute as execute_codex
from .skills import skill_snapshot


class CodexLocalRuntimeAdapter(RuntimeCapabilityMixin):
    type = "codex_local"
    supports_local_agent_jwt = True
    agent_configuration_doc = (
        "Configure cwd, model, promptTemplate, env, timeoutSec and Codex CLI options."
    )
    quota_provider = "openai"

    async def list_models(self) -> list[dict[str, str]]:
        return [
            {"id": "gpt-5-codex", "label": "GPT-5 Codex"},
            {"id": "gpt-5", "label": "GPT-5"},
        ]

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        return await test_codex_environment(config)

    def _skill_snapshot(
        self,
        config: dict[str, Any],
        desired_skills: list[str],
        *,
        materialize: bool,
    ) -> dict[str, Any]:
        return skill_snapshot(
            runtime_type=self.type,
            config=config,
            desired_skills=desired_skills,
            materialize=materialize,
        )

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        return await execute_codex(context)
