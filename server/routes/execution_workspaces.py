from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from ..dependencies.access import assert_organization_access
from ..dependencies.workspaces import get_workspace_service
from ..services.workspaces import WorkspaceService

router = APIRouter(tags=["execution-workspaces"])


async def _workspace_or_404(
    workspace_id: str, *, request: Request, service: WorkspaceService
) -> Any:
    workspace = await service.get_execution_workspace(workspace_id)
    if workspace is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Execution workspace not found",
        )
    assert_organization_access(request, workspace["orgId"])
    return workspace


@router.get("/api/execution-workspaces")
async def list_execution_workspaces_route(
    request: Request,
    orgId: str,
    projectId: str | None = None,
    issueId: str | None = None,
    service: WorkspaceService = Depends(get_workspace_service),
) -> Any:
    assert_organization_access(request, orgId)
    return await service.list_execution_workspaces(
        orgId, project_id=projectId, issue_id=issueId, reuse_eligible=False
    )


@router.get("/api/execution-workspaces/{workspaceId}")
async def get_execution_workspace_route(
    workspaceId: str,
    request: Request,
    service: WorkspaceService = Depends(get_workspace_service),
) -> Any:
    return await _workspace_or_404(workspaceId, request=request, service=service)


@router.get("/api/execution-workspaces/{workspaceId}/status")
async def get_execution_workspace_status_route(
    workspaceId: str,
    request: Request,
    service: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, Any]:
    workspace = await _workspace_or_404(workspaceId, request=request, service=service)
    result = await service.workspace_status(workspace["id"])
    assert result is not None
    return result


@router.get("/api/execution-workspaces/{workspaceId}/diff")
async def get_execution_workspace_diff_route(
    workspaceId: str,
    request: Request,
    service: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, Any]:
    workspace = await _workspace_or_404(workspaceId, request=request, service=service)
    result = await service.git_diff_for_workspace(workspace["id"])
    assert result is not None
    return result


@router.post("/api/execution-workspaces/{workspaceId}/merge-preview")
async def preview_execution_workspace_merge_route(
    workspaceId: str,
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    service: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, Any]:
    workspace = await _workspace_or_404(workspaceId, request=request, service=service)
    try:
        result = await service.merge_preview(
            workspace["id"], target_ref=body.get("targetRef")
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    assert result is not None
    return result


@router.post("/api/execution-workspaces/{workspaceId}/merge")
async def merge_execution_workspace_route(
    workspaceId: str,
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    service: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, Any]:
    workspace = await _workspace_or_404(workspaceId, request=request, service=service)
    target_ref = body.get("targetRef")
    try:
        result = await service.merge_workspace(
            workspace["id"],
            target_ref=target_ref if isinstance(target_ref, str) else None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    assert result is not None
    return result


@router.post("/api/execution-workspaces/{workspaceId}/prepare-pr")
async def prepare_execution_workspace_pr_route(
    workspaceId: str,
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    service: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, Any]:
    workspace = await _workspace_or_404(workspaceId, request=request, service=service)
    target_ref = body.get("targetRef")
    try:
        result = await service.prepare_pull_request(
            workspace["id"],
            remote=str(body.get("remote") or "origin"),
            target_ref=target_ref if isinstance(target_ref, str) else None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    assert result is not None
    return result


@router.post("/api/execution-workspaces/{workspaceId}/create-pr")
async def create_execution_workspace_pr_route(
    workspaceId: str,
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    service: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, Any]:
    workspace = await _workspace_or_404(workspaceId, request=request, service=service)
    target_ref = body.get("targetRef")
    title = body.get("title")
    pr_body = body.get("body")
    try:
        result = await service.create_pull_request(
            workspace["id"],
            remote=str(body.get("remote") or "origin"),
            target_ref=target_ref if isinstance(target_ref, str) else None,
            title=title if isinstance(title, str) else None,
            body=pr_body if isinstance(pr_body, str) else None,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    assert result is not None
    return result


@router.post("/api/execution-workspaces/{workspaceId}/push")
async def push_execution_workspace_route(
    workspaceId: str,
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    service: WorkspaceService = Depends(get_workspace_service),
) -> dict[str, Any]:
    workspace = await _workspace_or_404(workspaceId, request=request, service=service)
    try:
        result = await service.push_workspace_branch(
            workspace["id"],
            remote=str(body.get("remote") or "origin"),
            set_upstream=bool(body.get("setUpstream", True)),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    assert result is not None
    return result


@router.post("/api/execution-workspaces/{workspaceId}/abandon")
async def abandon_execution_workspace_route(
    workspaceId: str,
    request: Request,
    service: WorkspaceService = Depends(get_workspace_service),
) -> Any:
    workspace = await _workspace_or_404(workspaceId, request=request, service=service)
    try:
        abandoned = await service.abandon_workspace(workspace["id"])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    assert abandoned is not None
    return abandoned


@router.post("/api/execution-workspaces/{workspaceId}/cleanup")
async def cleanup_execution_workspace_route(
    workspaceId: str,
    request: Request,
    body: dict[str, Any] = Body(default_factory=dict),
    service: WorkspaceService = Depends(get_workspace_service),
) -> Any:
    workspace = await _workspace_or_404(workspaceId, request=request, service=service)
    try:
        cleaned = await service.cleanup_workspace(
            workspace["id"], discard_dirty=bool(body.get("discardDirty", False))
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    assert cleaned is not None
    return cleaned


@router.post("/api/execution-workspaces/{workspaceId}/archive")
async def archive_execution_workspace_route(
    workspaceId: str,
    request: Request,
    service: WorkspaceService = Depends(get_workspace_service),
) -> Any:
    workspace = await _workspace_or_404(workspaceId, request=request, service=service)
    try:
        archived = await service.archive_workspace(workspace["id"])
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=str(exc)
        ) from exc
    assert archived is not None
    return archived
