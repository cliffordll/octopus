from __future__ import annotations

from .claude_local import ClaudeLocalRuntimeAdapter
from .codex_local import CodexLocalRuntimeAdapter
from .common import UnavailableRuntimeAdapter
from .http import HttpRuntimeAdapter
from .opencode_local import OpenCodeLocalRuntimeAdapter
from .process import ProcessRuntimeAdapter
from .types import RuntimeAdapter

_PROCESS = ProcessRuntimeAdapter()
_CODEX_LOCAL = CodexLocalRuntimeAdapter()
_HTTP = HttpRuntimeAdapter()
_CLAUDE_LOCAL = ClaudeLocalRuntimeAdapter()
_OPENCODE_LOCAL = OpenCodeLocalRuntimeAdapter()
_ADAPTERS: dict[str, RuntimeAdapter] = {
    "process": _PROCESS,
    "codex_local": _CODEX_LOCAL,
    "http": _HTTP,
    "claude_local": _CLAUDE_LOCAL,
    "opencode_local": _OPENCODE_LOCAL,
}
_KNOWN_RUNTIME_TYPES = {
    "process",
    "http",
    "claude_local",
    "codex_local",
    "gemini_local",
    "opencode_local",
    "pi_local",
    "cursor",
    "openclaw_gateway",
    "hermes_local",
}


def get_runtime_adapter(runtime_type: str) -> RuntimeAdapter:
    adapter = _ADAPTERS.get(runtime_type)
    if adapter is not None:
        return adapter
    if runtime_type in _KNOWN_RUNTIME_TYPES:
        return UnavailableRuntimeAdapter(runtime_type)
    raise ValueError(f"Unknown runtime adapter: {runtime_type}")


async def list_runtime_models(runtime_type: str) -> list[dict[str, str]]:
    return await get_runtime_adapter(runtime_type).list_models()
