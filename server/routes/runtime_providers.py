from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from packages.shared.api_paths.runtime_providers import (
    ORG_RUNTIME_MODEL_DETAIL_PATH,
    ORG_RUNTIME_MODEL_LIST_PATH,
    ORG_RUNTIME_PROVIDER_DETAIL_PATH,
    ORG_RUNTIME_PROVIDER_LIST_PATH,
)

from ..dependencies.access import require_actor_identity, require_organization_access
from ..dependencies.runtime_providers import get_runtime_provider_service
from ..services.runtime_providers import RuntimeProviderService

router = APIRouter(tags=["runtime-providers"])


@router.get(ORG_RUNTIME_PROVIDER_LIST_PATH)
async def list_runtime_providers_route(
    orgId: str,
    runtimeType: str,
    _: None = Depends(require_organization_access),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> list[dict[str, Any]]:
    try:
        return await service.list_providers(orgId, runtimeType)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(ORG_RUNTIME_PROVIDER_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_runtime_provider_route(
    orgId: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    try:
        return await service.create_provider(
            orgId, body, actor_type=actor.actor_type, actor_id=actor.actor_id
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_409_CONFLICT
            if "already exists" in detail
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(status_code=code, detail=detail) from exc


@router.patch(ORG_RUNTIME_PROVIDER_DETAIL_PATH)
async def update_runtime_provider_route(
    orgId: str,
    providerId: str,
    runtimeType: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    try:
        result = await service.update_provider(
            orgId,
            runtimeType,
            providerId,
            body,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Runtime provider not found"
        )
    return result


@router.delete(ORG_RUNTIME_PROVIDER_DETAIL_PATH)
async def delete_runtime_provider_route(
    orgId: str,
    providerId: str,
    runtimeType: str,
    request: Request,
    _: None = Depends(require_organization_access),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    try:
        result = await service.delete_provider(
            orgId,
            runtimeType,
            providerId,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Runtime provider not found"
        )
    return result


@router.get(ORG_RUNTIME_MODEL_LIST_PATH)
async def list_runtime_models_route(
    orgId: str,
    providerId: str,
    runtimeType: str,
    _: None = Depends(require_organization_access),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> list[dict[str, Any]]:
    try:
        return await service.list_models(orgId, runtimeType, providerId)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.post(ORG_RUNTIME_MODEL_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_runtime_model_route(
    orgId: str,
    providerId: str,
    runtimeType: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    try:
        return await service.create_model(
            orgId,
            runtimeType,
            providerId,
            body,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_409_CONFLICT
            if "already exists" in detail
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(status_code=code, detail=detail) from exc


@router.patch(ORG_RUNTIME_MODEL_DETAIL_PATH)
async def update_runtime_model_route(
    orgId: str,
    providerId: str,
    modelId: str,
    runtimeType: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    try:
        result = await service.update_model(
            orgId,
            runtimeType,
            providerId,
            modelId,
            body,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Runtime model not found"
        )
    return result


@router.delete(ORG_RUNTIME_MODEL_DETAIL_PATH)
async def delete_runtime_model_route(
    orgId: str,
    providerId: str,
    modelId: str,
    runtimeType: str,
    request: Request,
    _: None = Depends(require_organization_access),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    try:
        result = await service.delete_model(
            orgId,
            runtimeType,
            providerId,
            modelId,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Runtime model not found"
        )
    return result
