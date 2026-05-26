from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.orgs import OrgService
from .database import get_session


def get_org_service(session: AsyncSession = Depends(get_session)) -> OrgService:
    return OrgService(session)
