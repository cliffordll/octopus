from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.assets import get_asset_by_id

from ..dependencies.access import assert_organization_access
from ..dependencies.database import get_session
from ..storage import StorageService, get_storage_service


router = APIRouter(tags=["assets"])


@router.get("/api/assets/{assetId}/content")
async def get_asset_content(
    assetId: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> Response:
    asset = await get_asset_by_id(session, assetId)
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found",
        )
    assert_organization_access(request, asset.org_id)
    storage = _storage_for_request(request)
    try:
        content = await storage.get_object_bytes(asset.org_id, asset.object_key)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Object not found",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    filename = (asset.original_filename or "asset").replace('"', "")
    return Response(
        content=content,
        media_type=asset.content_type or "application/octet-stream",
        headers={
            "Cache-Control": "private, max-age=60",
            "Content-Disposition": (
                f"inline; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


def _storage_for_request(request: Request) -> StorageService:
    storage = getattr(request.app.state, "storage_service", None)
    if storage is not None:
        return storage
    return get_storage_service()
