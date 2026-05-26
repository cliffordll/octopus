from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.ownership import OwnershipDecision, OwnershipService
from .database import get_session


async def require_organization_ownership(
    orgId: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    settings = request.app.state.settings
    service = OwnershipService(session, settings.pod_id)
    decision = await service.check_organization(orgId)
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
