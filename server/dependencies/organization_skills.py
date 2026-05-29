from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.organization_skills import OrganizationSkillService
from .database import get_session


def get_organization_skill_service(
    session: AsyncSession = Depends(get_session),
) -> OrganizationSkillService:
    return OrganizationSkillService(session)
