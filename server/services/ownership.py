from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.organization_ownership import (
    get_ownership_by_org_id,
    list_ownerships_for_pod,
)


class OwnershipDecision(str, Enum):
    OWNED = "owned"
    FOREIGN = "foreign"
    MISSING = "missing"
    EXPIRED = "expired"


def _default_now() -> datetime:
    return datetime.now(UTC)


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


class OwnershipService:
    def __init__(
        self,
        session: AsyncSession,
        pod_id: str,
        now: Callable[[], datetime] = _default_now,
    ) -> None:
        self._session = session
        self._pod_id = pod_id
        self._now = now

    async def check_organization(self, organization_id: str) -> OwnershipDecision:
        row = await get_ownership_by_org_id(self._session, organization_id)
        if row is None:
            return OwnershipDecision.MISSING
        if row.pod_id != self._pod_id:
            return OwnershipDecision.FOREIGN
        if _as_aware_utc(row.expires_at) <= _as_aware_utc(self._now()):
            return OwnershipDecision.EXPIRED
        return OwnershipDecision.OWNED

    async def list_owned_organization_ids(self) -> list[str]:
        rows = await list_ownerships_for_pod(self._session, self._pod_id)
        now_value = _as_aware_utc(self._now())
        return [
            row.organization_id
            for row in rows
            if _as_aware_utc(row.expires_at) > now_value
        ]
