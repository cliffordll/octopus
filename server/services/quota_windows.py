from __future__ import annotations

import asyncio
from typing import Any

from packages.runtimes.registry import (
    get_runtime_quota_windows,
    list_quota_runtime_types,
)

_QUOTA_TIMEOUT_SECONDS = 20.0


def _provider_for_runtime(runtime_type: str) -> str:
    if runtime_type == "codex_local":
        return "openai"
    if runtime_type == "claude_local":
        return "anthropic"
    return runtime_type


class QuotaWindowService:
    async def fetch_org_quota_windows(self, org_id: str) -> dict[str, Any]:
        providers = await asyncio.gather(
            *[
                self._fetch_runtime(runtime_type)
                for runtime_type in list_quota_runtime_types()
            ]
        )
        return {
            "orgId": org_id,
            "providers": providers,
            "relation": {
                "quota": "provider usage window evidence",
                "budget": "organization/project/agent governance limit",
                "cost": "persisted run/activity billing fact",
            },
        }

    async def _fetch_runtime(self, runtime_type: str) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(
                get_runtime_quota_windows(runtime_type),
                timeout=_QUOTA_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            return {
                "provider": _provider_for_runtime(runtime_type),
                "source": runtime_type,
                "ok": False,
                "error": "quota polling timed out after 20s",
                "windows": [],
            }
        except Exception as exc:
            return {
                "provider": _provider_for_runtime(runtime_type),
                "source": runtime_type,
                "ok": False,
                "error": str(exc),
                "windows": [],
            }
