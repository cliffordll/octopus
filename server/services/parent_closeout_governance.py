from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.issues import update_issue
from packages.database.schema import ActivityLog, HeartbeatRun, Issue, IssueWorkProduct

from .delegation_closeout import DelegationBatchStore, closeout_mode_from_context


class ParentCloseoutGovernance:
    """Enforces parent closeout rules for one settled delegation batch."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def block_for_unresolved_children(
        self, run: HeartbeatRun, parent: Issue
    ) -> bool:
        blocked_children = await self._unaccepted_blocked_children(run, parent)
        if not blocked_children:
            return False
        from_status = parent.status
        await update_issue(
            self._session,
            parent.id,
            {"status": "blocked", "completed_at": None},
        )
        await insert_activity_log(
            self._session,
            org_id=parent.org_id,
            actor_type="system",
            actor_id="parent_child_governance",
            action="issue.updated",
            entity_type="issue",
            entity_id=parent.id,
            agent_id=run.agent_id,
            run_id=run.id,
            details={
                "status": "blocked",
                "fromStatus": from_status,
                "reason": "blocked_child_unresolved",
                "runId": run.id,
                "childIssues": self._child_summaries(blocked_children),
            },
        )
        await insert_activity_log(
            self._session,
            org_id=parent.org_id,
            actor_type="system",
            actor_id="parent_child_governance",
            action="issue.parent_blocked_child_unresolved",
            entity_type="issue",
            entity_id=parent.id,
            agent_id=run.agent_id,
            run_id=run.id,
            details={
                "issueId": parent.id,
                "runId": run.id,
                "reason": "parent_blocked_due_to_blocked_children",
                "childIssues": self._child_summaries(blocked_children),
                "nextActions": [
                    "retry_child",
                    "reassign_child",
                    "create_replacement_child",
                    "accept_incomplete",
                ],
            },
        )
        return True

    async def record_blocked_child_if_needed(
        self, run: HeartbeatRun, parent: Issue
    ) -> bool:
        blocked_children = await self._unaccepted_blocked_children(run, parent)
        if not blocked_children:
            return False
        if parent.status == "done":
            await update_issue(
                self._session,
                parent.id,
                {
                    "status": "blocked",
                    "completed_at": None,
                    "cancelled_at": None,
                },
            )
            await insert_activity_log(
                self._session,
                org_id=parent.org_id,
                actor_type="system",
                actor_id="parent_child_governance",
                action="issue.updated",
                entity_type="issue",
                entity_id=parent.id,
                agent_id=run.agent_id,
                run_id=run.id,
                details={
                    "status": "blocked",
                    "fromStatus": "done",
                    "reason": "parent_done_with_blocked_children",
                    "runId": run.id,
                    "childIssues": self._child_summaries(blocked_children),
                },
            )
            parent.status = "blocked"
            parent.completed_at = None
            parent.cancelled_at = None
        if await self._run_has_activity(
            run, parent.id, ("issue.parent_blocked_child_unresolved",)
        ):
            return True
        await insert_activity_log(
            self._session,
            org_id=parent.org_id,
            actor_type="system",
            actor_id="parent_child_governance",
            action="issue.parent_blocked_child_unresolved",
            entity_type="issue",
            entity_id=parent.id,
            agent_id=run.agent_id,
            run_id=run.id,
            details={
                "issueId": parent.id,
                "runId": run.id,
                "reason": "parent_done_with_blocked_children",
                "childIssues": self._child_summaries(blocked_children),
                "allowedCloseout": "block_parent_or_create_replacement_child",
            },
        )
        return True

    async def record_evidence_warning_if_needed(
        self, run: HeartbeatRun, parent: Issue
    ) -> bool:
        children = await self.children_for_run(run, parent)
        if not children:
            return False
        if any(
            child.status in {"backlog", "todo", "in_progress", "in_review"}
            for child in children
        ):
            return False
        if await self._run_has_activity(
            run, parent.id, ("issue.parent_deliverable_convergence_warning",)
        ):
            return True
        closeout_mode = closeout_mode_from_context(run.context_snapshot)
        missing_child_ids: list[str] = []
        if closeout_mode == "child_outputs":
            missing_child_ids = await self._children_missing_primary_outputs(children)
            if not missing_child_ids:
                return False
        elif await self._has_parent_summary_evidence(run, parent, children):
            return False
        await insert_activity_log(
            self._session,
            org_id=parent.org_id,
            actor_type="system",
            actor_id="parent_deliverable_governance",
            action="issue.parent_deliverable_convergence_warning",
            entity_type="issue",
            entity_id=parent.id,
            agent_id=run.agent_id,
            run_id=run.id,
            details={
                "issueId": parent.id,
                "runId": run.id,
                "reason": (
                    "child_outputs_missing_primary_work_product"
                    if closeout_mode == "child_outputs"
                    else "parent_done_without_child_output_evidence"
                ),
                "closeoutMode": closeout_mode,
                "childIssues": self._child_summaries(children),
                "expectedEvidence": (
                    ["primary_work_product_for_every_completed_child"]
                    if closeout_mode == "child_outputs"
                    else [
                        "parent_primary_work_product_after_children_settled",
                        "closeout_comment_mentions_child_identifier_or_title",
                    ]
                ),
                "missingChildIssueIds": missing_child_ids,
            },
        )
        return True

    def missing_evidence_message(self, run: HeartbeatRun) -> str:
        if closeout_mode_from_context(run.context_snapshot) == "child_outputs":
            return (
                "Parent issue cannot close because one or more delegated child "
                "outputs have no primary work product."
            )
        return (
            "Parent issue was marked done without a parent-owned final "
            "deliverable or child-output evidence."
        )

    async def _accepted_incomplete_child_ids(self, parent: Issue) -> set[str]:
        rows = (
            (
                await self._session.execute(
                    select(ActivityLog.details).where(
                        ActivityLog.org_id == parent.org_id,
                        ActivityLog.entity_type == "issue",
                        ActivityLog.entity_id == parent.id,
                        ActivityLog.action == "issue.incomplete_accepted",
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

    async def _unaccepted_blocked_children(
        self, run: HeartbeatRun, parent: Issue
    ) -> list[Issue]:
        accepted_child_ids = await self._accepted_incomplete_child_ids(parent)
        return [
            child
            for child in await self.children_for_run(run, parent)
            if child.status in {"blocked", "cancelled"}
            and child.id not in accepted_child_ids
        ]

    async def children_for_run(self, run: HeartbeatRun, parent: Issue) -> list[Issue]:
        context = run.context_snapshot if isinstance(run.context_snapshot, dict) else {}
        origin_run_id = context.get("delegationOriginRunId")
        if isinstance(origin_run_id, str) and origin_run_id:
            batch = await DelegationBatchStore(self._session).for_parent(
                parent.id,
                org_id=parent.org_id,
                origin_run_id=origin_run_id,
            )
            if batch is not None:
                return list(batch.children)
        result = await self._session.execute(
            select(Issue).where(
                Issue.org_id == parent.org_id,
                Issue.parent_id == parent.id,
                Issue.hidden_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def _children_missing_primary_outputs(
        self, children: list[Issue]
    ) -> list[str]:
        completed_child_ids = [child.id for child in children if child.status == "done"]
        if not completed_child_ids:
            return []
        rows = await self._session.execute(
            select(IssueWorkProduct.issue_id).where(
                IssueWorkProduct.issue_id.in_(completed_child_ids),
                IssueWorkProduct.is_primary.is_(True),
            )
        )
        child_ids_with_products = set(rows.scalars().all())
        return [
            child_id
            for child_id in completed_child_ids
            if child_id not in child_ids_with_products
        ]

    async def _has_parent_summary_evidence(
        self, run: HeartbeatRun, parent: Issue, children: list[Issue]
    ) -> bool:
        if await self._run_declares_existing_parent_primary_product(run, parent):
            return True
        child_settled_at = max(
            (child.completed_at or child.updated_at or child.created_at)
            for child in children
        )
        if child_settled_at.tzinfo is None:
            child_settled_at = child_settled_at.replace(tzinfo=UTC)
        product_created_at = await self._latest_parent_primary_product_at(parent)
        if product_created_at is not None:
            if product_created_at.tzinfo is None:
                product_created_at = product_created_at.replace(tzinfo=UTC)
            if product_created_at >= child_settled_at:
                return True
        return await self._run_mentions_children(run, parent, children)

    async def _run_declares_existing_parent_primary_product(
        self, run: HeartbeatRun, parent: Issue
    ) -> bool:
        """Accept an existing parent artifact explicitly resubmitted by this Run."""
        activity_rows = await self._session.execute(
            select(ActivityLog.details).where(
                ActivityLog.org_id == parent.org_id,
                ActivityLog.run_id == run.id,
                ActivityLog.entity_type == "issue",
                ActivityLog.entity_id == parent.id,
            )
        )
        declared_paths = {
            normalized
            for details in activity_rows.scalars().all()
            if isinstance(details, dict)
            for declaration in (details.get("workProductDeclarations") or [])
            if isinstance(declaration, dict) and declaration.get("isPrimary") is True
            for normalized in (self._normalize_product_path(declaration.get("path")),)
            if normalized
        }
        if not declared_paths:
            return False

        product_rows = await self._session.execute(
            select(IssueWorkProduct).where(
                IssueWorkProduct.org_id == parent.org_id,
                IssueWorkProduct.issue_id == parent.id,
                IssueWorkProduct.is_primary.is_(True),
            )
        )
        for product in product_rows.scalars().all():
            metadata = (
                product.metadata_json if isinstance(product.metadata_json, dict) else {}
            )
            product_paths = {
                normalized
                for value in (
                    product.title,
                    metadata.get("workspacePath"),
                    metadata.get("path"),
                )
                for normalized in (self._normalize_product_path(value),)
                if normalized
            }
            if declared_paths & product_paths:
                return True
        return False

    async def _latest_parent_primary_product_at(self, parent: Issue) -> datetime | None:
        result = await self._session.execute(
            select(IssueWorkProduct.created_at)
            .where(
                IssueWorkProduct.org_id == parent.org_id,
                IssueWorkProduct.issue_id == parent.id,
                IssueWorkProduct.is_primary.is_(True),
            )
            .order_by(IssueWorkProduct.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _run_mentions_children(
        self, run: HeartbeatRun, parent: Issue, children: list[Issue]
    ) -> bool:
        result = await self._session.execute(
            select(ActivityLog.details).where(
                ActivityLog.org_id == parent.org_id,
                ActivityLog.run_id == run.id,
                ActivityLog.entity_type == "issue",
                ActivityLog.entity_id == parent.id,
                ActivityLog.action.in_(("issue.comment_added", "issue.updated")),
            )
        )
        haystack = "\n".join(
            self._activity_details_text(details)
            for details in result.scalars().all()
            if isinstance(details, dict)
        ).casefold()
        return bool(haystack) and any(
            needle and needle.casefold() in haystack
            for child in children
            for needle in (child.identifier, child.title)
        )

    async def _run_has_activity(
        self, run: HeartbeatRun, issue_id: str, actions: tuple[str, ...]
    ) -> bool:
        result = await self._session.execute(
            select(ActivityLog.id)
            .where(
                ActivityLog.org_id == run.org_id,
                ActivityLog.run_id == run.id,
                ActivityLog.entity_type == "issue",
                ActivityLog.entity_id == issue_id,
                ActivityLog.action.in_(actions),
            )
            .limit(1)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _child_summaries(children: list[Issue]) -> list[dict[str, Any]]:
        return [
            {
                "id": child.id,
                "identifier": child.identifier,
                "title": child.title,
                "status": child.status,
            }
            for child in children
        ]

    @staticmethod
    def _activity_details_text(details: dict[str, Any]) -> str:
        values: list[str] = []
        for key in ("body", "comment", "note", "summary", "message", "status"):
            value = details.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value)
        return "\n".join(values)

    @staticmethod
    def _normalize_product_path(value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return value.replace("\\", "/").strip().casefold()
