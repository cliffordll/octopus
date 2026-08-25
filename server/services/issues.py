from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.issue_comments import (
    insert_issue_comment_idempotent,
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
from packages.database.queries.organizations import increment_issue_counter
from packages.database.schema import (
    ActivityLog,
    Agent,
    Asset,
    Issue,
    IssueAttachment,
    IssueComment,
)
from packages.shared.constants.issue import (
    DEFAULT_DELEGATION_CLOSEOUT_MODE,
    DelegationCloseoutMode,
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
    CreateChildIssuesPayload,
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
from .delegation_closeout import DELEGATION_ORIGIN_KIND, DelegationBatchStore
from .documents import DocumentService
from .goals import GoalService

_REVIEWABLE_STATUSES = {"in_review", "blocked"}
_REOPENABLE_STATUSES = {"done", "cancelled"}
_REVIEW_DECISION_STATUS_MAP = {
    "approve": "done",
    "request_changes": "in_progress",
    "blocked": "blocked",
}


def _require_reviewer_for_in_review(values: Mapping[str, Any]) -> None:
    if values.get("status") != "in_review":
        return
    if values.get("reviewer_agent_id") or values.get("reviewer_user_id"):
        return
    raise ValueError("in_review requires reviewerAgentId or reviewerUserId")


def _require_distinct_assignee_and_reviewer(values: Mapping[str, Any]) -> None:
    assignee_agent_id = values.get("assignee_agent_id")
    reviewer_agent_id = values.get("reviewer_agent_id")
    if (
        assignee_agent_id
        and reviewer_agent_id
        and assignee_agent_id == reviewer_agent_id
    ):
        raise ValueError("reviewerAgentId must differ from assigneeAgentId")


def _reject_agent_self_delegated_child_issue(
    values: Mapping[str, Any], *, actor_type: str, actor_id: str
) -> None:
    if (
        actor_type == "agent"
        and values.get("parent_id") is not None
        and values.get("assignee_agent_id") == actor_id
    ):
        raise ValueError(
            "Agent cannot delegate a child issue to itself. Do the work in the "
            "parent issue without creating a child issue, or assign the child "
            "issue to a different agent."
        )


class IssueCheckoutConflictError(RuntimeError):
    pass


def _apply_status_side_effects(
    values: dict[str, Any], *, previous_status: str | None = None
) -> None:
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
    elif previous_status == "done":
        values["completed_at"] = None
    if status == "cancelled":
        values["cancelled_at"] = now
    elif previous_status == "cancelled":
        values["cancelled_at"] = None


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
    "createdByAgentId": "created_by_agent_id",
    "createdByUserId": "created_by_user_id",
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
        parent_id: str | None = None,
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
            parent_id=parent_id,
            origin_kind=origin_kind,
            origin_id=origin_id,
        )
        return [_to_list_item(row) for row in rows]

    async def get_by_id(self, issue_id: str) -> IssueDetail | None:
        row = await get_issue_by_id(self._session, issue_id)
        if row is None:
            return None
        return await self._to_detail(row)

    async def get_child_outputs(
        self,
        issue_id: str,
        *,
        include_work_products: bool = False,
        delegation_origin_run_id: str | None = None,
    ) -> dict[str, Any] | None:
        parent = await get_issue_by_id(self._session, issue_id)
        if parent is None:
            return None
        criteria = [
            Issue.org_id == parent.org_id,
            Issue.parent_id == parent.id,
            Issue.hidden_at.is_(None),
        ]
        if delegation_origin_run_id is not None:
            criteria.extend(
                (
                    Issue.origin_kind == DELEGATION_ORIGIN_KIND,
                    Issue.origin_run_id == delegation_origin_run_id,
                )
            )
        children = (
            (
                await self._session.execute(
                    select(Issue).where(*criteria).order_by(Issue.created_at, Issue.id)
                )
            )
            .scalars()
            .all()
        )
        workspace = WorkspaceService(self._session)
        child_items: list[dict[str, Any]] = []
        active_statuses = {"backlog", "todo", "in_progress", "in_review"}
        terminal_statuses = {"done", "blocked", "cancelled"}
        for child in children:
            item: dict[str, Any] = dict(_to_list_item(child))
            item.update(
                {
                    "parentId": child.parent_id,
                    "originRunId": child.origin_run_id,
                    "closeoutMode": child.closeout_mode,
                    "assigneeUserId": child.assignee_user_id,
                    "reviewerAgentId": child.reviewer_agent_id,
                    "reviewerUserId": child.reviewer_user_id,
                    "startedAt": child.started_at.isoformat()
                    if child.started_at
                    else None,
                    "completedAt": child.completed_at.isoformat()
                    if child.completed_at
                    else None,
                    "cancelledAt": child.cancelled_at.isoformat()
                    if child.cancelled_at
                    else None,
                    "lastCloseout": await self._latest_child_closeout(child),
                }
            )
            if include_work_products:
                item["workProducts"] = await workspace.list_work_products_for_issue(
                    child.id
                )
            child_items.append(item)
        active_count = sum(1 for child in children if child.status in active_statuses)
        settled_count = sum(
            1 for child in children if child.status in terminal_statuses
        )
        blocked_count = sum(
            1 for child in children if child.status in {"blocked", "cancelled"}
        )
        return {
            "parent": dict(_to_list_item(parent)),
            "children": child_items,
            "activeChildCount": active_count,
            "settledChildCount": settled_count,
            "blockedChildCount": blocked_count,
            "totalChildCount": len(children),
            "parentExecutionStage": _parent_execution_stage(
                child_items, parent_status=parent.status
            ),
            "includeWorkProducts": include_work_products,
            "delegationOriginRunId": delegation_origin_run_id,
            "closeoutMode": (children[0].closeout_mode if children else None),
        }

    async def create_child_issues(
        self,
        parent_issue_id: str,
        payload: CreateChildIssuesPayload,
        *,
        actor_type: str,
        actor_id: str,
        run_id: str | None = None,
    ) -> tuple[IssueDetail, list[IssueDetail], bool]:
        # Take a write lock before reading the child set. PostgreSQL/MySQL lock the
        # parent row; SQLite begins its single-writer transaction here instead of
        # relying on its no-op ``FOR UPDATE`` implementation.
        locked_parent_id = (
            await self._session.execute(
                update(Issue)
                .where(Issue.id == parent_issue_id)
                .values(updated_at=Issue.updated_at)
                .returning(Issue.id)
            )
        ).scalar_one_or_none()
        if locked_parent_id is None:
            locked_parent_id = (
                await self._session.execute(
                    update(Issue)
                    .where(Issue.identifier == parent_issue_id)
                    .values(updated_at=Issue.updated_at)
                    .returning(Issue.id)
                )
            ).scalar_one_or_none()
        parent = (
            await self._session.get(Issue, locked_parent_id)
            if locked_parent_id is not None
            else None
        )
        if parent is None:
            raise ValueError("Parent issue not found")

        existing_batch = await DelegationBatchStore(
            self._session
        ).existing_for_creation(parent, origin_run_id=run_id)
        if existing_batch is not None:
            return (
                await self._to_detail(parent),
                [await self._to_detail(child) for child in existing_batch.children],
                False,
            )

        if parent.status in {"done", "cancelled"}:
            raise ValueError("Closed parent issue cannot create child issues")

        agent_ids: set[str] = set()
        for child in payload["children"]:
            assignee_agent_id = child.get("assigneeAgentId")
            reviewer_agent_id = child.get("reviewerAgentId")
            if isinstance(assignee_agent_id, str):
                agent_ids.add(assignee_agent_id)
            if isinstance(reviewer_agent_id, str):
                agent_ids.add(reviewer_agent_id)
        referenced_agents = (
            (await self._session.execute(select(Agent).where(Agent.id.in_(agent_ids))))
            .scalars()
            .all()
        )
        agents_by_id = {agent.id: agent for agent in referenced_agents}
        invalid_agent_ids = sorted(
            agent_id
            for agent_id in agent_ids
            if agent_id not in agents_by_id
            or agents_by_id[agent_id].org_id != parent.org_id
        )
        if invalid_agent_ids:
            raise ValueError(
                "Child agents must exist in the parent organization: "
                + ", ".join(invalid_agent_ids)
            )

        children: list[IssueDetail] = []
        closeout_mode = payload.get("closeoutMode", DEFAULT_DELEGATION_CLOSEOUT_MODE)
        for child in payload["children"]:
            child_payload: CreateIssuePayload = {
                **child,
                "parentId": parent.id,
                "status": "todo",
            }
            children.append(
                await self.create_issue(
                    parent.org_id,
                    child_payload,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    run_id=run_id,
                    origin_run_id=run_id,
                    closeout_mode=closeout_mode,
                    origin_kind=DELEGATION_ORIGIN_KIND,
                )
            )

        await insert_activity_log(
            self._session,
            org_id=parent.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.children_created",
            entity_type="issue",
            entity_id=parent.id,
            run_id=run_id,
            details={
                "childIssueIds": [child["id"] for child in children],
                "childCount": len(children),
                "mode": "atomic_batch",
                "originRunId": run_id,
                "closeoutMode": closeout_mode,
            },
        )
        return await self._to_detail(parent), children, True

    async def commit_child_issues(self) -> None:
        """Commit a completed child batch before its dispatch tasks are scheduled."""

        await self._session.commit()

    async def end_child_batch_preflight(self) -> None:
        """End the access-check read transaction before taking the batch write lock."""

        await self._session.rollback()

    async def _latest_child_closeout(self, child: Issue) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(ActivityLog)
            .where(
                ActivityLog.org_id == child.org_id,
                ActivityLog.entity_type == "issue",
                ActivityLog.entity_id == child.id,
                ActivityLog.action.in_(
                    (
                        "issue.updated",
                        "issue.comment_added",
                        "issue.review_decision_recorded",
                        "issue.review_closeout_missing",
                        "issue.closure_needs_operator_review",
                    )
                ),
            )
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return {
            "id": row.id,
            "action": row.action,
            "runId": row.run_id,
            "details": row.details,
            "createdAt": row.created_at.isoformat(),
        }

    async def list_comments(self, issue_id: str) -> list[IssueComment]:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None:
            return []
        rows = await list_issue_comments(self._session, issue.id)
        return list(rows)

    async def list_attachments(self, issue_id: str) -> list[IssueAttachmentType]:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None:
            raise ValueError("Issue not found")
        rows = await list_issue_attachments(self._session, issue.id)
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
        run_id: str | None = None,
        origin_run_id: str | None = None,
        closeout_mode: DelegationCloseoutMode | None = None,
        origin_kind: IssueOriginKind | None = None,
    ) -> IssueDetail:
        values = {
            ISSUE_CREATE_TO_COLUMN[key]: value
            for key, value in payload.items()
            if key in ISSUE_CREATE_TO_COLUMN
        }
        values["org_id"] = org_id
        if origin_run_id is not None:
            values["origin_run_id"] = origin_run_id
        if closeout_mode is not None:
            values["closeout_mode"] = closeout_mode
        if origin_kind is not None:
            values["origin_kind"] = origin_kind
        values.setdefault("status", DEFAULT_ISSUE_STATUS)
        values.setdefault("priority", DEFAULT_ISSUE_PRIORITY)
        values.setdefault("origin_kind", DEFAULT_ISSUE_ORIGIN_KIND)
        _require_reviewer_for_in_review(values)
        parent = await self._apply_parent_values(
            org_id,
            values,
            issue_id=None,
            explicit_parent="parent_id" in values,
        )
        if parent is not None:
            self._inherit_parent_scope(values, parent)
        _reject_agent_self_delegated_child_issue(
            values, actor_type=actor_type, actor_id=actor_id
        )
        if parent is not None:
            existing = await self._find_existing_agent_child_issue(
                values, actor_type=actor_type
            )
            if existing is not None:
                return await self._to_detail(existing)
        if (
            actor_type == "agent"
            and values.get("created_by_agent_id") == actor_id
            and "assignee_agent_id" not in values
            and "assignee_user_id" not in values
        ):
            values["assignee_agent_id"] = actor_id
        _require_distinct_assignee_and_reviewer(values)
        if not values.get("project_id") and not values.get("goal_id"):
            default_goal = await GoalService(
                self._session
            ).get_default_organization_goal(org_id)
            if default_goal is not None:
                values["goal_id"] = default_goal["id"]
        counter = await increment_issue_counter(self._session, org_id)
        if counter is None:
            raise ValueError("Organization not found")
        issue_number, issue_prefix = counter
        values["issue_number"] = issue_number
        values["identifier"] = f"{issue_prefix}-{issue_number}"
        _apply_status_side_effects(values)
        row = await create_issue(self._session, values)
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.created",
            entity_type="issue",
            entity_id=row.id,
            run_id=run_id,
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
        run_id: str | None = None,
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
        await self._apply_parent_values(
            current.org_id,
            values,
            issue_id=current.id,
            explicit_parent="parentId" in payload,
        )

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

        effective_values = {
            "status": values.get("status", current.status),
            "assignee_agent_id": values.get(
                "assignee_agent_id", current.assignee_agent_id
            ),
            "reviewer_agent_id": values.get(
                "reviewer_agent_id", current.reviewer_agent_id
            ),
            "reviewer_user_id": values.get(
                "reviewer_user_id", current.reviewer_user_id
            ),
        }
        _require_reviewer_for_in_review(effective_values)
        if "assignee_agent_id" in values or "reviewer_agent_id" in values:
            _require_distinct_assignee_and_reviewer(effective_values)
        _apply_status_side_effects(values, previous_status=current.status)

        row = await update_issue(self._session, issue_id, values)
        if row is None:
            return None
        if "parent_id" in values:
            await self._refresh_descendant_depths(row)
        if values.get("status") == "done":
            await self._reject_done_with_open_descendants(row)

        if values and review_decision is None:
            await insert_activity_log(
                self._session,
                org_id=row.org_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action="issue.updated",
                entity_type="issue",
                entity_id=row.id,
                run_id=run_id,
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
                run_id=run_id,
                details=dict(details) if details is not None else None,
            )
        return await self._to_detail(row)

    async def _accepted_incomplete_child_ids(self, parent: Issue) -> set[str]:
        rows = (
            (
                await self._session.execute(
                    select(ActivityLog.details).where(
                        and_(
                            ActivityLog.org_id == parent.org_id,
                            ActivityLog.entity_type == "issue",
                            ActivityLog.entity_id == parent.id,
                            ActivityLog.action == "issue.incomplete_accepted",
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        accepted: set[str] = set()
        for details in rows:
            if not isinstance(details, dict):
                continue
            child_issue_id = details.get("childIssueId")
            if isinstance(child_issue_id, str) and child_issue_id:
                accepted.add(child_issue_id)
            child_issue_ids = details.get("childIssueIds")
            if isinstance(child_issue_ids, list):
                accepted.update(
                    child_id
                    for child_id in child_issue_ids
                    if isinstance(child_id, str) and child_id
                )
        return accepted

    async def _reject_done_with_open_descendants(self, parent: Issue) -> None:
        rows = (
            (
                await self._session.execute(
                    select(Issue).where(Issue.org_id == parent.org_id)
                )
            )
            .scalars()
            .all()
        )
        children_by_parent: dict[str, list[Issue]] = {}
        for row in rows:
            if row.parent_id is not None:
                children_by_parent.setdefault(row.parent_id, []).append(row)

        accepted_child_ids = await self._accepted_incomplete_child_ids(parent)
        stack = list(children_by_parent.get(parent.id, []))
        while stack:
            child = stack.pop()
            stack.extend(children_by_parent.get(child.id, []))
            if child.status == "done":
                continue
            if child.status in {"blocked", "cancelled"}:
                if child.id in accepted_child_ids:
                    continue
                raise ValueError(
                    "Cannot mark issue done while child issues are blocked or cancelled. "
                    f"Retry, replace, or explicitly resolve child issue {child.identifier or child.id} first."
                )
            raise ValueError(
                "Cannot mark issue done while child issues are still open. "
                f"Complete child issue {child.identifier or child.id} first."
            )

    async def _apply_parent_values(
        self,
        org_id: str,
        values: dict[str, Any],
        *,
        issue_id: str | None,
        explicit_parent: bool,
    ) -> Issue | None:
        if not explicit_parent:
            return None
        parent_id = values.get("parent_id")
        if parent_id is None:
            values["request_depth"] = 0
            return None
        if issue_id is not None and parent_id == issue_id:
            raise ValueError("Issue cannot be its own parent")
        parent = await get_issue_by_id(self._session, parent_id)
        if parent is None or parent.org_id != org_id:
            raise ValueError("Parent issue not found")
        if issue_id is not None:
            await self._assert_parent_does_not_cycle(issue_id, parent_id, org_id)
        values["request_depth"] = parent.request_depth + 1
        return parent

    @staticmethod
    def _inherit_parent_scope(values: dict[str, Any], parent: Issue) -> None:
        inherited_fields = {
            "project_id": parent.project_id,
            "goal_id": parent.goal_id,
            "project_workspace_id": parent.project_workspace_id,
            "execution_workspace_preference": parent.execution_workspace_preference,
            "execution_workspace_settings": parent.execution_workspace_settings,
        }
        if not IssueService._parent_workspace_is_issue_scoped(parent):
            inherited_fields["execution_workspace_id"] = parent.execution_workspace_id
        for field, value in inherited_fields.items():
            if values.get(field) is None and value is not None:
                values[field] = value

    @staticmethod
    def _parent_workspace_is_issue_scoped(parent: Issue) -> bool:
        if parent.execution_workspace_preference in {
            "isolated_workspace",
            "operator_branch",
        }:
            return True
        settings = parent.execution_workspace_settings
        if not isinstance(settings, Mapping):
            return False
        mode = settings.get("mode")
        if mode == "isolated":
            mode = "isolated_workspace"
        return mode in {"isolated_workspace", "operator_branch"}

    async def _find_existing_agent_child_issue(
        self, values: Mapping[str, Any], *, actor_type: str
    ) -> Issue | None:
        parent_id = values.get("parent_id")
        title = values.get("title")
        if actor_type != "agent" or not parent_id or not isinstance(title, str):
            return None
        criteria = [
            Issue.org_id == values["org_id"],
            Issue.parent_id == parent_id,
            Issue.title == title,
            Issue.hidden_at.is_(None),
        ]
        if values.get("origin_kind") == DELEGATION_ORIGIN_KIND:
            criteria.extend(
                (
                    Issue.origin_kind == DELEGATION_ORIGIN_KIND,
                    Issue.origin_run_id == values.get("origin_run_id"),
                )
            )
        result = await self._session.execute(
            select(Issue).where(*criteria).order_by(Issue.created_at, Issue.id).limit(1)
        )
        return result.scalar_one_or_none()

    async def _assert_parent_does_not_cycle(
        self, issue_id: str, parent_id: str, org_id: str
    ) -> None:
        rows = (
            (await self._session.execute(select(Issue).where(Issue.org_id == org_id)))
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        cursor: str | None = parent_id
        while cursor is not None:
            if cursor == issue_id:
                raise ValueError("Issue parent cycle is not allowed")
            parent = by_id.get(cursor)
            cursor = parent.parent_id if parent is not None else None

    async def _refresh_descendant_depths(self, root: Issue) -> None:
        rows = (
            (
                await self._session.execute(
                    select(Issue).where(Issue.org_id == root.org_id)
                )
            )
            .scalars()
            .all()
        )
        children_by_parent: dict[str, list[Issue]] = {}
        for row in rows:
            if row.parent_id is not None:
                children_by_parent.setdefault(row.parent_id, []).append(row)

        stack = [
            (child, root.request_depth + 1)
            for child in children_by_parent.get(root.id, [])
        ]
        now = datetime.now(UTC)
        while stack:
            row, depth = stack.pop()
            row.request_depth = depth
            row.updated_at = now
            stack.extend(
                (child, depth + 1) for child in children_by_parent.get(row.id, [])
            )
        await self._session.flush()

    async def checkout_issue(
        self,
        issue_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
        checkout_run_id: str | None = None,
    ) -> IssueDetail | None:
        current = await get_issue_by_id(self._session, issue_id)
        if current is None:
            return None

        agent_id = cast(str, payload["agentId"])
        expected_statuses = cast(list[str], payload["expectedStatuses"])
        now = datetime.now(UTC)
        assignee_matches = or_(
            Issue.assignee_agent_id.is_(None),
            Issue.assignee_agent_id == agent_id,
        )
        if checkout_run_id is None:
            run_lock_matches = and_(
                Issue.checkout_run_id.is_(None),
                Issue.execution_run_id.is_(None),
            )
        else:
            run_lock_matches = and_(
                or_(
                    Issue.checkout_run_id.is_(None),
                    Issue.checkout_run_id == checkout_run_id,
                ),
                or_(
                    Issue.execution_run_id.is_(None),
                    Issue.execution_run_id == checkout_run_id,
                ),
            )
        result = await self._session.execute(
            update(Issue)
            .where(
                Issue.id == current.id,
                Issue.status.in_(expected_statuses),
                assignee_matches,
                run_lock_matches,
            )
            .values(
                assignee_agent_id=agent_id,
                assignee_user_id=None,
                checkout_run_id=checkout_run_id,
                execution_run_id=checkout_run_id,
                status="in_progress",
                started_at=now,
                updated_at=now,
            )
            .returning(Issue)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise IssueCheckoutConflictError("Issue checkout conflict")

        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.checked_out",
            entity_type="issue",
            entity_id=row.id,
            details={
                "agentId": agent_id,
                "expectedStatuses": expected_statuses,
                "checkoutRunId": checkout_run_id,
            },
        )
        return await self._to_detail(row)

    async def get_heartbeat_context(
        self,
        issue_id: str,
        *,
        delegation_origin_run_id: str | None = None,
    ) -> dict[str, Any] | None:
        detail = await self.get_by_id(issue_id)
        if detail is None:
            return None
        documents = DocumentService(self._session)
        document_summaries = await documents.list_issue_documents(issue_id)
        plan_document = await documents.get_issue_document_by_key(issue_id, "plan")
        issue_documents_prompt = _build_issue_documents_prompt(
            plan_document=plan_document,
            document_summaries=document_summaries,
        )
        aggregated_work_products = await WorkspaceService(
            self._session
        ).list_work_products_for_issue(issue_id, include_child_primary=True)
        child_primary_work_products = _child_primary_work_products(
            aggregated_work_products
        )
        child_outputs = await self.get_child_outputs(
            issue_id,
            include_work_products=True,
            delegation_origin_run_id=delegation_origin_run_id,
        )
        closeout_mode = child_outputs.get("closeoutMode") if child_outputs else None
        if delegation_origin_run_id is not None and child_outputs is not None:
            batch_child_ids = {
                str(child.get("id")) for child in child_outputs.get("children", [])
            }
            child_primary_work_products = [
                product
                for product in child_primary_work_products
                if str(product.get("sourceIssueId")) in batch_child_ids
            ]
        child_work_products_prompt = _build_child_work_products_prompt(
            child_primary_work_products,
            closeout_mode=closeout_mode,
        )
        blocked_child_issues = _blocked_child_issues(
            child_outputs.get("children", []) if child_outputs else []
        )
        issue = {
            "id": detail["id"],
            "identifier": detail["identifier"],
            "title": detail["title"],
            "description": detail["description"],
            "status": detail["status"],
            "priority": detail["priority"],
            "projectId": detail["projectId"],
            "goalId": detail["goalId"],
            "parentId": detail["parentId"],
            "assigneeAgentId": detail["assigneeAgentId"],
            "assigneeUserId": detail["assigneeUserId"],
            "updatedAt": detail["updatedAt"],
        }
        return {
            "issue": issue,
            "ancestors": [],
            "project": None,
            "goal": None,
            "commentCursor": None,
            "documentSummaries": document_summaries,
            "planDocument": plan_document,
            "legacyPlanDocument": None,
            "issueDocumentsPrompt": issue_documents_prompt,
            "childPrimaryWorkProducts": child_primary_work_products,
            "childWorkProductsPrompt": child_work_products_prompt,
            "childOutputs": child_outputs,
            "childIssues": child_outputs.get("children", []) if child_outputs else [],
            "parentExecutionStage": child_outputs.get("parentExecutionStage")
            if child_outputs
            else "no_children",
            "blockedChildIssues": blocked_child_issues,
            "delegationOriginRunId": delegation_origin_run_id,
            "closeoutMode": closeout_mode,
            "wakeComment": None,
        }

    async def record_child_replaced(
        self,
        old_child: IssueDetail,
        replacement: IssueDetail,
        *,
        reason: object,
        actor_type: str,
        actor_id: str,
        run_id: str | None = None,
    ) -> None:
        replaced_at = datetime.now(UTC)
        await self._session.execute(
            update(Issue)
            .where(
                Issue.id == old_child["id"],
                Issue.org_id == old_child["orgId"],
                Issue.hidden_at.is_(None),
            )
            .values(hidden_at=replaced_at, updated_at=replaced_at)
        )
        await insert_activity_log(
            self._session,
            org_id=old_child["orgId"],
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.child_replaced",
            entity_type="issue",
            entity_id=old_child["id"],
            run_id=run_id,
            details={
                "replacementIssueId": replacement["id"],
                "reason": reason,
                "retiredAt": replaced_at.isoformat(),
            },
        )

    async def lock_and_get_child_replacement(
        self, child_id: str, org_id: str
    ) -> IssueDetail | None:
        """Serialize replacement creation and replay an existing replacement."""

        await self._session.execute(
            update(Issue)
            .where(Issue.id == child_id, Issue.org_id == org_id)
            .values(updated_at=Issue.updated_at)
        )
        result = await self._session.execute(
            select(ActivityLog.details)
            .where(
                ActivityLog.org_id == org_id,
                ActivityLog.entity_type == "issue",
                ActivityLog.entity_id == child_id,
                ActivityLog.action == "issue.child_replaced",
            )
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(1)
        )
        details = result.scalar_one_or_none()
        replacement_id = (
            details.get("replacementIssueId") if isinstance(details, dict) else None
        )
        if not isinstance(replacement_id, str):
            return None
        return await self.get_by_id(replacement_id)

    async def record_incomplete_accepted(
        self,
        issue: IssueDetail,
        *,
        reason: str,
        actor_type: str,
        actor_id: str,
        child_issue_ids: Sequence[str] | None = None,
        run_id: str | None = None,
    ) -> None:
        details: dict[str, Any] = {"reason": reason}
        if child_issue_ids:
            details["childIssueIds"] = list(child_issue_ids)
            if len(child_issue_ids) == 1:
                details["childIssueId"] = child_issue_ids[0]
        await insert_activity_log(
            self._session,
            org_id=issue["orgId"],
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.incomplete_accepted",
            entity_type="issue",
            entity_id=issue["id"],
            run_id=run_id,
            details=details,
        )

    async def add_comment(
        self,
        issue_id: str,
        payload: CreateIssueCommentPayload,
        *,
        actor_type: str,
        actor_id: str,
        run_id: str | None = None,
    ) -> IssueComment:
        issue = await get_issue_by_id(self._session, issue_id)
        if issue is None:
            raise ValueError("Issue not found")

        request_id = payload.get("requestId")
        values: dict[str, Any] = {
            "org_id": issue.org_id,
            "issue_id": issue.id,
            "body": payload["body"],
            "request_id": request_id,
        }
        if actor_type == "agent":
            values["author_agent_id"] = actor_id
        else:
            values["author_user_id"] = actor_id

        comment, created = await insert_issue_comment_idempotent(self._session, values)
        if not created:
            expected_author = (
                comment.author_agent_id
                if actor_type == "agent"
                else comment.author_user_id
            )
            if comment.body != payload["body"] or expected_author != actor_id:
                raise ValueError("Comment requestId was already used")
            return comment
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.comment_added",
            entity_type="issue",
            entity_id=issue.id,
            run_id=run_id,
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
        detail["documentSummaries"] = await DocumentService(
            self._session
        ).list_issue_documents(row.id)
        return detail


_ISSUE_DOCUMENT_PROMPT_BODY_CHAR_LIMIT = 12_000


def _parent_execution_stage(
    children: Sequence[Mapping[str, Any]], *, parent_status: str | None = None
) -> str:
    if parent_status in {"done", "blocked", "cancelled"}:
        return f"parent_{parent_status}"
    if not children:
        return "no_children"
    statuses = {str(child.get("status") or "") for child in children}
    if statuses & {"backlog", "todo", "in_progress", "in_review"}:
        return "children_active"
    if statuses & {"blocked", "cancelled"}:
        return "children_blocked"
    if statuses <= {"done"}:
        return "children_settled"
    return "children_mixed"


def _blocked_child_issues(
    children: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for child in children:
        status = child.get("status")
        if status not in {"blocked", "cancelled"}:
            continue
        work_products = child.get("workProducts")
        result.append(
            {
                "id": child.get("id"),
                "identifier": child.get("identifier"),
                "title": child.get("title"),
                "status": status,
                "lastCloseout": child.get("lastCloseout"),
                "workProductCount": len(work_products)
                if isinstance(work_products, Sequence)
                else 0,
            }
        )
    return result


def _child_primary_work_products(
    work_products: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for product in work_products:
        metadata = product.get("metadata")
        if (
            not isinstance(metadata, Mapping)
            or metadata.get("parentAggregated") is not True
        ):
            continue
        result.append(
            {
                "id": product.get("id"),
                "issueId": product.get("issueId"),
                "title": product.get("title"),
                "type": product.get("type"),
                "summary": product.get("summary"),
                "url": product.get("url"),
                "contentPath": product.get("contentPath"),
                "sourceIssueId": metadata.get("sourceIssueId"),
                "sourceIssueIdentifier": metadata.get("sourceIssueIdentifier"),
                "sourceIssueTitle": metadata.get("sourceIssueTitle"),
            }
        )
    return result


def _build_child_work_products_prompt(
    child_primary_work_products: Sequence[Mapping[str, Any]],
    *,
    closeout_mode: object = None,
) -> str:
    if not child_primary_work_products:
        return ""
    lines = [
        "## Child Primary Work Products",
        "",
        "Direct child issues have completed and exposed these primary deliverables.",
    ]
    for product in child_primary_work_products:
        child_label = str(
            product.get("sourceIssueIdentifier")
            or product.get("sourceIssueTitle")
            or product.get("sourceIssueId")
            or "child issue"
        )
        title = str(product.get("title") or "Untitled work product")
        summary = str(product.get("summary") or "").strip()
        location = str(product.get("contentPath") or product.get("url") or "").strip()
        line = f"- {child_label}: {title}"
        if summary:
            line += f" — {summary}"
        if location:
            line += f" ({location})"
        lines.append(line)
    if closeout_mode == "child_outputs":
        lines.extend(
            [
                "",
                "These child deliverables are the final outputs for this delegation batch. Verify them and close the parent issue without creating a duplicate parent summary artifact.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Use them as source material for the parent issue's final deliverable.",
                "Create a parent-owned final report or deliverable that synthesizes these child outputs. Do not merely point the user at child task artifacts.",
                "Write the final deliverable to the user-requested path or a clear shared path under `$OCTOPUS_WORKSPACE_CWD` such as `reports/<name>.md` so Octopus can register it as this parent issue's own primary work product. Use `$OCTOPUS_ISSUE_ARTIFACTS_DIR` only as a compatibility fallback, not as the default target for shared project work. Then close out the parent issue.",
            ]
        )
    return "\n".join(lines)


def _build_issue_documents_prompt(
    *,
    plan_document: Mapping[str, Any] | None,
    document_summaries: Sequence[Mapping[str, Any]],
) -> str:
    sections: list[str] = []
    plan_key = (
        str(plan_document.get("key")).strip()
        if isinstance(plan_document, Mapping) and plan_document.get("key") is not None
        else "plan"
    )
    plan_body = (
        str(plan_document.get("body")).strip()
        if isinstance(plan_document, Mapping) and plan_document.get("body") is not None
        else ""
    )
    if plan_body:
        title = (
            str(plan_document.get("title")).strip()
            if isinstance(plan_document, Mapping)
            and plan_document.get("title") is not None
            else ""
        )
        sections.append(
            "\n".join(
                [
                    _format_issue_document_heading(plan_key, title),
                    f"Source: issue document `{plan_key}`.",
                    "",
                    _truncate_issue_document_body(plan_body),
                ]
            )
        )

    additional = [
        summary
        for summary in document_summaries
        if str(summary.get("key") or "").strip() and summary.get("key") != plan_key
    ]
    if additional:
        issue_id = _read_issue_document_prompt_issue_id(plan_document, additional)
        lines = ["### Additional Issue Documents"]
        for summary in additional:
            key = str(summary.get("key") or "document").strip()
            title = str(summary.get("title") or "").strip()
            revision = summary.get("latestRevisionNumber")
            revision_text = (
                f", revision {revision}" if isinstance(revision, int) else ""
            )
            title_text = f" - {title}" if title else ""
            lines.append(
                f"- `{key}`{title_text}{revision_text}. Fetch with "
                f"`octopus issue documents get {issue_id} {key} --json`."
            )
        sections.append("\n".join(lines))

    if not sections:
        return ""
    return "\n\n".join(["## Issue Documents", *sections])


def _format_issue_document_heading(key: str, title: str) -> str:
    return f"### {key} - {title}" if title else f"### {key}"


def _truncate_issue_document_body(body: str) -> str:
    if len(body) <= _ISSUE_DOCUMENT_PROMPT_BODY_CHAR_LIMIT:
        return body
    return (
        body[:_ISSUE_DOCUMENT_PROMPT_BODY_CHAR_LIMIT].rstrip()
        + "\n\n[Document truncated in prompt. Fetch the full document with the "
        "octopus CLI.]"
    )


def _read_issue_document_prompt_issue_id(
    plan_document: Mapping[str, Any] | None,
    document_summaries: Sequence[Mapping[str, Any]],
) -> str:
    if isinstance(plan_document, Mapping):
        issue_id = str(plan_document.get("issueId") or "").strip()
        if issue_id:
            return issue_id
    for summary in document_summaries:
        issue_id = str(summary.get("issueId") or "").strip()
        if issue_id:
            return issue_id
    return "<issue-id>"


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
        createdByAgentId=row.created_by_agent_id,
        createdByUserId=row.created_by_user_id,
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
        createdByAgentId=row.created_by_agent_id,
        createdByUserId=row.created_by_user_id,
        updatedAt=row.updated_at.isoformat(),
        description=row.description,
        reviewerAgentId=row.reviewer_agent_id,
        reviewerUserId=row.reviewer_user_id,
        projectId=row.project_id,
        goalId=row.goal_id,
        parentId=row.parent_id,
        originKind=cast(IssueOriginKind, row.origin_kind),
        originId=row.origin_id,
        originRunId=row.origin_run_id,
        closeoutMode=cast(DelegationCloseoutMode | None, row.closeout_mode),
        issueNumber=row.issue_number,
        requestDepth=row.request_depth,
        startedAt=row.started_at.isoformat() if row.started_at else None,
        completedAt=row.completed_at.isoformat() if row.completed_at else None,
        cancelledAt=row.cancelled_at.isoformat() if row.cancelled_at else None,
        checkoutRunId=row.checkout_run_id,
        executionRunId=row.execution_run_id,
        createdAt=row.created_at.isoformat(),
        workProducts=[],
        documentSummaries=[],
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
