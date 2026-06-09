from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from packages.shared.api_paths.issue_attachments import (
    ATTACHMENT_DETAIL_PATH,
    ISSUE_ATTACHMENTS_PATH,
    ORG_ISSUE_ATTACHMENTS_PATH,
)
from packages.shared.api_paths.heartbeat import ISSUE_HEARTBEAT_RUNS_PATH
from packages.shared.api_paths.issues import (
    ISSUE_CHECKOUT_PATH,
    ISSUE_COMMENT_LIST_PATH,
    ISSUE_DOCUMENT_DETAIL_PATH,
    ISSUE_DOCUMENT_REVISIONS_PATH,
    ISSUE_DOCUMENTS_PATH,
    ISSUE_DETAIL_PATH,
    ISSUE_EXECUTE_PATH,
    ISSUE_HEARTBEAT_CONTEXT_PATH,
    ISSUE_LIST_MISSING_ORG_PATH,
    ISSUE_REVIEW_DECISION_PATH,
    ISSUE_WORK_PRODUCTS_PATH,
    ORG_ISSUE_LIST_PATH,
    WORK_PRODUCT_DETAIL_PATH,
)
from packages.shared.types.heartbeat import HeartbeatRun, WakeAgentPayload
from packages.shared.types.issue import (
    DocumentRevision,
    IssueDetail,
    IssueDocument,
    IssueDocumentSummary,
    IssueListItem,
)
from packages.shared.types.issue_attachment import IssueAttachment
from packages.shared.types.workspace import IssueWorkProduct
from packages.shared.validators.issue import (
    validate_create_issue,
    validate_create_issue_comment,
    validate_checkout_issue,
    validate_issue_document_key,
    validate_list_org_issues_query,
    validate_record_issue_review_decision,
    validate_upsert_issue_document,
    validate_update_issue,
)
from packages.shared.validators.work_product import (
    validate_create_issue_work_product,
    validate_update_issue_work_product,
)

from ..dependencies.access import (
    assert_organization_access,
    require_actor_identity,
    require_board_access,
    require_organization_access,
)
from ..dependencies.heartbeat import get_heartbeat_service
from ..dependencies.issues import get_issue_service
from ..dependencies.documents import get_document_service
from ..dependencies.workspaces import get_workspace_service
from ..services.heartbeat import HeartbeatService, dispatch_queued_agent
from ..services.issue_assignment_wakeup import queue_issue_assignment_wakeup
from ..services.issue_review_wakeup import queue_issue_review_wakeup
from ..services.issues import IssueCheckoutConflictError, IssueService
from ..services.documents import DocumentService
from ..services.workspaces import WorkspaceService
from ..storage import StorageService, get_storage_service

router = APIRouter(tags=["issues"])


def _schedule_dispatch(request: Request, agent_id: str) -> None:
    async def dispatch_after_commit() -> None:
        # Let the request-scoped transaction close before the dispatcher claims
        # the queued run with a separate session.
        await asyncio.sleep(0.05)
        await dispatch_queued_agent(request.app.state.session_factory, agent_id)

    task = asyncio.create_task(dispatch_after_commit())
    tasks = getattr(request.app.state, "heartbeat_dispatch_tasks", set())
    tasks.add(task)
    request.app.state.heartbeat_dispatch_tasks = tasks
    task.add_done_callback(tasks.discard)


@router.get(ISSUE_LIST_MISSING_ORG_PATH)
async def list_org_issues_missing_org_route() -> None:
    raise HTTPException(
        status_code=http_status.HTTP_400_BAD_REQUEST,
        detail="Missing orgId in path. Use /api/orgs/{orgId}/issues.",
    )


