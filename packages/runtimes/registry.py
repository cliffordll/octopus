from __future__ import annotations

from .codex_local import CodexLocalRuntimeAdapter
from .process import ProcessRuntimeAdapter
from .types import RuntimeAdapter

_PROCESS = ProcessRuntimeAdapter()
_CODEX_LOCAL = CodexLocalRuntimeAdapter()


def get_runtime_adapter(runtime_type: str) -> RuntimeAdapter:
    if runtime_type == "process":
        return _PROCESS
    if runtime_type == "codex_local":
        return _CODEX_LOCAL
    raise ValueError(f"Runtime adapter is not implemented: {runtime_type}")
