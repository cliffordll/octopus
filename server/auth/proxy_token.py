from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.external_identities import get_external_identity
from server.identity import PrincipalRef
from server.roles import RoleAccessService, RoleService

from .base import BaseTokenAuth
from .contracts import AuthResult
from .jwt import HmacJwtCodec


class ProxyTokenAuth(BaseTokenAuth):
    def __init__(
        self, session: AsyncSession, *, secret: str, issuer: str, audience: str
    ) -> None:
        self._session = session
        self._tokens = HmacJwtCodec(secret=secret, issuer=issuer, audience=audience)
        self._roles = RoleAccessService(RoleService(session))

    async def authenticate_token(self, token: str) -> AuthResult | None:
        claims = self._tokens.decode(token)
        required = ("iss", "aud", "sub", "iat", "exp", "jti", "org_id")
        if claims is None or any(key not in claims for key in required):
            return None
        binding = await get_external_identity(
            self._session, str(claims["iss"]), str(claims["sub"])
        )
        if binding is None:
            return None
        org_id = str(claims["org_id"])
        principal = PrincipalRef(type="user", id=binding.user_id)
        if await self._roles.find_active("organization", org_id, principal) is None:
            return None
        return AuthResult(principal, "proxy_token", org_id)
