from __future__ import annotations

from fastapi import APIRouter

from packages.shared.api_paths.health import HEALTH_PATH

router = APIRouter(tags=["health"])


@router.get(HEALTH_PATH)
async def get_health() -> dict[str, str]:
    return {"status": "ok"}
