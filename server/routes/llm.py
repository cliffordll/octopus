from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from packages.shared.api_paths.llm import (
    LLM_MODEL_DETAIL_PATH,
    LLM_MODEL_LIST_PATH,
    LLM_PROVIDER_DETAIL_PATH,
    LLM_PROVIDER_LIST_PATH,
)

from ..dependencies.access import require_actor_identity
from ..dependencies.runtime_providers import get_runtime_provider_service
from ..services.runtime_providers import RuntimeProviderService

router = APIRouter(tags=["llm"])

DEFAULT_RUNTIME_TYPE = "opencode_local"


@router.get(LLM_PROVIDER_LIST_PATH)
async def list_llm_providers_route(
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> list[dict[str, Any]]:
    return await service.list_llm_providers()


@router.post(LLM_PROVIDER_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_llm_provider_route(
    request: Request,
    body: dict[str, Any] = Body(...),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    try:
        return await service.create_provider(
            "",
            body,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        detail = str(exc)
        code = (
            status.HTTP_409_CONFLICT
            if "already exists" in detail
            else status.HTTP_422_UNPROCESSABLE_CONTENT
        )
        raise HTTPException(status_code=code, detail=detail) from exc


@router.patch(LLM_PROVIDER_DETAIL_PATH)
async def update_llm_provider_route(
    providerId: str,
    request: Request,
    runtimeType: str = DEFAULT_RUNTIME_TYPE,
    body: dict[str, Any] = Body(...),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    try:
        result = await service.update_provider(
            "",
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
            status_code=status.HTTP_404_NOT_FOUND, detail="LLM provider not found"
        )
    return result


@router.delete(LLM_PROVIDER_DETAIL_PATH)
async def delete_llm_provider_route(
    providerId: str,
    request: Request,
    runtimeType: str = DEFAULT_RUNTIME_TYPE,
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    result = await service.delete_provider(
        "",
        runtimeType,
        providerId,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="LLM provider not found"
        )
    return result


@router.get(LLM_MODEL_LIST_PATH)
async def list_llm_models_route(
    providerId: str,
    runtimeType: str = DEFAULT_RUNTIME_TYPE,
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> list[dict[str, Any]]:
    try:
        return await service.list_models("", runtimeType, providerId)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc


@router.post(LLM_MODEL_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_llm_model_route(
    providerId: str,
    request: Request,
    runtimeType: str = DEFAULT_RUNTIME_TYPE,
    body: dict[str, Any] = Body(...),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    try:
        return await service.create_model(
            "",
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


@router.patch(LLM_MODEL_DETAIL_PATH)
async def update_llm_model_route(
    providerId: str,
    modelId: str,
    request: Request,
    runtimeType: str = DEFAULT_RUNTIME_TYPE,
    body: dict[str, Any] = Body(...),
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    result = await service.update_model(
        "",
        runtimeType,
        providerId,
        modelId,
        body,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="LLM model not found"
        )
    return result


@router.delete(LLM_MODEL_DETAIL_PATH)
async def delete_llm_model_route(
    providerId: str,
    modelId: str,
    request: Request,
    runtimeType: str = DEFAULT_RUNTIME_TYPE,
    service: RuntimeProviderService = Depends(get_runtime_provider_service),
) -> dict[str, Any]:
    actor = require_actor_identity(request)
    result = await service.delete_model(
        "",
        runtimeType,
        providerId,
        modelId,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="LLM model not found"
        )
    return result