@router.get(ORG_ISSUE_LIST_PATH)
async def list_org_issues_route(
    orgId: str,
    _: None = Depends(require_organization_access),
    service: IssueService = Depends(get_issue_service),
    status: str | None = Query(default=None),
    assigneeAgentId: str | None = Query(default=None),
    projectId: str | None = Query(default=None),
    goalId: str | None = Query(default=None),
    parentId: str | None = Query(default=None),
    originKind: str | None = Query(default=None),
    originId: str | None = Query(default=None),
) -> list[IssueListItem]:
    raw_query: dict[str, str] = {}
    if status is not None:
        raw_query["status"] = status
    if assigneeAgentId is not None:
        raw_query["assigneeAgentId"] = assigneeAgentId
    if projectId is not None:
        raw_query["projectId"] = projectId
    if goalId is not None:
        raw_query["goalId"] = goalId
    if parentId is not None:
        raw_query["parentId"] = parentId
    if originKind is not None:
        raw_query["originKind"] = originKind
    if originId is not None:
        raw_query["originId"] = originId
    try:
        validated = validate_list_org_issues_query(raw_query)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return await service.list_for_org(
        orgId,
        status=validated.get("status"),
        assignee_agent_id=validated.get("assigneeAgentId"),
        project_id=validated.get("projectId"),
        goal_id=validated.get("goalId"),
        parent_id=validated.get("parentId"),
        origin_kind=validated.get("originKind"),
        origin_id=validated.get("originId"),
    )


