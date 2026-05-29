from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.workspaces import WorkspaceService
from .database import get_session


def get_workspace_service(
    session: AsyncSession = Depends(get_session),
) -> WorkspaceService:
    return WorkspaceService(session)
