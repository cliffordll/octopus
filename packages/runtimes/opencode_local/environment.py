from __future__ import annotations

from typing import Any

from ..environment import aggregate_status, local_cli_environment_checks
from ..types import RuntimeEnvironmentTestResult
from .protocol import string


async def test_environment(config: dict[str, Any]) -> RuntimeEnvironmentTestResult:
    command = string(config.get("command")) or "opencode"
    checks = local_cli_environment_checks(
        config=config,
        command=command,
        command_label="OpenCode CLI command",
        auth_env_keys=("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENCODE_API_KEY"),
        auth_hint="Set provider API key env or configure local OpenCode authentication.",
    )
    checks.append(_model_check(config.get("model")))
    return RuntimeEnvironmentTestResult(
        agent_runtime_type="opencode_local",
        status=aggregate_status(checks),
        checks=checks,
    )


def _model_check(value: Any) -> dict[str, str | None]:
    model = string(value)
    if model is None:
        return {
            "id": "model",
            "label": "OpenCode model",
            "status": "failed",
            "message": "OpenCode requires agentRuntimeConfig.model in provider/model format.",
            "hint": "Run `opencode models` and choose a provider/model id.",
        }
    provider, separator, model_name = model.partition("/")
    if not separator or not provider.strip() or not model_name.strip():
        return {
            "id": "model",
            "label": "OpenCode model",
            "status": "failed",
            "message": "OpenCode model must use provider/model format.",
            "hint": "Use a model id such as openai/gpt-5.",
        }
    return {
        "id": "model",
        "label": "OpenCode model",
        "status": "ok",
        "message": f"Configured model: {model}",
        "hint": None,
    }
