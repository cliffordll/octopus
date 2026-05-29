from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from packages.shared.api_paths.workspace_operations import WORKSPACE_OPERATION_LOG_PATH

from ..dependencies.access import assert_organization_access
from ..dependencies.workspaces import get_workspace_service
from ..services.workspaces import WorkspaceService

router = APIRouter(tags=["workspace-operations"])


@router.get(WORKSPACE_OPERATION_LOG_PATH)
async def get_workspace_operation_log_route(
    operationId: str,
    request: Request,
    offset: int = 0,
    limitBytes: int = 256_000,
    service: WorkspaceService = Depends(get_workspace_service),
) -> JSONResponse:
    operation = await service.get_operation(operationId)
    if operation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace operation not found",
        )
    assert_organization_access(request, operation["orgId"])
    log = await service.read_operation_log(
        operationId, offset=offset, limit_bytes=limitBytes
    )
    assert log is not None
    return JSONResponse(
        log,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
