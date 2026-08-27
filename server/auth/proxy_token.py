from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.external_user_bindings import get_external_user_binding
from server.identity import PrincipalRef
from server.membership import MemberAccessService, MemberService

from .base import BaseTokenAuth
from .contracts import AuthResult
from .jwt import HmacJwtCodec


class ProxyTokenAuth(BaseTokenAuth):
    def __init__(
        self, session: AsyncSession, *, secret: str, issuer: str, audience: str
    ) -> None:
        self._session = session
        self._tokens = HmacJwtCodec(secret=secret, issuer=issuer, audience=audience)
        self._members = MemberAccessService(MemberService(session))

    async def authenticate_token(self, token: str) -> AuthResult | None:
        claims = self._tokens.decode(token)
        required = ("iss", "aud", "sub", "iat", "exp", "jti", "org_id")
        if claims is None or any(key not in claims for key in required):
            return None
        binding = await get_external_user_binding(
            self._session, str(claims["iss"]), str(claims["sub"])
        )
        if binding is None:
            return None
        org_id = str(claims["org_id"])
        principal = PrincipalRef(type="user", id=binding.local_user_id)
        if await self._members.find_active(org_id, principal) is None:
            return None
        return AuthResult(principal, "proxy_token", org_id)
