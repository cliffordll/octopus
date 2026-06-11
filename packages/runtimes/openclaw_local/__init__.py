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


class OpenClawLocalRuntimeAdapter(RuntimeCapabilityMixin):
    """Run OpenClaw as an embedded local coding agent (`openclaw agent --local`).

    Unlike `openclaw_gateway` (which connects to a running OpenClaw Gateway over
    WebSocket), this adapter spawns the OpenClaw CLI per turn — like codex_local /
    opencode_local. Platform models are injected the same way the other local CLI
    runtimes do (provider baseUrl/apiKey via the runtime-provider catalog); the
    runner registers them into OpenClaw's per-agent config so `--model` resolves.
    """

    type = "openclaw_local"
    supports_local_agent_jwt = True
    agent_configuration_doc = (
        "Configure model, promptTemplate, env, timeoutSec and OpenClaw CLI options. "
        "The model is registered into a managed per-agent OpenClaw home and run via "
        "`openclaw agent --local`."
    )

    async def list_models(
        self, config: dict[str, Any] | None = None
    ) -> list[dict[str, str]]:
        # Models come from the runtime-provider catalog (same as codex/opencode),
        # not from a static list here.
        return []

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        return await test_openclaw_environment(config)

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
        metadata["capabilities"]["skills"] = False
        return metadata

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        return await execute_openclaw(context)


def _unsupported_skill_snapshot(desired_skills: list[str]) -> dict[str, Any]:
    return {
        "agentRuntimeType": "openclaw_local",
        "supported": False,
        "mode": "unsupported",
        "desiredSkills": desired_skills,
        "entries": [],
        "warnings": [
            "OpenClaw manages its own skills; Octopus runtime skill sync is not wired."
        ],
    }
