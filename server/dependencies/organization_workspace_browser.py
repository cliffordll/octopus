from __future__ import annotations

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from ..services.organization_workspace_browser import (
    OrganizationWorkspaceBrowserService,
)
from .database import get_session


def get_organization_workspace_browser_service(
    session: AsyncSession = Depends(get_session),
) -> OrganizationWorkspaceBrowserService:
    return OrganizationWorkspaceBrowserService(session)
