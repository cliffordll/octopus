from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from server.identity import IdentityContext
from server.identity.resolver import IdentityContextResolver

from .errors import AccessDeniedError
from .policy import AccessPolicyService


ResourceT = TypeVar("ResourceT")


@dataclass(frozen=True, slots=True)
class ScopedResource(Generic[ResourceT]):
    resource: ResourceT
    context: IdentityContext


class AccessScopeResolver(ABC, Generic[ResourceT]):
    """Resolve a resource to its organization before applying access policy."""

    def __init__(self, session: AsyncSession) -> None:
        self._identities = IdentityContextResolver(session)
        self._policy = AccessPolicyService()

    @abstractmethod
    async def load(self, resource_id: str) -> ResourceT | None:
        raise NotImplementedError

    @abstractmethod
    def organization_id(self, resource: ResourceT) -> str:
        raise NotImplementedError

    async def resolve(
        self,
        resource_id: str,
        *,
        actor_type: str,
        actor_id: str,
        source: str,
        run_id: str | None,
    ) -> ScopedResource[ResourceT] | None:
        resource = await self.load(resource_id)
        if resource is None:
            return None
        org_id = self.organization_id(resource)
        context = await self._identities.resolve(
            actor_type=actor_type,
            actor_id=actor_id,
            org_id=org_id,
            source=source,
            run_id=run_id,
        )
        self._policy.require_organization_access(context, org_id)
        return ScopedResource(resource=resource, context=context)


__all__ = ["AccessDeniedError", "AccessScopeResolver", "ScopedResource"]
