from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace

from .artifacts import RuntimeArtifactsCollector
from .common import RuntimeCapabilityMixin
from .types import RuntimeExecutionContext, RuntimeExecutionResult


class RuntimeAdapterBase(RuntimeCapabilityMixin, ABC):
    """Template for executing a runtime and normalizing shared result evidence."""

    def __init__(
        self, artifacts_collector: RuntimeArtifactsCollector | None = None
    ) -> None:
        self._artifacts_collector = artifacts_collector or RuntimeArtifactsCollector()

    async def execute(self, context: RuntimeExecutionContext) -> RuntimeExecutionResult:
        result = await self._execute_runtime(context)
        work_products = self._artifacts_collector.collect(context, result)
        if work_products == list(result.work_products or []):
            return result
        return replace(result, work_products=work_products)

    @abstractmethod
    async def _execute_runtime(
        self, context: RuntimeExecutionContext
    ) -> RuntimeExecutionResult:
        raise NotImplementedError


class LocalRuntimeAdapter(RuntimeAdapterBase, ABC):
    """Base for process-backed runtimes that execute inside a local workspace."""

    execution_location = "local"


class RemoteRuntimeAdapter(RuntimeAdapterBase, ABC):
    """Extension point for HTTP, streaming HTTP, or gateway-backed runtimes."""

    execution_location = "remote"