@router.post(ORG_ISSUE_LIST_PATH)
async def create_issue_route(
    request: Request,
    orgId: str,
    _: None = Depends(require_organization_access),
    service: IssueService = Depends(get_issue_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
    body: dict[str, Any] = Body(...),
) -> IssueDetail:
    try:
        payload = validate_create_issue(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor = require_actor_identity(request)
    try:
        issue = await service.create_issue(
            orgId,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            run_id=actor.run_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    await queue_issue_assignment_wakeup(
        heartbeat,
        issue,
        reason="issue_assigned",
        mutation="create",
        context_source="issue.create",
        actor_type="agent" if actor.actor_type == "agent" else "user",
        actor_id=actor.actor_id,
    )
    await queue_issue_review_wakeup(
        heartbeat,
        issue,
        mutation="create_in_review",
        context_source="issue.create",
        actor_type="agent" if actor.actor_type == "agent" else "user",
        actor_id=actor.actor_id,
        actor_agent_id=actor.actor_id if actor.actor_type == "agent" else None,
    )
    return issue


@router.get(ISSUE_DETAIL_PATH)
async def get_issue_route(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
) -> IssueDetail:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    return detail


@router.get(ISSUE_HEARTBEAT_RUNS_PATH)
async def list_issue_heartbeat_runs_route(
    issueId: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> list[dict[str, Any]]:
    detail = await service.get_by_id(issueId)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    runs = await heartbeat.list_for_issue(issueId)
    assert runs is not None
    return runs


@router.get(ISSUE_HEARTBEAT_CONTEXT_PATH)
async def get_issue_heartbeat_context_route(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
) -> dict[str, Any]:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    context = await service.get_heartbeat_context(id)
    assert context is not None
    return context


@router.post(ISSUE_CHECKOUT_PATH)
async def checkout_issue_route(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
    body: dict[str, Any] = Body(...),
) -> IssueDetail:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    try:
        payload = validate_checkout_issue(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor = require_actor_identity(request)
    if actor.actor_type == "agent" and actor.actor_id != payload["agentId"]:
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Agent actor cannot checkout for another agent",
        )
    try:
        updated = await service.checkout_issue(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except IssueCheckoutConflictError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    await queue_issue_assignment_wakeup(
        heartbeat,
        updated,
        reason="issue_checked_out",
        mutation="checkout",
        context_source="issue.checkout",
        actor_type="agent" if actor.actor_type == "agent" else "user",
        actor_id=actor.actor_id,
    )
    return updated


@router.post(ISSUE_EXECUTE_PATH, response_model=None)
async def execute_issue_route(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> HeartbeatRun | JSONResponse:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    assignee_agent_id = detail.get("assigneeAgentId")
    if not assignee_agent_id:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Issue must be assigned to an agent before execution",
        )
    active = await heartbeat.get_active_for_issue(id)
    if active is not None:
        return active

    actor = require_actor_identity(request)
    payload: WakeAgentPayload = {
        "source": "assignment",
        "triggerDetail": "system",
        "reason": "issue_execute",
        "idempotencyKey": f"issue:{id}:execute",
        "payload": {"issueId": id, "mutation": "execute"},
        "contextSnapshot": {
            "issueId": id,
            "source": "issue.execute",
            "wakeSource": "assignment",
            "wakeReason": "issue_execute",
            "issue": {
                "id": id,
                "title": detail["title"],
                "description": detail.get("description"),
                "status": detail["status"],
                "priority": detail["priority"],
            },
        },
    }
    try:
        run = await heartbeat.wakeup(
            assignee_agent_id,
            payload,
            actor_type="agent" if actor.actor_type == "agent" else "user",
            actor_id=actor.actor_id,
            execute_immediately=False,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if run is None:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Issue assignee is not invokable",
        )
    enriched = await heartbeat.get(run["id"])
    assert enriched is not None
    if enriched["status"] == "queued":
        _schedule_dispatch(request, enriched["agentId"])
    return JSONResponse(enriched, status_code=http_status.HTTP_202_ACCEPTED)


@router.patch(ISSUE_DETAIL_PATH)
async def update_issue_route(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
    body: dict[str, Any] = Body(...),
) -> IssueDetail:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    try:
        payload = validate_update_issue(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    try:
        actor = require_actor_identity(request)
        if (
            actor.actor_type == "agent"
            and payload.get("status") == "done"
            and detail.get("assigneeAgentId") != actor.actor_id
        ):
            raise HTTPException(
                status_code=http_status.HTTP_403_FORBIDDEN,
                detail="Only the checkout owner can mark issue done",
            )
        updated = await service.update_issue(
            id,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            run_id=actor.run_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    status_changed_to_review = (
        detail["status"] != "in_review"
        and updated["status"] == "in_review"
        and "status" in payload
    )
    status_changed_to_blocked = (
        detail["status"] != "blocked"
        and updated["status"] == "blocked"
        and "status" in payload
    )
    status_changed_from_backlog = (
        detail["status"] == "backlog"
        and updated["status"] != "backlog"
        and "status" in payload
    )
    status_returned_from_review_to_assignee = (
        detail["status"] in {"in_review", "blocked"}
        and updated["status"] in {"in_progress", "todo"}
        and "status" in payload
    )
    reviewer_changed_in_reviewable = (
        (
            payload.get("reviewerAgentId") is not None
            and payload.get("reviewerAgentId") != detail.get("reviewerAgentId")
        )
        and detail["status"] in {"in_review", "blocked"}
        and updated["status"] in {"in_review", "blocked"}
    )
    if (
        status_changed_to_review
        or status_changed_to_blocked
        or reviewer_changed_in_reviewable
    ):
        mutation = (
            "status_to_in_review"
            if status_changed_to_review
            else "status_to_blocked"
            if status_changed_to_blocked
            else "reviewer_changed_blocked"
            if updated["status"] == "blocked"
            else "reviewer_changed_in_review"
        )
        await queue_issue_review_wakeup(
            heartbeat,
            updated,
            mutation=mutation,
            context_source=(
                "issue.status_change"
                if status_changed_to_review or status_changed_to_blocked
                else "issue.reviewer_change"
            ),
            actor_type="agent" if actor.actor_type == "agent" else "user",
            actor_id=actor.actor_id,
            actor_agent_id=actor.actor_id if actor.actor_type == "agent" else None,
        )
    if status_changed_from_backlog:
        await queue_issue_assignment_wakeup(
            heartbeat,
            updated,
            reason="issue_status_changed",
            mutation="update",
            context_source="issue.status_change",
            source="automation",
            wake_source="automation",
            actor_type="agent" if actor.actor_type == "agent" else "user",
            actor_id=actor.actor_id,
        )
    if status_returned_from_review_to_assignee:
        await queue_issue_assignment_wakeup(
            heartbeat,
            updated,
            reason="issue_changes_requested",
            mutation="review_changes_requested",
            context_source="issue.review_changes_requested",
            actor_type="agent" if actor.actor_type == "agent" else "user",
            actor_id=actor.actor_id,
        )
    return updated


@router.get(ISSUE_COMMENT_LIST_PATH)
async def list_issue_comments_route(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
) -> list[dict[str, Any]]:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    comments = await service.list_comments(id)
    return [
        {
            "id": comment.id,
            "issueId": comment.issue_id,
            "body": comment.body,
            "authorAgentId": comment.author_agent_id,
            "authorUserId": comment.author_user_id,
            "createdAt": comment.created_at.isoformat(),
            "updatedAt": comment.updated_at.isoformat(),
        }
        for comment in comments
    ]


@router.post(ISSUE_COMMENT_LIST_PATH)
async def create_issue_comment_route(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
    body: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    try:
        payload = validate_create_issue_comment(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    actor = require_actor_identity(request)
    comment = await service.add_comment(
        id,
        payload,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
        run_id=actor.run_id,
    )
    return {
        "id": comment.id,
        "issueId": comment.issue_id,
        "body": comment.body,
        "authorAgentId": comment.author_agent_id,
        "authorUserId": comment.author_user_id,
        "createdAt": comment.created_at.isoformat(),
        "updatedAt": comment.updated_at.isoformat(),
    }


@router.post(ISSUE_REVIEW_DECISION_PATH)
async def record_issue_review_decision_route(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
    body: dict[str, Any] = Body(...),
) -> IssueDetail:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    try:
        payload = validate_record_issue_review_decision(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    try:
        actor = require_actor_identity(request)
        updated = await service.update_issue(
            id,
            {"reviewDecision": payload},
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
            run_id=actor.run_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    return updated


@router.get(ISSUE_WORK_PRODUCTS_PATH)
async def list_issue_work_products_route(
    id: str,
    request: Request,
    issue_service: IssueService = Depends(get_issue_service),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> list[IssueWorkProduct]:
    detail = await issue_service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    return await workspace_service.list_work_products_for_issue(id)


@router.post(ISSUE_WORK_PRODUCTS_PATH, status_code=http_status.HTTP_201_CREATED)
async def create_issue_work_product_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    issue_service: IssueService = Depends(get_issue_service),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> IssueWorkProduct:
    detail = await issue_service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    try:
        payload = validate_create_issue_work_product(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return await workspace_service.create_work_product_for_issue(
        org_id=detail["orgId"],
        issue_id=id,
        project_id=detail.get("projectId"),
        payload=payload,
    )


@router.patch(WORK_PRODUCT_DETAIL_PATH)
async def update_work_product_route(
    id: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> IssueWorkProduct:
    existing = await workspace_service.get_work_product(id)
    if existing is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Work product not found",
        )
    assert_organization_access(request, existing["orgId"])
    try:
        payload = validate_update_issue_work_product(body)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    updated = await workspace_service.update_work_product(id, payload)
    if updated is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Work product not found",
        )
    return updated


@router.delete(WORK_PRODUCT_DETAIL_PATH)
async def delete_work_product_route(
    id: str,
    request: Request,
    workspace_service: WorkspaceService = Depends(get_workspace_service),
) -> IssueWorkProduct:
    existing = await workspace_service.get_work_product(id)
    if existing is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Work product not found",
        )
    assert_organization_access(request, existing["orgId"])
    removed = await workspace_service.delete_work_product(id)
    if removed is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Work product not found",
        )
    return removed


@router.get(ISSUE_DOCUMENTS_PATH)
async def list_issue_documents_route(
    id: str,
    request: Request,
    issue_service: IssueService = Depends(get_issue_service),
    document_service: DocumentService = Depends(get_document_service),
) -> list[IssueDocumentSummary]:
    detail = await issue_service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    return await document_service.list_issue_documents(id)


@router.get(ISSUE_DOCUMENT_DETAIL_PATH)
async def get_issue_document_route(
    id: str,
    key: str,
    request: Request,
    issue_service: IssueService = Depends(get_issue_service),
    document_service: DocumentService = Depends(get_document_service),
) -> IssueDocument:
    detail = await issue_service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    try:
        document_key = validate_issue_document_key(key)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    document = await document_service.get_issue_document_by_key(id, document_key)
    if document is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return document


@router.put(ISSUE_DOCUMENT_DETAIL_PATH)
async def upsert_issue_document_route(
    id: str,
    key: str,
    request: Request,
    body: dict[str, Any] = Body(...),
    issue_service: IssueService = Depends(get_issue_service),
    document_service: DocumentService = Depends(get_document_service),
) -> JSONResponse:
    detail = await issue_service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    try:
        document_key = validate_issue_document_key(key)
        payload = validate_upsert_issue_document(body)
        actor = require_actor_identity(request)
        document, created, _ = await document_service.upsert_issue_document(
            org_id=detail["orgId"],
            issue_id=id,
            key=document_key,
            payload=payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    return JSONResponse(
        status_code=http_status.HTTP_201_CREATED
        if created
        else http_status.HTTP_200_OK,
        content=document,
    )


@router.get(ISSUE_DOCUMENT_REVISIONS_PATH)
async def list_issue_document_revisions_route(
    id: str,
    key: str,
    request: Request,
    issue_service: IssueService = Depends(get_issue_service),
    document_service: DocumentService = Depends(get_document_service),
) -> list[DocumentRevision]:
    detail = await issue_service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    try:
        document_key = validate_issue_document_key(key)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return await document_service.list_issue_document_revisions(id, document_key)


@router.delete(ISSUE_DOCUMENT_DETAIL_PATH)
async def delete_issue_document_route(
    id: str,
    key: str,
    request: Request,
    _: None = Depends(require_board_access),
    issue_service: IssueService = Depends(get_issue_service),
    document_service: DocumentService = Depends(get_document_service),
) -> dict[str, bool]:
    detail = await issue_service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    try:
        document_key = validate_issue_document_key(key)
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    removed = await document_service.delete_issue_document(id, document_key)
    if removed is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )
    return {"ok": True}


@router.get(ISSUE_ATTACHMENTS_PATH)
async def list_issue_attachments_route(
    issueId: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
) -> list[IssueAttachment]:
    detail = await service.get_by_id(issueId)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    assert_organization_access(request, detail["orgId"])
    return await service.list_attachments(issueId)


@router.post(ORG_ISSUE_ATTACHMENTS_PATH, status_code=http_status.HTTP_201_CREATED)
async def create_issue_attachment_route(
    orgId: str,
    issueId: str,
    request: Request,
    _: None = Depends(require_organization_access),
    service: IssueService = Depends(get_issue_service),
) -> IssueAttachment:
    detail = await service.get_by_id(issueId)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Issue not found",
        )
    if detail["orgId"] != orgId:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Issue does not belong to organization",
        )
    try:
        payload = await _issue_attachment_payload_from_request(request, orgId)
        actor = require_actor_identity(request)
        return await service.create_attachment(
            issueId,
            payload,
            actor_type=actor.actor_type,
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc


@router.delete(ATTACHMENT_DETAIL_PATH, status_code=http_status.HTTP_204_NO_CONTENT)
async def delete_attachment_route(
    attachmentId: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
) -> Response:
    current = await service.get_attachment(attachmentId)
    if current is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )
    assert_organization_access(request, current["orgId"])
    actor = require_actor_identity(request)
    deleted = await service.delete_attachment(
        attachmentId,
        actor_type=actor.actor_type,
        actor_id=actor.actor_id,
    )
    if deleted is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Attachment not found",
        )
    attachment, asset, should_delete_asset = deleted
    if should_delete_asset:
        await _storage_for_request(request).delete_object(
            attachment["orgId"], asset.object_key
        )
    return Response(status_code=http_status.HTTP_204_NO_CONTENT)


async def _issue_attachment_payload_from_request(
    request: Request, org_id: str
) -> dict[str, Any]:
    form = await request.form()
    upload = form.get("file")
    if not isinstance(upload, StarletteUploadFile):
        raise ValueError("'file' is required")
    body = await upload.read()
    if not body:
        raise ValueError("'file' must not be empty")
    storage = _storage_for_request(request)
    stored = await storage.put_file(
        org_id=org_id,
        namespace="issue/attachments",
        original_filename=upload.filename,
        content_type=upload.content_type or "application/octet-stream",
        body=body,
    )
    usage = form.get("usage")
    issue_comment_id = form.get("issueCommentId")
    return {
        "provider": stored["provider"],
        "objectKey": stored["objectKey"],
        "contentType": stored["contentType"],
        "byteSize": stored["byteSize"],
        "sha256": stored["sha256"],
        "originalFilename": stored["originalFilename"],
        "usage": usage if isinstance(usage, str) and usage else "attachment",
        "issueCommentId": (
            issue_comment_id
            if isinstance(issue_comment_id, str) and issue_comment_id
            else None
        ),
    }


def _storage_for_request(request: Request) -> StorageService:
    storage = getattr(request.app.state, "storage_service", None)
    if storage is not None:
        return storage
    return get_storage_service()
