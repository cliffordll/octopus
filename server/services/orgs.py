from __future__ import annotations

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.organizations import list_organizations
from packages.shared.constants.organization import OrganizationStatus
from packages.shared.types.organization import OrganizationSummary


class OrgService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[OrganizationSummary]:
        rows = await list_organizations(self._session)
        return [
            OrganizationSummary(
                id=row.id,
                urlKey=row.url_key,
                name=row.name,
                status=cast(OrganizationStatus, row.status),
            )
            for row in rows
        ]
