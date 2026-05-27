from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class RuntimeExecutionContext:
    run_id: str
    agent_id: str
    org_id: str
    agent_name: str
    config: dict[str, Any]
    on_log: Callable[[str, str], Awaitable[None]]


@dataclass(frozen=True)
class RuntimeExecutionResult:
    exit_code: int | None
    signal: str | None = None
    timed_out: bool = False
    error_message: str | None = None
    result_json: dict[str, Any] | None = None


class RuntimeAdapter(Protocol):
    type: str

    async def execute(
        self, context: RuntimeExecutionContext
    ) -> RuntimeExecutionResult: ...
