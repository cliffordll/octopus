from __future__ import annotations

from ..common import RuntimeCapabilityMixin
from ..types import RuntimeExecutionContext, RuntimeExecutionResult
from .runner import execute as execute_process


class ProcessRuntimeAdapter(RuntimeCapabilityMixin):
    type = "process"

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        return await execute_process(context)
