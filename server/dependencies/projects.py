from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.projects import ProjectService
from .database import get_session


def get_project_service(
    session: AsyncSession = Depends(get_session),
) -> ProjectService:
    return ProjectService(session)
