from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.agents import get_agent_by_id
from packages.database.queries.heartbeat import get_run
from server.identity import PrincipalRef
from server.roles import RoleAccessService, RoleService

from .base import BaseTokenAuth
from .contracts import AuthResult
from .jwt import HmacJwtCodec


@dataclass(frozen=True, slots=True)
class RunTokenConfig:
    secret: str
    issuer: str = "rudder"
    audience: str = "rudder-api"
    ttl_seconds: int = 48 * 60 * 60

    @classmethod
    def from_env(cls) -> RunTokenConfig:
        return cls(
            secret=os.getenv("RUDDER_AGENT_JWT_SECRET")
            or os.getenv("BETTER_AUTH_SECRET")
            or "rudder-dev-secret",
            issuer=os.getenv("RUDDER_AGENT_JWT_ISSUER", "rudder"),
            audience=os.getenv("RUDDER_AGENT_JWT_AUDIENCE", "rudder-api"),
            ttl_seconds=int(os.getenv("RUDDER_AGENT_JWT_TTL_SECONDS", 48 * 60 * 60)),
        )


class RunTokenIssuer:
    def __init__(self, config: RunTokenConfig | None = None) -> None:
        self._config = config or RunTokenConfig.from_env()
        self._tokens = HmacJwtCodec(
            secret=self._config.secret,
            issuer=self._config.issuer,
            audience=self._config.audience,
        )

    def issue(
        self, *, agent_id: str, org_id: str, adapter_type: str, run_id: str
    ) -> str:
        now = int(time.time())
        return self._tokens.encode(
            {
                "sub": agent_id,
                "org_id": org_id,
                "adapter_type": adapter_type,
                "run_id": run_id,
                "jti": str(uuid.uuid4()),
                "iat": now,
                "exp": now + self._config.ttl_seconds,
            }
        )


class RunTokenAuth(BaseTokenAuth):
    def __init__(
        self, session: AsyncSession, config: RunTokenConfig | None = None
    ) -> None:
        self._session = session
        config = config or RunTokenConfig.from_env()
        self._tokens = HmacJwtCodec(
            secret=config.secret,
            issuer=config.issuer,
            audience=config.audience,
        )
        self._roles = RoleAccessService(RoleService(session))

    async def authenticate_token(self, token: str) -> AuthResult | None:
        claims = self._tokens.decode(token)
        required = ("sub", "org_id", "adapter_type", "run_id", "jti")
        if claims is None or any(key not in claims for key in required):
            return None
        agent_id = str(claims["sub"])
        org_id = str(claims["org_id"])
        run = await get_run(self._session, str(claims["run_id"]))
        agent = await get_agent_by_id(self._session, agent_id)
        if (
            run is None
            or agent is None
            or run.status != "running"
            or agent.status != "running"
        ):
            return None
        if run.agent_id != agent_id or run.org_id != org_id:
            return None
        if agent.org_id != org_id or agent.agent_runtime_type != claims["adapter_type"]:
            return None
        principal = PrincipalRef(type="agent", id=agent_id)
        if await self._roles.find_active("organization", org_id, principal) is None:
            return None
        return AuthResult(principal, "run_token", org_id, run.id)
