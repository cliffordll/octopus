from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.runtimes import RuntimeAdapterProtocol
from server.auth import RunTokenIssuer

from .runtime_providers import inject_runtime_provider_config


@dataclass(frozen=True, slots=True)
class ResolvedRuntimeAccess:
    config: dict[str, Any]
    env: dict[str, str] | None


class RuntimeAccessResolver:
    """Materialize transient runtime credentials at the execution boundary."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        run_tokens: RunTokenIssuer | None = None,
    ) -> None:
        self._session = session
        self._run_tokens = run_tokens or RunTokenIssuer()

    async def resolve(
        self,
        *,
        adapter: RuntimeAdapterProtocol,
        run_id: str,
        agent_id: str,
        org_id: str,
        runtime_type: str,
        config: dict[str, Any],
        env: dict[str, str] | None,
    ) -> ResolvedRuntimeAccess:
        resolved_config = await inject_runtime_provider_config(
            self._session,
            org_id=org_id,
            runtime_type=runtime_type,
            config=config,
        )
        resolved_env = dict(env) if env is not None else {}
        if getattr(adapter, "supports_local_agent_jwt", False):
            resolved_env["RUDDER_API_KEY"] = self._run_tokens.issue(
                agent_id=agent_id,
                org_id=org_id,
                adapter_type=runtime_type,
                run_id=run_id,
            )
            api_url = resolved_env.get("OCTOPUS_API_URL") or os.getenv(
                "OCTOPUS_API_URL", "http://localhost:8000"
            )
            resolved_env.setdefault("RUDDER_API_URL", api_url)
        else:
            resolved_env.pop("RUDDER_API_KEY", None)
            resolved_env.pop("RUDDER_API_URL", None)
        return ResolvedRuntimeAccess(
            config=resolved_config,
            env=resolved_env or None,
        )
