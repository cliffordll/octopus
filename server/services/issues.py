from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.issue_comments import (
    insert_issue_comment,
    list_issue_comments,
)
from packages.database.queries.issue_attachments import (
    create_issue_attachment,
    delete_issue_attachment,
    list_issue_attachments,
)
from packages.database.queries.issues import (
    create_issue,
    get_issue_by_id,
    list_org_issues,
    update_issue,
)
from packages.database.schema import Asset, Issue, IssueAttachment, IssueComment
from packages.shared.constants.issue import (
    IssueOriginKind,
    IssuePriority,
    IssueStatus,
)
from packages.shared.constants.issue import (
    DEFAULT_ISSUE_ORIGIN_KIND,
    DEFAULT_ISSUE_PRIORITY,
    DEFAULT_ISSUE_STATUS,
)
from packages.shared.types.issue import (
    CreateIssueCommentPayload,
    CreateIssuePayload,
    IssueDetail,
    IssueListItem,
    UpdateIssuePayload,
)
from packages.shared.types.issue_attachment import (
    IssueAttachment as IssueAttachmentType,
)
from .workspaces import WorkspaceService
from .goals import GoalService

_REVIEWABLE_STATUSES = {"in_review", "blocked"}
_REOPENABLE_STATUSES = {"done", "cancelled"}
_REVIEW_DECISION_STATUS_MAP = {
    "approve": "done",
    "request_changes": "in_progress",
    "blocked": "blocked",
}


def _apply_status_side_effects(values: dict[str, Any]) -> None:
    """Mirror upstream ``applyStatusSideEffects`` in ``issues.helpers.ts``.

    When ``status`` transitions to ``in_progress``/``done``/``cancelled`` and
    the caller did not supply a matching timestamp, stamp the current time so
    issue lifecycle markers stay in sync with the upstream contract.
    """

    status = values.get("status")
    if not status:
        return
    now = datetime.now(UTC)
    if status == "in_progress" and not values.get("started_at"):
        values["started_at"] = now
    if status == "done":
        values["completed_at"] = now
    if status == "cancelled":
        values["cancelled_at"] = now


ISSUE_CREATE_TO_COLUMN: dict[str, str] = {
    "title": "title",
    "description": "description",
    "status": "status",
    "priority": "priority",
    "projectId": "project_id",
    "goalId": "goal_id",
    "parentId": "parent_id",
    "assigneeAgentId": "assignee_agent_id",
    "assigneeUserId": "assignee_user_id",
    "reviewerAgentId": "reviewer_agent_id",
    "reviewerUserId": "reviewer_user_id",
    "originKind": "origin_kind",
    "originId": "origin_id",
    "requestDepth": "request_depth",
}

ISSUE_UPDATE_TO_COLUMN: dict[str, str] = {
    "title": "title",
    "description": "description",
    "status": "status",
    "priority": "priority",
    "projectId": "project_id",
    "goalId": "goal_id",
    "parentId": "parent_id",
    "assigneeAgentId": "assignee_agent_id",
    "assigneeUserId": "assignee_user_id",
    "reviewerAgentId": "reviewer_agent_id",
    "reviewerUserId": "reviewer_user_id",
    "hiddenAt": "hidden_at",
}


