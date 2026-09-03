from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from server.identity import PrincipalRef


@dataclass(frozen=True, slots=True)
class AuthResult:
    principal: PrincipalRef
    source: str
    org_id: str | None = None
    run_id: str | None = None


class AuthProviderProtocol(Protocol):
    async def authenticate(self, credential: str) -> AuthResult | None: ...
