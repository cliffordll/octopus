from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.approvals import (
    create_approval,
    create_approval_comment,
    get_approval_by_id,
    link_issues_to_approval,
    list_approval_comments,
    list_issues_for_approval,
    list_org_approvals,
    update_approval,
)
from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import (
    get_agent_by_id,
    update_agent as update_agent_row,
)
from packages.database.queries.issues import (
    get_issue_by_id,
    recover_blocked_linked_issues_for_approval,
)
from packages.database.schema import Approval
from packages.database.schema import ApprovalComment as ApprovalCommentRow
from packages.database.schema import Issue as IssueRow
from packages.shared.constants.approval import (
    ApprovalStatus,
    ApprovalType,
    DEFAULT_APPROVAL_STATUS,
)
from packages.shared.constants.issue import (
    IssueOriginKind,
    IssuePriority,
    IssueStatus,
)
from packages.shared.types.approval import (
    AddApprovalCommentPayload,
    ApprovalComment,
    ApprovalDetail,
    ApprovalListItem,
    CreateApprovalPayload,
    RequestApprovalRevisionPayload,
    ResolveApprovalPayload,
    ResubmitApprovalPayload,
)
from packages.shared.types.issue import IssueListItem

APPROVAL_CREATE_TO_COLUMN: dict[str, str] = {
    "type": "type",
    "payload": "payload",
    "requestedByAgentId": "requested_by_agent_id",
}