class IssueService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self,
        org_id: str,
        *,
        status: str | None = None,
        assignee_agent_id: str | None = None,
        project_id: str | None = None,
        goal_id: str | None = None,
        origin_kind: str | None = None,
        origin_id: str | None = None,
    ) -> list[IssueListItem]:
        rows = await list_org_issues(
            self._session,
            org_id,
            status=status,
            assignee_agent_id=assignee_agent_id,
            project_id=project_id,
            goal_id=goal_id,
            origin_kind=origin_kind,
            origin_id=origin_id,
        )
        return [_to_list_item(row) for row in rows]

    async def get_by_id(self, issue_id: str) -> IssueDetail | None:
        row = await get_issue_by_id(self._session, issue_id)
        if row is None:
            return None
        return await self._to_detail(row)

    async def list_comments(self, issue_id: str) -> list[IssueComment]:
        rows = await list_issue_comments(self._session, issue_id)
        return list(rows)

    async def list_attachments(self, issue_id: str) -> list[IssueAttachmentType]:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None:
            raise ValueError("Issue not found")
        rows = await list_issue_attachments(self._session, issue_id)
        return [_to_attachment(row, asset) for row, asset in rows]

    async def get_attachment(self, attachment_id: str) -> IssueAttachmentType | None:
        from packages.database.queries.issue_attachments import get_issue_attachment

        current = await get_issue_attachment(self._session, attachment_id)
        if current is None:
            return None
        attachment, asset = current
        return _to_attachment(attachment, asset)

    async def create_issue(
        self,
        org_id: str,
        payload: CreateIssuePayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> IssueDetail:
        values = {
            ISSUE_CREATE_TO_COLUMN[key]: value
            for key, value in payload.items()
            if key in ISSUE_CREATE_TO_COLUMN
        }
        values["org_id"] = org_id
        values.setdefault("status", DEFAULT_ISSUE_STATUS)
        values.setdefault("priority", DEFAULT_ISSUE_PRIORITY)
        values.setdefault("origin_kind", DEFAULT_ISSUE_ORIGIN_KIND)
        if not values.get("project_id") and not values.get("goal_id"):
            default_goal = await GoalService(
                self._session
            ).get_default_organization_goal(org_id)
            if default_goal is not None:
                values["goal_id"] = default_goal["id"]
        row = await create_issue(self._session, values)
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.created",
            entity_type="issue",
            entity_id=row.id,
            details=dict(payload),
        )
        return await self._to_detail(row)

    async def update_issue(
        self,
        issue_id: str,
        payload: UpdateIssuePayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> IssueDetail | None:
        current = await get_issue_by_id(self._session, issue_id)
        if current is None:
            return None

        values = {
            ISSUE_UPDATE_TO_COLUMN[key]: value
            for key, value in payload.items()
            if key in ISSUE_UPDATE_TO_COLUMN
        }
        next_project_id = payload.get("projectId", current.project_id)
        next_goal_id = payload.get("goalId", current.goal_id)
        if not next_project_id and not next_goal_id:
            default_goal = await GoalService(
                self._session
            ).get_default_organization_goal(current.org_id)
            next_goal_id = default_goal["id"] if default_goal is not None else None
        if next_goal_id != current.goal_id:
            values["goal_id"] = next_goal_id

        workflow_actions: list[tuple[str, Mapping[str, Any] | None]] = []
        review_decision = payload.get("reviewDecision")
        if review_decision is not None:
            if current.status not in _REVIEWABLE_STATUSES:
                raise ValueError(
                    "review decision is only allowed when issue status is in_review or blocked"
                )
            decision = review_decision["decision"]
            workflow_actions.append(
                ("issue.review_decision_recorded", dict(review_decision))
            )
            mapped_status = _REVIEW_DECISION_STATUS_MAP.get(decision)
            if mapped_status is not None:
                values["status"] = mapped_status
            elif decision == "needs_followup":
                workflow_actions.append(
                    ("issue.human_intervention_required", dict(review_decision))
                )

        if payload.get("reopen") and "status" not in values:
            if current.status in _REOPENABLE_STATUSES:
                values["status"] = "todo"

        _apply_status_side_effects(values)

        row = await update_issue(self._session, issue_id, values)
        if row is None:
            return None

        if values and review_decision is None:
            await insert_activity_log(
                self._session,
                org_id=row.org_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action="issue.updated",
                entity_type="issue",
                entity_id=row.id,
                details=dict(payload),
            )
        for action, details in workflow_actions:
            await insert_activity_log(
                self._session,
                org_id=row.org_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action=action,
                entity_type="issue",
                entity_id=row.id,
                details=dict(details) if details is not None else None,
            )
        return await self._to_detail(row)

    async def add_comment(
        self,
        issue_id: str,
        payload: CreateIssueCommentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> IssueComment:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None:
            raise ValueError("Issue not found")

        values: dict[str, Any] = {
            "org_id": issue.org_id,
            "issue_id": issue_id,
            "body": payload["body"],
        }
        if actor_type == "agent":
            values["author_agent_id"] = actor_id
        else:
            values["author_user_id"] = actor_id

        comment = await insert_issue_comment(self._session, values)
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.comment_added",
            entity_type="issue",
            entity_id=issue_id,
            details=dict(payload),
        )
        return comment

    async def create_attachment(
        self,
        issue_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> IssueAttachmentType:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None:
            raise ValueError("Issue not found")
        comment_id = payload.get("issueCommentId")
        if isinstance(comment_id, str) and comment_id:
            comment = await self._session.get(IssueComment, comment_id)
            if comment is None or comment.issue_id != issue.id:
                raise ValueError("Issue comment not found")
        attachment, asset = await create_issue_attachment(
            self._session,
            asset_fields={
                "org_id": issue.org_id,
                "provider": payload["provider"],
                "object_key": payload["objectKey"],
                "content_type": payload["contentType"],
                "byte_size": payload["byteSize"],
                "sha256": payload["sha256"],
                "original_filename": payload.get("originalFilename"),
                "created_by_agent_id": actor_id if actor_type == "agent" else None,
                "created_by_user_id": actor_id if actor_type != "agent" else None,
            },
            attachment_fields={
                "org_id": issue.org_id,
                "issue_id": issue.id,
                "issue_comment_id": comment_id,
                "usage": payload.get("usage", "attachment"),
            },
        )
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.attachment_added",
            entity_type="issue",
            entity_id=issue.id,
            details={
                "attachmentId": attachment.id,
                "issueCommentId": comment_id,
                "originalFilename": asset.original_filename,
                "contentType": asset.content_type,
            },
        )
        return _to_attachment(attachment, asset)

    async def delete_attachment(
        self,
        attachment_id: str,
        *,
        actor_type: str,
        actor_id: str,
    ) -> tuple[IssueAttachmentType, Asset, bool] | None:
        deleted = await delete_issue_attachment(self._session, attachment_id)
        if deleted is None:
            return None
        attachment, asset, should_delete_asset = deleted
        await insert_activity_log(
            self._session,
            org_id=attachment.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.attachment_deleted",
            entity_type="issue",
            entity_id=attachment.issue_id,
            details={"attachmentId": attachment.id, "assetId": asset.id},
        )
        return _to_attachment(attachment, asset), asset, should_delete_asset

    async def _to_detail(self, row: Issue) -> IssueDetail:
        detail = _to_detail(row)
        detail["workProducts"] = await WorkspaceService(
            self._session
        ).list_work_products_for_issue(row.id)
        return detail


def _to_list_item(row: Issue) -> IssueListItem:
    return IssueListItem(
        id=row.id,
        orgId=row.org_id,
        identifier=row.identifier,
        title=row.title,
        status=cast(IssueStatus, row.status),
        priority=cast(IssuePriority, row.priority),
        projectId=row.project_id,
        goalId=row.goal_id,
        assigneeAgentId=row.assignee_agent_id,
        assigneeUserId=row.assignee_user_id,
        originKind=cast(IssueOriginKind, row.origin_kind),
        originId=row.origin_id,
        updatedAt=row.updated_at.isoformat(),
    )


def _to_detail(row: Issue) -> IssueDetail:
    return IssueDetail(
        id=row.id,
        orgId=row.org_id,
        identifier=row.identifier,
        title=row.title,
        status=cast(IssueStatus, row.status),
        priority=cast(IssuePriority, row.priority),
        assigneeAgentId=row.assignee_agent_id,
        assigneeUserId=row.assignee_user_id,
        updatedAt=row.updated_at.isoformat(),
        description=row.description,
        reviewerAgentId=row.reviewer_agent_id,
        reviewerUserId=row.reviewer_user_id,
        projectId=row.project_id,
        goalId=row.goal_id,
        parentId=row.parent_id,
        originKind=cast(IssueOriginKind, row.origin_kind),
        originId=row.origin_id,
        issueNumber=row.issue_number,
        requestDepth=row.request_depth,
        startedAt=row.started_at.isoformat() if row.started_at else None,
        completedAt=row.completed_at.isoformat() if row.completed_at else None,
        cancelledAt=row.cancelled_at.isoformat() if row.cancelled_at else None,
        createdAt=row.created_at.isoformat(),
        workProducts=[],
    )


def _to_attachment(row: IssueAttachment, asset: Asset) -> IssueAttachmentType:
    return {
        "id": row.id,
        "orgId": row.org_id,
        "issueId": row.issue_id,
        "issueCommentId": row.issue_comment_id,
        "assetId": row.asset_id,
        "usage": row.usage,
        "provider": asset.provider,
        "objectKey": asset.object_key,
        "contentType": asset.content_type,
        "byteSize": asset.byte_size,
        "sha256": asset.sha256,
        "originalFilename": asset.original_filename,
        "createdAt": row.created_at.isoformat(),
        "updatedAt": row.updated_at.isoformat(),
        "contentPath": f"/api/assets/{row.asset_id}/content",
    }
