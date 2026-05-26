from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.approvals import ApprovalService
from .database import get_session


def get_approval_service(
    session: AsyncSession = Depends(get_session),
) -> ApprovalService:
    return ApprovalService(session)
