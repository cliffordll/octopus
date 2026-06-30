from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any, cast

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response
from fastapi import status as http_status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
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
    ISSUE_PASSIVE_FOLLOWUP_PATH,
    ISSUE_REVIEW_DECISION_PATH,
    ISSUE_WORK_PRODUCTS_PATH,
    ORG_ISSUE_LIST_PATH,
    WORK_PRODUCT_DETAIL_PATH,
)
from packages.shared.types.heartbeat import HeartbeatRun, WakeAgentPayload
from packages.shared.types.agent import Agent
from packages.shared.types.issue import (
    DocumentRevision,
    IssueDetail,
    IssueDocument,
    IssueDocumentSummary,
    IssueListItem,
    UpdateIssuePayload,
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
from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.heartbeat import get_wakeup_by_idempotency_key

from ..dependencies.access import (
    assert_organization_access,
    require_actor_identity,
    require_board_access,
    require_organization_access,
)
from ..dependencies.agents import get_agent_service
from ..dependencies.heartbeat import get_heartbeat_service
from ..dependencies.issues import get_issue_service
from ..dependencies.documents import get_document_service
from ..dependencies.database import get_session
from ..dependencies.workspaces import get_workspace_service
from ..services.heartbeat import HeartbeatService, dispatch_queued_agent
from ..services.issue_assignment_wakeup import queue_issue_assignment_wakeup
from ..services.issue_review_wakeup import queue_issue_review_wakeup
from ..services.agents import AgentService
from ..services.issues import IssueCheckoutConflictError, IssueService
from ..services.documents import DocumentService
from ..services.workspaces import WorkspaceService
from ..storage import StorageService, get_storage_service

router = APIRouter(tags=["issues"])
_MENTION_PATTERN = re.compile(r"@([A-Za-z0-9][A-Za-z0-9_.-]*)")


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


def _mentioned_tokens(body: str) -> set[str]:
    return {match.group(1).strip().lower() for match in _MENTION_PATTERN.finditer(body)}


def _issue_execute_unavailable_detail(wakeup: Any | None) -> str:
    if wakeup is None:
        return "Issue assignee is not invokable"
    if wakeup.status == "deferred_agent_paused":
        return (
            "Issue execution was deferred because the assignee agent is paused. "
            "Resume the agent to continue."
        )
    if wakeup.status == "deferred_issue_execution":
        return (
            "Issue execution was deferred because the issue already has an active "
            "execution run. It will continue after the active run finishes."
        )
    if wakeup.status == "skipped" and wakeup.error == "heartbeat.wakeOnDemand.disabled":
        return (
            "Issue execution was skipped because the assignee agent has on-demand "
            "wakeup disabled."
        )
    if wakeup.status == "skipped" and wakeup.error:
        return f"Issue execution was skipped: {wakeup.error}"
    return "Issue assignee is not invokable"


async def _mentioned_agents(
    agent_service: AgentService, org_id: str, body: str
) -> list[Agent]:
    tokens = _mentioned_tokens(body)
    if not tokens:
        return []
    agents = await agent_service.list_for_org(org_id)
    mentioned: list[Agent] = []
    for agent in agents:
        aliases = {
            value.lower()
            for value in (agent["id"], agent["name"], agent["urlKey"])
            if isinstance(value, str) and value
        }
        if tokens & aliases:
            mentioned.append(agent)
    return mentioned


async def _queue_issue_comment_mention_wakeup(
    heartbeat: HeartbeatService,
    issue: IssueDetail,
    *,
    mentioned_agent_id: str,
    comment_id: str,
    comment_body: str,
    actor_type: str,
    actor_id: str,
) -> None:
    payload: WakeAgentPayload = {
        "source": "on_demand",
        "triggerDetail": "system",
        "reason": "issue_comment_mentioned",
        "payload": {
            "issueId": issue["id"],
            "mutation": "comment_mention",
            "commentId": comment_id,
        },
        "contextSnapshot": {
            "issueId": issue["id"],
            "source": "issue.comment",
            "wakeSource": "mention",
            "wakeReason": "issue_comment_mentioned",
            "commentId": comment_id,
            "commentBody": comment_body,
            "issue": {
                "id": issue["id"],
                "title": issue["title"],
                "description": issue.get("description"),
                "status": issue["status"],
                "priority": issue["priority"],
            },
        },
    }
    await heartbeat.wakeup(
        mentioned_agent_id,
        payload,
        actor_type=actor_type,
        actor_id=actor_id,
        execute_immediately=False,
    )


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
    reviewer_agent_id = issue.get("reviewerAgentId")
    if (
        reviewer_agent_id
        and issue["status"] in {"in_review", "blocked"}
        and not (actor.actor_type == "agent" and actor.actor_id == reviewer_agent_id)
    ):
        _schedule_dispatch(request, reviewer_agent_id)
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
    assignee_agent_id = updated.get("assigneeAgentId")
    if assignee_agent_id and updated["status"] != "backlog":
        _schedule_dispatch(request, assignee_agent_id)
    return updated


@router.post(ISSUE_EXECUTE_PATH, response_model=None)
async def execute_issue_route(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
    session: AsyncSession = Depends(get_session),
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
    if detail["status"] in {"done", "cancelled"}:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail="Reopen the issue before execution",
        )
    active = await heartbeat.get_active_for_issue(id)
    if active is not None:
        return active

    actor = require_actor_identity(request)
    idempotency_key = f"issue:{id}:execute:{uuid.uuid4()}"
    payload: WakeAgentPayload = {
        "source": "assignment",
        "triggerDetail": "system",
        "reason": "issue_execute",
        "idempotencyKey": idempotency_key,
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
        wakeup = await get_wakeup_by_idempotency_key(
            session, assignee_agent_id, idempotency_key
        )
        if wakeup is not None:
            return JSONResponse(
                status_code=http_status.HTTP_202_ACCEPTED,
                content={
                    "status": wakeup.status,
                    "detail": _issue_execute_unavailable_detail(wakeup),
                },
            )
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=_issue_execute_unavailable_detail(wakeup),
        )
    enriched = await heartbeat.get(run["id"])
    assert enriched is not None
    await insert_activity_log(
        session,
        org_id=detail["orgId"],
        actor_type="agent" if actor.actor_type == "agent" else "user",
        actor_id=actor.actor_id,
        action="issue.executed",
        entity_type="issue",
        entity_id=id,
        agent_id=assignee_agent_id,
        run_id=enriched["id"],
        details={
            "agentId": assignee_agent_id,
            "runId": enriched["id"],
            "reason": "issue_execute",
            "status": enriched["status"],
        },
    )
    if enriched["status"] == "queued":
        _schedule_dispatch(request, enriched["agentId"])
    return JSONResponse(enriched, status_code=http_status.HTTP_202_ACCEPTED)


@router.post(ISSUE_PASSIVE_FOLLOWUP_PATH)
async def request_issue_passive_followup_route(
    id: str,
    request: Request,
    service: IssueService = Depends(get_issue_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
) -> JSONResponse:
    detail = await service.get_by_id(id)
    if detail is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Issue not found"
        )
    assert_organization_access(request, detail["orgId"])
    actor = require_actor_identity(request)
    try:
        run = await heartbeat.request_issue_passive_followup(
            id,
            actor_type="agent" if actor.actor_type == "agent" else "user",
            actor_id=actor.actor_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    if run is None:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND, detail="Issue not found"
        )
    if run["status"] == "queued":
        _schedule_dispatch(request, run["agentId"])
    return JSONResponse(run, status_code=http_status.HTTP_202_ACCEPTED)


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
        assignee_done_requested_review = (
            actor.actor_type == "agent"
            and payload.get("status") == "done"
            and detail.get("assigneeAgentId") == actor.actor_id
            and (
                bool(detail.get("reviewerUserId"))
                or (
                    bool(detail.get("reviewerAgentId"))
                    and detail.get("reviewerAgentId") != actor.actor_id
                )
            )
        )
        if assignee_done_requested_review:
            payload = cast(
                UpdateIssuePayload,
                {
                    **payload,
                    "status": "in_review",
                    "requestedStatus": "done",
                },
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
        actor.actor_type != "agent"
        and "status" in payload
        and updated["status"] in {"done", "blocked", "in_review"}
    ):
        await heartbeat.skip_scheduled_issue_passive_followups(
            id,
            reason="Issue status was manually closed after missing closeout",
        )
    if (
        status_changed_to_review
        or status_changed_to_blocked
        or reviewer_changed_in_reviewable
    ):
        mutation = (
            "assignee_done"
            if assignee_done_requested_review
            else "status_to_in_review"
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
                "issue.assignee_done"
                if assignee_done_requested_review
                else "issue.status_change"
                if status_changed_to_review or status_changed_to_blocked
                else "issue.reviewer_change"
            ),
            actor_type="agent" if actor.actor_type == "agent" else "user",
            actor_id=actor.actor_id,
            actor_agent_id=actor.actor_id if actor.actor_type == "agent" else None,
        )
        reviewer_agent_id = updated.get("reviewerAgentId")
        if reviewer_agent_id and not (
            actor.actor_type == "agent" and actor.actor_id == reviewer_agent_id
        ):
            _schedule_dispatch(request, reviewer_agent_id)
    if status_changed_from_backlog:
        await queue_issue_assignment_wakeup(
            heartbeat,
            updated,
            reason="issue_status_changed",
            mutation="update",
            context_source="issue.status_change",
            source="assignment",
            wake_source="assignment",
            actor_type="agent" if actor.actor_type == "agent" else "user",
            actor_id=actor.actor_id,
        )
        assignee_agent_id = updated.get("assigneeAgentId")
        if assignee_agent_id:
            _schedule_dispatch(request, assignee_agent_id)
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
        assignee_agent_id = updated.get("assigneeAgentId")
        if assignee_agent_id:
            _schedule_dispatch(request, assignee_agent_id)
    if detail["status"] != updated["status"] and updated["status"] in {
        "done",
        "cancelled",
        "blocked",
    }:
        parent_agent_id = await heartbeat.queue_parent_continuation_for_settled_child(
            id
        )
        if parent_agent_id:
            _schedule_dispatch(request, parent_agent_id)
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
    agent_service: AgentService = Depends(get_agent_service),
    heartbeat: HeartbeatService = Depends(get_heartbeat_service),
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
    user_intervention_stopped_followup = (
        actor.actor_type != "agent"
        and await heartbeat.skip_scheduled_issue_passive_followups(
            id,
            reason="Issue has user comment after missing closeout",
        )
    )
    mentioned_agents = await _mentioned_agents(
        agent_service, detail["orgId"], comment.body
    )
    mentioned_agent_ids = {mentioned["id"] for mentioned in mentioned_agents}
    assignee_agent_id = detail.get("assigneeAgentId")
    issue_status = detail.get("status")
    skip_assignee_comment_wakeup = issue_status in {"backlog", "done", "cancelled"}
    comment_targets_assignee = not mentioned_agent_ids or (
        assignee_agent_id is not None and assignee_agent_id in mentioned_agent_ids
    )
    queued_assignee_wakeup = not (
        user_intervention_stopped_followup
        or skip_assignee_comment_wakeup
        or not comment_targets_assignee
        or (actor.actor_type == "agent" and actor.actor_id == assignee_agent_id)
    )
    if queued_assignee_wakeup:
        await queue_issue_assignment_wakeup(
            heartbeat,
            detail,
            reason="issue_comment_added",
            mutation="comment",
            context_source="issue.comment",
            actor_type="agent" if actor.actor_type == "agent" else "user",
            actor_id=actor.actor_id,
            extra_payload={"commentId": comment.id},
            extra_context={"commentId": comment.id, "commentBody": comment.body},
        )
    for mentioned in mentioned_agents:
        mentioned_agent_id = mentioned["id"]
        if actor.actor_type == "agent" and actor.actor_id == mentioned_agent_id:
            continue
        if queued_assignee_wakeup and mentioned_agent_id == assignee_agent_id:
            continue
        await _queue_issue_comment_mention_wakeup(
            heartbeat,
            detail,
            mentioned_agent_id=mentioned_agent_id,
            comment_id=comment.id,
            comment_body=comment.body,
            actor_type="agent" if actor.actor_type == "agent" else "user",
            actor_id=actor.actor_id,
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
    await heartbeat.cancel_open_issue_review_wakeups(
        id,
        reason="review already resolved",
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
