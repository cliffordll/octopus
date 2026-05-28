from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol


@dataclass(frozen=True)
class RuntimeExecutionContext:
    run_id: str
    agent_id: str
    org_id: str
    agent_name: str
    config: dict[str, Any]
    on_log: Callable[[str, str], Awaitable[None]]
    cancel_event: asyncio.Event | None = None
    on_process_started: Callable[[int, datetime], Awaitable[None]] | None = None


@dataclass(frozen=True)
class RuntimeExecutionResult:
    exit_code: int | None
    signal: str | None = None
    timed_out: bool = False
    error_message: str | None = None
    usage_json: dict[str, Any] | None = None
    session_id_after: str | None = None
    result_json: dict[str, Any] | None = None


class RuntimeAdapter(Protocol):
    type: str

    async def execute(
        self, context: RuntimeExecutionContext
    ) -> RuntimeExecutionResult: ...
