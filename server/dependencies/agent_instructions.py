from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.agent_instructions import AgentInstructionsService
from .database import get_session


def get_agent_instructions_service(
    session: AsyncSession = Depends(get_session),
) -> AgentInstructionsService:
    return AgentInstructionsService(session)
