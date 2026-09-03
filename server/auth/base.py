from __future__ import annotations

from abc import ABC, abstractmethod

from .contracts import AuthResult


class BaseTokenAuth(ABC):
    async def authenticate(self, credential: str) -> AuthResult | None:
        token = self.extract_bearer_token(credential)
        if token is None:
            return None
        return await self.authenticate_token(token)

    @staticmethod
    def extract_bearer_token(credential: str) -> str | None:
        scheme, separator, token = credential.strip().partition(" ")
        if not separator or scheme.lower() != "bearer" or not token.strip():
            return None
        return token.strip()

    @abstractmethod
    async def authenticate_token(self, token: str) -> AuthResult | None:
        raise NotImplementedError
