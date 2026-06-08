from __future__ import annotations

from typing import Any

from ..environment import (
    aggregate_status,
    cli_hello_probe_check,
    local_cli_environment_checks,
)
from ..types import RuntimeEnvironmentTestResult
from .models import list_models
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
    checks.append(
        await cli_hello_probe_check(
            config,
            command=command,
            label="OpenCode CLI hello probe",
            default_args=["--version"],
        )
    )
    checks.append(await _available_model_check(config))
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


async def _available_model_check(config: dict[str, Any]) -> dict[str, str | None]:
    if config.get("liveProbe") is not True:
        return {
            "id": "availableModel",
            "label": "OpenCode available model",
            "status": "skipped",
            "message": "OpenCode model availability probe was not requested.",
            "hint": "Set agentRuntimeConfig.liveProbe=true to run `opencode models`.",
        }
    configured = string(config.get("model"))
    if configured is None:
        return {
            "id": "availableModel",
            "label": "OpenCode available model",
            "status": "failed",
            "message": "Cannot verify model availability without configured model.",
            "hint": "Set agentRuntimeConfig.model.",
        }
    models = await list_models(config)
    ids = {model["id"] for model in models if isinstance(model.get("id"), str)}
    if not ids:
        return {
            "id": "availableModel",
            "label": "OpenCode available model",
            "status": "warning",
            "message": "OpenCode models probe returned no models.",
            "hint": "Verify OpenCode auth/config and run `opencode models` manually.",
        }
    if configured not in ids:
        return {
            "id": "availableModel",
            "label": "OpenCode available model",
            "status": "failed",
            "message": f"Configured model is not available to OpenCode: {configured}",
            "hint": "Choose a model returned by `opencode models`.",
        }
    return {
        "id": "availableModel",
        "label": "OpenCode available model",
        "status": "ok",
        "message": f"Configured model is available: {configured}",
        "hint": None,
    }
