from __future__ import annotations

from .claude_local import ClaudeLocalRuntimeAdapter
from .codex_local import CodexLocalRuntimeAdapter
from .common import UnavailableRuntimeAdapter
from .http import HttpRuntimeAdapter
from .opencode_local import OpenCodeLocalRuntimeAdapter
from .openclaw_gateway import OpenClawGatewayRuntimeAdapter
from .openclaw_local import OpenClawLocalRuntimeAdapter
from .process import ProcessRuntimeAdapter
from .types import RuntimeAdapter

_PROCESS = ProcessRuntimeAdapter()
_CODEX_LOCAL = CodexLocalRuntimeAdapter()
_HTTP = HttpRuntimeAdapter()
_CLAUDE_LOCAL = ClaudeLocalRuntimeAdapter()
_OPENCODE_LOCAL = OpenCodeLocalRuntimeAdapter()
_OPENCLAW_GATEWAY = OpenClawGatewayRuntimeAdapter()
_OPENCLAW_LOCAL = OpenClawLocalRuntimeAdapter()
_ADAPTERS: dict[str, RuntimeAdapter] = {
    "process": _PROCESS,
    "codex_local": _CODEX_LOCAL,
    "http": _HTTP,
    "claude_local": _CLAUDE_LOCAL,
    "opencode_local": _OPENCODE_LOCAL,
    "openclaw_gateway": _OPENCLAW_GATEWAY,
    "openclaw_local": _OPENCLAW_LOCAL,
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
    "openclaw_local",
    "hermes_local",
}


def get_runtime_adapter(runtime_type: str) -> RuntimeAdapter:
    adapter = _ADAPTERS.get(runtime_type)
    if adapter is not None:
        return adapter
    if runtime_type in _KNOWN_RUNTIME_TYPES:
        return UnavailableRuntimeAdapter(runtime_type)
    raise ValueError(f"Unknown runtime adapter: {runtime_type}")


def list_runtime_adapter_types() -> list[str]:
    return list(_ADAPTERS)


async def list_runtime_adapters() -> list[dict]:
    return [
        {
            "type": runtime_type,
            "displayName": runtime_type,
            "metadata": await adapter.get_metadata(),
        }
        for runtime_type, adapter in _ADAPTERS.items()
    ]


def list_quota_runtime_types() -> list[str]:
    return [
        runtime_type
        for runtime_type, adapter in _ADAPTERS.items()
        if getattr(adapter, "quota_provider", None) is not None
    ]


async def list_runtime_models(
    runtime_type: str, config: dict | None = None
) -> list[dict[str, str]]:
    return await get_runtime_adapter(runtime_type).list_models(config)


async def get_runtime_metadata(runtime_type: str) -> dict:
    return await get_runtime_adapter(runtime_type).get_metadata()


async def get_runtime_quota_windows(runtime_type: str) -> dict:
    return await get_runtime_adapter(runtime_type).get_quota_windows()
