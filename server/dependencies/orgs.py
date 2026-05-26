from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.types.organization import OrganizationDetail

from ..dependencies.ownership import assert_organization_owned
from ..services.orgs import OrgService
from .database import get_session


def get_org_service(session: AsyncSession = Depends(get_session)) -> OrgService:
    return OrgService(session)


async def get_owned_org_detail(
    orgId: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    service: OrgService = Depends(get_org_service),
) -> OrganizationDetail:
    org = await service.get(orgId)
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    await assert_organization_owned(request, session, orgId)
    return org