_RESOLVABLE_APPROVAL_STATUSES: frozenset[str] = frozenset(
    {"pending", "revision_requested"}
)


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self,
        org_id: str,
        *,
        status: str | None = None,
    ) -> list[ApprovalListItem]:
        rows = await list_org_approvals(self._session, org_id, status=status)
        return [_to_list_item(row) for row in rows]

    async def get_by_id(self, approval_id: str) -> ApprovalDetail | None:
        row = await get_approval_by_id(self._session, approval_id)
        if row is None:
            return None
        return _to_detail(row)

    async def create_approval(
        self,
        org_id: str,
        payload: CreateApprovalPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ApprovalDetail:
        issue_ids = list(dict.fromkeys(payload.get("issueIds", [])))
        for issue_id in issue_ids:
            issue = await get_issue_by_id(self._session, issue_id)
            if issue is None:
                raise ValueError("One or more issues not found")
            if issue.org_id != org_id:
                raise ValueError(
                    "Issue and approval must belong to the same organization"
                )

        values = {
            APPROVAL_CREATE_TO_COLUMN[key]: value
            for key, value in payload.items()
            if key in APPROVAL_CREATE_TO_COLUMN
        }
        values["org_id"] = org_id
        values.setdefault("status", DEFAULT_APPROVAL_STATUS)
        if actor_type == "agent":
            values.setdefault("requested_by_agent_id", actor_id)
        else:
            values["requested_by_user_id"] = actor_id
        row = await create_approval(self._session, values)
        if issue_ids:
            await link_issues_to_approval(
                self._session,
                org_id=org_id,
                approval_id=row.id,
                issue_ids=issue_ids,
                linked_by_agent_id=actor_id if actor_type == "agent" else None,
                linked_by_user_id=actor_id if actor_type != "agent" else None,
            )
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="approval.created",
            entity_type="approval",
            entity_id=row.id,
            details=dict(payload),
        )
        for issue_id in issue_ids:
            await insert_activity_log(
                self._session,
                org_id=org_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action="issue.approval_linked",
                entity_type="issue",
                entity_id=issue_id,
                details={"approvalId": row.id},
            )
        return _to_detail(row)

    async def approve_approval(
        self,
        approval_id: str,
        payload: ResolveApprovalPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ApprovalDetail | None:
        detail = await self._resolve_approval(
            approval_id,
            payload,
            status="approved",
            action="approval.approved",
            actor_type=actor_type,
            actor_id=actor_id,
        )
        if detail is None:
            return None

        recovered_issues = await recover_blocked_linked_issues_for_approval(
            self._session, approval_id
        )
        for issue in recovered_issues:
            has_assignee = (
                issue.assignee_agent_id is not None
                or issue.assignee_user_id is not None
            )
            if not has_assignee:
                continue
            await insert_activity_log(
                self._session,
                org_id=detail["orgId"],
                actor_type=actor_type,
                actor_id=actor_id,
                action="approval.linked_issue_assignee_wakeup_queued",
                entity_type="approval",
                entity_id=approval_id,
                details={"issueId": issue.id},
            )
        return detail

    async def reject_approval(
        self,
        approval_id: str,
        payload: ResolveApprovalPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ApprovalDetail | None:
        return await self._resolve_approval(
            approval_id,
            payload,
            status="rejected",
            action="approval.rejected",
            actor_type=actor_type,
            actor_id=actor_id,
        )

    async def request_revision(
        self,
        approval_id: str,
        payload: RequestApprovalRevisionPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ApprovalDetail | None:
        return await self._resolve_approval(
            approval_id,
            payload,
            status="revision_requested",
            action="approval.revision_requested",
            actor_type=actor_type,
            actor_id=actor_id,
        )

    async def resubmit_approval(
        self,
        approval_id: str,
        payload: ResubmitApprovalPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ApprovalDetail | None:
        current = await get_approval_by_id(self._session, approval_id)
        if current is None:
            return None
        if (
            current.requested_by_agent_id is not None
            and actor_id != current.requested_by_agent_id
        ):
            raise PermissionError(
                "Only the requesting agent can resubmit this approval"
            )

        values: dict[str, Any] = {
            "status": "pending",
            "decision_note": None,
            "decided_by_user_id": None,
            "decided_at": None,
        }
        if "payload" in payload:
            values["payload"] = payload["payload"]

        row = await update_approval(self._session, approval_id, values)
        if row is None:
            return None

        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="approval.resubmitted",
            entity_type="approval",
            entity_id=row.id,
            details=dict(payload),
        )
        return _to_detail(row)

    async def list_issues_for_approval(
        self, approval_id: str
    ) -> list[IssueListItem] | None:
        approval = await get_approval_by_id(self._session, approval_id)
        if approval is None:
            return None
        rows = await list_issues_for_approval(self._session, approval_id)
        return [_to_issue_list_item(row) for row in rows]

    async def list_comments(self, approval_id: str) -> list[ApprovalComment] | None:
        approval = await get_approval_by_id(self._session, approval_id)
        if approval is None:
            return None
        rows = await list_approval_comments(self._session, approval_id)
        return [_to_approval_comment(row) for row in rows]

    async def add_comment(
        self,
        approval_id: str,
        payload: AddApprovalCommentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> ApprovalComment | None:
        approval = await get_approval_by_id(self._session, approval_id)
        if approval is None:
            return None
        author_agent_id = actor_id if actor_type == "agent" else None
        author_user_id = actor_id if actor_type != "agent" else None
        row = await create_approval_comment(
            self._session,
            org_id=approval.org_id,
            approval_id=approval_id,
            body=payload["body"],
            author_agent_id=author_agent_id,
            author_user_id=author_user_id,
        )
        await insert_activity_log(
            self._session,
            org_id=approval.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="approval.comment_added",
            entity_type="approval",
            entity_id=approval_id,
            details={"commentId": row.id},
        )
        return _to_approval_comment(row)

    async def _resolve_approval(
        self,
        approval_id: str,
        payload: Mapping[str, Any],
        *,
        status: ApprovalStatus,
        action: str,
        actor_type: str,
        actor_id: str,
    ) -> ApprovalDetail | None:
        current = await get_approval_by_id(self._session, approval_id)
        if current is None:
            return None

        # Mirror upstream `services/approvals.ts:15,45-52`: only approvals in
        # the resolvable states may transition; same-status calls are
        # idempotent, different terminal states raise an explanatory error.
        if current.status not in _RESOLVABLE_APPROVAL_STATUSES:
            if current.status == status:
                return _to_detail(current)
            raise ValueError(
                f"Only pending or revision requested approvals can be {status}"
            )

        values = {"status": status}
        if "decisionNote" in payload:
            values["decision_note"] = payload["decisionNote"]
        if "decidedByUserId" in payload:
            values["decided_by_user_id"] = payload["decidedByUserId"]
        if "payload" in payload:
            values["payload"] = payload["payload"]

        row = await update_approval(self._session, approval_id, values)
        if row is None:
            return None

        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type="approval",
            entity_id=row.id,
            details=dict(payload),
        )
        await self._apply_hire_agent_decision(
            row,
            status=status,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        return _to_detail(row)

    async def _apply_hire_agent_decision(
        self,
        approval: Approval,
        *,
        status: ApprovalStatus,
        actor_type: str,
        actor_id: str,
    ) -> None:
        if approval.type != "hire_agent":
            return
        agent_id = approval.payload.get("agentId")
        if not isinstance(agent_id, str) or not agent_id:
            return
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None or agent.org_id != approval.org_id:
            return
        next_status: str | None = None
        action: str | None = None
        if status == "approved" and agent.status == "pending_approval":
            next_status = "idle"
            action = "agent.hire_approved"
        elif status == "rejected" and agent.status != "terminated":
            next_status = "terminated"
            action = "agent.hire_rejected"
        if next_status is None or action is None:
            return
        updated = await update_agent_row(
            self._session,
            agent_id,
            {"status": next_status, "pause_reason": None, "paused_at": None},
        )
        if updated is None:
            return
        await insert_activity_log(
            self._session,
            org_id=approval.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type="agent",
            entity_id=agent_id,
            details={"approvalId": approval.id},
        )


def _to_list_item(row: Approval) -> ApprovalListItem:
    return ApprovalListItem(
        id=row.id,
        orgId=row.org_id,
        type=cast(ApprovalType, row.type),
        status=cast(ApprovalStatus, row.status),
        requestedByAgentId=row.requested_by_agent_id,
        requestedByUserId=row.requested_by_user_id,
        createdAt=row.created_at.isoformat(),
    )


def _to_detail(row: Approval) -> ApprovalDetail:
    return ApprovalDetail(
        id=row.id,
        orgId=row.org_id,
        type=cast(ApprovalType, row.type),
        status=cast(ApprovalStatus, row.status),
        requestedByAgentId=row.requested_by_agent_id,
        requestedByUserId=row.requested_by_user_id,
        createdAt=row.created_at.isoformat(),
        payload=_redact_payload(row.payload),
        decisionNote=row.decision_note,
        decidedByUserId=row.decided_by_user_id,
        decidedAt=row.decided_at.isoformat() if row.decided_at else None,
        updatedAt=row.updated_at.isoformat(),
    )


def _to_approval_comment(row: ApprovalCommentRow) -> ApprovalComment:
    return ApprovalComment(
        id=row.id,
        orgId=row.org_id,
        approvalId=row.approval_id,
        authorAgentId=row.author_agent_id,
        authorUserId=row.author_user_id,
        body=row.body,
        createdAt=row.created_at.isoformat(),
        updatedAt=row.updated_at.isoformat(),
    )


def _to_issue_list_item(row: IssueRow) -> IssueListItem:
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
        createdByAgentId=row.created_by_agent_id,
        createdByUserId=row.created_by_user_id,
        originKind=cast(IssueOriginKind, row.origin_kind),
        originId=row.origin_id,
        updatedAt=row.updated_at.isoformat(),
    )


def _redact_payload(payload: dict[str, object]) -> dict[str, object]:
    return {key: _redact_value(key, value) for key, value in payload.items()}


def _redact_value(key: str, value: object) -> object:
    if _is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            nested_key: _redact_value(nested_key, nested_value)
            for nested_key, nested_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(key, item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "").replace("_", "").lower()
    return any(
        token in normalized
        for token in (
            "secret",
            "token",
            "password",
            "apikey",
            "accesskey",
            "privatekey",
            "credential",
        )
    )
