from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.types.organization import OrganizationDetail

from ..services.orgs import OrgService
from .database import get_session


def get_org_service(session: AsyncSession = Depends(get_session)) -> OrgService:
    return OrgService(session)


async def get_org_detail(
    orgId: str,
    service: OrgService = Depends(get_org_service),
) -> OrganizationDetail:
    org = await service.get(orgId)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return org
