from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.ownership import OwnershipDecision, OwnershipService
from .database import get_session


def _ownership_decision_to_http(decision: OwnershipDecision) -> None:
    match decision:
        case OwnershipDecision.OWNED:
            return
        case OwnershipDecision.EXPIRED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Organization ownership lease has expired",
            )
        case OwnershipDecision.FOREIGN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization is owned by another pod",
            )
        case OwnershipDecision.MISSING:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Organization has no ownership record",
            )


async def assert_organization_owned(
    request: Request,
    session: AsyncSession,
    organization_id: str,
) -> None:
    settings = request.app.state.settings
    service = OwnershipService(session, settings.pod_id)
    decision = await service.check_organization(organization_id)
    _ownership_decision_to_http(decision)


async def require_organization_ownership(
    orgId: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    await assert_organization_owned(request, session, orgId)
