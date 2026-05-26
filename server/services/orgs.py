from __future__ import annotations

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.organizations import (
    get_organization_by_id,
    list_organizations,
)
from packages.shared.constants.organization import OrganizationStatus
from packages.shared.types.organization import OrganizationDetail, OrganizationSummary


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

    async def get(self, org_id: str) -> OrganizationDetail | None:
        row = await get_organization_by_id(self._session, org_id)
        if row is None:
            return None
        return OrganizationDetail(
            id=row.id,
            urlKey=row.url_key,
            name=row.name,
            status=cast(OrganizationStatus, row.status),
            description=row.description,
            issuePrefix=row.issue_prefix,
            issueCounter=row.issue_counter,
            budgetMonthlyCents=row.budget_monthly_cents,
            spentMonthlyCents=row.spent_monthly_cents,
            brandColor=row.brand_color,
            createdAt=row.created_at.isoformat(),
            updatedAt=row.updated_at.isoformat(),
        )
