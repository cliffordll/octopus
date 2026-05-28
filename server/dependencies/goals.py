from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.goals import GoalService
from .database import get_session


def get_goal_service(session: AsyncSession = Depends(get_session)) -> GoalService:
    return GoalService(session)
