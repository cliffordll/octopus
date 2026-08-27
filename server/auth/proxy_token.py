from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.external_user_bindings import get_external_user_binding
from server.identity import PrincipalRef
from server.membership import MemberAccessService, MemberService

from .base import BaseTokenAuth
from .contracts import AuthResult


class ProxyTokenAuth(BaseTokenAuth):
    def __init__(
        self, session: AsyncSession, *, secret: str, issuer: str, audience: str
    ) -> None:
        self._session = session
        self._secret = secret.encode()
        self._issuer = issuer
        self._audience = audience
        self._members = MemberAccessService(MemberService(session))

    async def authenticate_token(self, token: str) -> AuthResult | None:
        claims = self._verify(token)
        if claims is None:
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

    def _verify(self, token: str) -> dict[str, Any] | None:
        try:
            encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
            header = json.loads(_decode(encoded_header))
            claims = json.loads(_decode(encoded_payload))
            signature = _decode_bytes(encoded_signature)
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        if header.get("alg") != "HS256":
            return None
        signed = f"{encoded_header}.{encoded_payload}".encode()
        expected = hmac.new(self._secret, signed, hashlib.sha256).digest()
        now = int(time.time())
        required = ("iss", "aud", "sub", "iat", "exp", "jti", "org_id")
        if not hmac.compare_digest(signature, expected) or any(
            key not in claims for key in required
        ):
            return None
        if claims["iss"] != self._issuer or claims["aud"] != self._audience:
            return None
        if not isinstance(claims["iat"], int) or not isinstance(claims["exp"], int):
            return None
        if claims["iat"] > now + 60 or claims["exp"] <= now:
            return None
        return claims


def _decode(value: str) -> str:
    return _decode_bytes(value).decode()


def _decode_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
