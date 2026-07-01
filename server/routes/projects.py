from __future__ import annotations

from typing import Any
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status

from packages.shared.api_paths.projects import (
    ORG_PROJECT_LIST_PATH,
    PROJECT_DETAIL_PATH,
    PROJECT_RESOURCE_DETAIL_PATH,
    PROJECT_RESOURCE_LIST_PATH,
    PROJECT_WORKSPACE_DETAIL_PATH,
    PROJECT_WORKSPACE_LIST_PATH,
)
from packages.shared.types.project import (
    ProjectDetail,
    ProjectResourceAttachment,
    ProjectWorkspace,
)
from packages.shared.validators.project import (
    validate_create_project,
    validate_create_project_workspace,
    validate_project_resource_attachment_input,
    validate_update_project,
    validate_update_project_resource_attachment,
    validate_update_project_workspace,
)

from ..dependencies.access import (
    assert_organization_access,
    require_actor_identity,
    require_organization_access,
)
from ..dependencies.projects import get_project_service
from ..services.projects import ProjectService

router = APIRouter(tags=["projects"])


def _is_uuid_like(value: str) -> bool:
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


async def _get_project_or_404(
    project_id: str,
    *,
    request: Request,
    service: ProjectService,
    org_id: str | None = None,
) -> ProjectDetail:
    if org_id is not None and not _is_uuid_like(project_id):
        assert_organization_access(request, org_id)
    try:
        detail = await service.resolve_by_reference(project_id, org_id=org_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    assert_organization_access(request, detail["orgId"])
    return detail


@router.get(ORG_PROJECT_LIST_PATH)
async def list_projects_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    service: ProjectService = Depends(get_project_service),
) -> list[ProjectDetail]:
    return await service.list_for_org(orgId)


@router.post(ORG_PROJECT_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_project_route(
    request: Request,
    orgId: str,
    body: dict[str, Any] = Body(...),
    _: None = Depends(require_organization_access),
    service: ProjectService = Depends(get_project_service),
) -> ProjectDetail:
    try:
        payload = validate_create_project(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    actor = require_actor_identity(request)
    try:
        return await service.create_project(
            orgId, payload, actor_type=actor.actor_type, actor_id=actor.actor_id
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc


@router.get(PROJECT_DETAIL_PATH)
async def get_project_route(
    id: str,
    request: Request,
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> ProjectDetail:
    return await _get_project_or_404(id, request=request, service=service, org_id=orgId)


@router.patch(PROJECT_DETAIL_PATH)
async def update_project_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> ProjectDetail:
    detail = await _get_project_or_404(
        id, request=request, service=service, org_id=orgId
    )
    try:
        payload = validate_update_project(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    actor = require_actor_identity(request)
    updated = await service.update_project(
        detail["id"], payload, actor_type=actor.actor_type, actor_id=actor.actor_id
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    return updated


@router.delete(PROJECT_DETAIL_PATH)
async def delete_project_route(
    id: str,
    request: Request,
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> ProjectDetail:
    detail = await _get_project_or_404(
        id, request=request, service=service, org_id=orgId
    )
    actor = require_actor_identity(request)
    removed = await service.delete_project(
        detail["id"], actor_type=actor.actor_type, actor_id=actor.actor_id
    )
    if removed is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    return removed


@router.get(PROJECT_WORKSPACE_LIST_PATH)
async def list_project_workspaces_route(
    id: str,
    request: Request,
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> list[ProjectWorkspace]:
    detail = await _get_project_or_404(
        id, request=request, service=service, org_id=orgId
    )
    return await service.list_workspaces(detail["id"])


@router.post(PROJECT_WORKSPACE_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def create_project_workspace_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> ProjectWorkspace:
    detail = await _get_project_or_404(
        id, request=request, service=service, org_id=orgId
    )
    try:
        payload = validate_create_project_workspace(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    actor = require_actor_identity(request)
    workspace = await service.create_workspace(
        detail["id"], payload, actor_type=actor.actor_type, actor_id=actor.actor_id
    )
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    return workspace


@router.patch(PROJECT_WORKSPACE_DETAIL_PATH)
async def update_project_workspace_route(
    id: str,
    workspaceId: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> ProjectWorkspace:
    detail = await _get_project_or_404(
        id, request=request, service=service, org_id=orgId
    )
    try:
        payload = validate_update_project_workspace(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    actor = require_actor_identity(request)
    workspace = await service.update_workspace(
        detail["id"],
        workspaceId,
        payload,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project workspace not found",
        )
    return workspace


@router.delete(PROJECT_WORKSPACE_DETAIL_PATH)
async def delete_project_workspace_route(
    id: str,
    workspaceId: str,
    request: Request,
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> ProjectWorkspace:
    detail = await _get_project_or_404(
        id, request=request, service=service, org_id=orgId
    )
    actor = require_actor_identity(request)
    try:
        workspace = await service.remove_workspace(
            detail["id"],
            workspaceId,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project workspace not found",
        )
    return workspace


@router.get(PROJECT_RESOURCE_LIST_PATH)
async def list_project_resources_route(
    id: str,
    request: Request,
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> list[ProjectResourceAttachment]:
    detail = await _get_project_or_404(
        id, request=request, service=service, org_id=orgId
    )
    return await service.list_resources(detail["id"])


@router.post(PROJECT_RESOURCE_LIST_PATH, status_code=status.HTTP_201_CREATED)
async def add_project_resource_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> ProjectResourceAttachment:
    detail = await _get_project_or_404(
        id, request=request, service=service, org_id=orgId
    )
    try:
        payload = validate_project_resource_attachment_input(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    actor = require_actor_identity(request)
    attachment = await service.add_resource_attachment(
        detail["id"], payload, actor_type=actor.actor_type, actor_id=actor.actor_id
    )
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found"
        )
    return attachment


@router.patch(PROJECT_RESOURCE_DETAIL_PATH)
async def update_project_resource_route(
    id: str,
    attachmentId: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> ProjectResourceAttachment:
    detail = await _get_project_or_404(
        id, request=request, service=service, org_id=orgId
    )
    try:
        payload = validate_update_project_resource_attachment(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    actor = require_actor_identity(request)
    attachment = await service.update_resource_attachment(
        detail["id"],
        attachmentId,
        payload,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project resource attachment not found",
        )
    return attachment


@router.delete(PROJECT_RESOURCE_DETAIL_PATH)
async def delete_project_resource_route(
    id: str,
    attachmentId: str,
    request: Request,
    orgId: str | None = Query(default=None),
    service: ProjectService = Depends(get_project_service),
) -> ProjectResourceAttachment:
    detail = await _get_project_or_404(
        id, request=request, service=service, org_id=orgId
    )
    actor = require_actor_identity(request)
    attachment = await service.remove_resource_attachment(
        detail["id"],
        attachmentId,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project resource attachment not found",
        )
    return attachment
