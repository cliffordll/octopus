from __future__ import annotations

from dataclasses import replace
from typing import Any

from .common import RuntimeCapabilityMixin
from .codex_local import _string
from .process import ProcessRuntimeAdapter
from .types import RuntimeEnvironmentTestResult, RuntimeExecutionContext


class LocalCliRuntimeAdapter(RuntimeCapabilityMixin):
    def __init__(
        self,
        runtime_type: str,
        *,
        default_command: str,
        default_args: list[str] | None = None,
        models: list[dict[str, str]] | None = None,
    ) -> None:
        self.type = runtime_type
        self._default_command = default_command
        self._default_args = default_args or []
        self._models = models or []
        self._process = ProcessRuntimeAdapter()

    async def execute(self, context: RuntimeExecutionContext):
        config = dict(context.config)
        config.setdefault("command", self._default_command)
        config.setdefault("args", self._default_args)
        return await self._process.execute(replace(context, config=config))

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        command = _string(config.get("command")) or self._default_command
        return RuntimeEnvironmentTestResult(
            agent_runtime_type=self.type,
            status="ok",
            checks=[
                {
                    "id": "command",
                    "label": "CLI command",
                    "status": "ok",
                    "message": f"Runtime command is configured: {command}",
                    "hint": None,
                }
            ],
        )

    async def list_models(self) -> list[dict[str, str]]:
        return self._models
