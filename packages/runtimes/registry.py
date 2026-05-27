from __future__ import annotations

from .process import ProcessRuntimeAdapter
from .types import RuntimeAdapter

_PROCESS = ProcessRuntimeAdapter()


def get_runtime_adapter(runtime_type: str) -> RuntimeAdapter:
    if runtime_type == "process":
        return _PROCESS
    raise ValueError(f"Runtime adapter is not implemented: {runtime_type}")
