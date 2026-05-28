from __future__ import annotations

from typing import Any

from ..common import RuntimeCapabilityMixin
from ..types import (
    RuntimeEnvironmentTestResult,
    RuntimeExecutionContext,
    RuntimeExecutionResult,
)
from .environment import test_environment as test_http_environment
from .runner import execute as execute_http


class HttpRuntimeAdapter(RuntimeCapabilityMixin):
    type = "http"

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        return await execute_http(context)

    async def test_environment(
        self, config: dict[str, Any]
    ) -> RuntimeEnvironmentTestResult:
        return await test_http_environment(config)
