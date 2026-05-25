from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from ..services.orgs import OrgService

router = APIRouter(prefix="/api/orgs", tags=["orgs"])


def get_org_service() -> OrgService:
    return OrgService()


@router.get("")
async def list_orgs(
    service: OrgService = Depends(get_org_service),
) -> list[dict[str, Any]]:
    return await service.list()
