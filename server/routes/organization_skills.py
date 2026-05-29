from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from packages.shared.api_paths.organization_skills import (
    ORG_SKILL_DETAIL_PATH,
    ORG_SKILL_FILE_PATH,
    ORG_SKILL_LIST_PATH,
    ORG_SKILL_UPDATE_STATUS_PATH,
)
from packages.shared.types.organization_skill import (
    OrganizationSkill,
    OrganizationSkillDetail,
    OrganizationSkillFileDetail,
    OrganizationSkillListItem,
    OrganizationSkillUpdateStatus,
)
from packages.shared.validators.organization_skills import (
    validate_create_organization_skill,
    validate_update_organization_skill_file,
)

from ..dependencies.access import require_actor_identity, require_organization_access
from ..dependencies.organization_skills import get_organization_skill_service
from ..services.organization_skills import (
    OrganizationSkillConflictError,
    OrganizationSkillPathError,
    OrganizationSkillService,
)

router = APIRouter(tags=["organization-skills"])


@router.get(ORG_SKILL_LIST_PATH)
async def list_organization_skills(
    orgId: str,
    _: None = Depends(require_organization_access),
    service: OrganizationSkillService = Depends(get_organization_skill_service),
) -> list[OrganizationSkillListItem]:
    return await service.list(orgId)


@router.post(ORG_SKILL_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_organization_skill(
    request: Request,
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: OrganizationSkillService = Depends(get_organization_skill_service),
) -> OrganizationSkill:
    try:
        payload = validate_create_organization_skill(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor = require_actor_identity(request)
    try:
        return await service.create_local_skill(
            orgId,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except OrganizationSkillConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.get(ORG_SKILL_DETAIL_PATH)
async def get_organization_skill(
    orgId: str,
    skillId: str,
    _: None = Depends(require_organization_access),
    service: OrganizationSkillService = Depends(get_organization_skill_service),
) -> OrganizationSkillDetail:
    detail = await service.detail(orgId, skillId)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )
    return detail


@router.get(ORG_SKILL_UPDATE_STATUS_PATH)
async def get_organization_skill_update_status(
    orgId: str,
    skillId: str,
    _: None = Depends(require_organization_access),
    service: OrganizationSkillService = Depends(get_organization_skill_service),
) -> OrganizationSkillUpdateStatus:
    detail = await service.update_status(orgId, skillId)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )
    return detail


@router.get(ORG_SKILL_FILE_PATH)
async def read_organization_skill_file(
    orgId: str,
    skillId: str,
    path: str = Query(default="SKILL.md"),
    _: None = Depends(require_organization_access),
    service: OrganizationSkillService = Depends(get_organization_skill_service),
) -> OrganizationSkillFileDetail:
    try:
        detail = await service.read_file(orgId, skillId, path)
    except OrganizationSkillPathError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )
    return detail


@router.patch(ORG_SKILL_FILE_PATH)
async def update_organization_skill_file(
    request: Request,
    orgId: str,
    skillId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: OrganizationSkillService = Depends(get_organization_skill_service),
) -> OrganizationSkillFileDetail:
    try:
        payload = validate_update_organization_skill_file(body)
        actor = require_actor_identity(request)
        detail = await service.update_file(
            orgId,
            skillId,
            payload["path"],
            payload["content"],
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except (ValueError, OrganizationSkillPathError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )
    return detail


@router.delete(ORG_SKILL_DETAIL_PATH)
async def delete_organization_skill(
    request: Request,
    orgId: str,
    skillId: str,
    _: None = Depends(require_organization_access),
    service: OrganizationSkillService = Depends(get_organization_skill_service),
) -> OrganizationSkill:
    actor = require_actor_identity(request)
    deleted = await service.delete_skill(
        orgId,
        skillId,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if deleted is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found",
        )
    return deleted
