from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.heartbeat import update_run
from packages.database.queries.issues import update_issue
from packages.database.schema import ActivityLog, HeartbeatRun, Issue, IssueWorkProduct
from packages.shared.types.issue import DelegationCloseoutPolicy

from .delegation_closeout import (
    DelegationBatch,
    DelegationBatchStore,
)


@dataclass(frozen=True)
class ParentCloseoutResult:
    applicable: bool
    completed: bool
    error: str | None = None


class ParentCloseoutGovernance:
    """Enforces parent closeout rules for one settled delegation batch."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_closeout_request_if_required(
        self,
        parent: Issue,
        *,
        run_id: str | None,
        actor_type: str,
        actor_id: str,
        comment: str | None,
        declarations: list[dict[str, Any]],
    ) -> bool:
        """Persist an Agent request without prematurely completing the parent."""

        store = DelegationBatchStore(self._session)
        run = await self._session.get(HeartbeatRun, run_id) if run_id else None
        if run is not None and run.org_id != parent.org_id:
            run = None
        context = (
            run.context_snapshot
            if run is not None and isinstance(run.context_snapshot, dict)
            else {}
        )
        context_origin = context.get("delegationOriginRunId")
        batch = (
            await store.for_parent(
                parent.id,
                org_id=parent.org_id,
                origin_run_id=context_origin,
            )
            if isinstance(context_origin, str) and context_origin
            else await store.latest_for_parent(parent.id, org_id=parent.org_id)
        )
        if batch is None or not batch.requires_parent_output:
            return False
        if actor_type != "agent":
            raise ValueError(
                "This parent requires a validated parent output. A human operator "
                "cannot bypass it by directly marking the issue done."
            )
        if run is None:
            raise ValueError(
                "A parent-output closeout request must come from an active Agent Run"
            )
        origin_run_id = batch.origin_run_id
        if origin_run_id is None:
            return False
        if (
            context_origin != origin_run_id
            or context.get("closeoutPolicy") != batch.closeout_policy
        ):
            updated_context = {
                **context,
                "delegationOriginRunId": origin_run_id,
                "closeoutPolicy": batch.closeout_policy,
            }
            updated_run = await update_run(
                self._session, run.id, {"context_snapshot": updated_context}
            )
            if updated_run is not None:
                run = updated_run
        if any(
            child.status in {"backlog", "todo", "in_progress", "in_review"}
            for child in batch.children
        ):
            raise ValueError(
                "Cannot request parent closeout while delegated child issues are open"
            )
        declaration_error = self._required_declaration_error(
            batch.closeout_policy, declarations
        )
        if declaration_error is not None:
            raise ValueError(declaration_error)
        existing = await self._session.execute(
            select(ActivityLog.details)
            .where(
                ActivityLog.org_id == parent.org_id,
                ActivityLog.entity_type == "issue",
                ActivityLog.entity_id == parent.id,
                ActivityLog.run_id == run.id,
                ActivityLog.action == "issue.closeout_requested",
            )
            .limit(1)
        )
        previous = existing.scalar_one_or_none()
        next_details = {
            "version": 1,
            "runId": run.id,
            "delegationOriginRunId": origin_run_id,
            "declaredWorkProducts": declarations,
            "comment": comment,
        }
        if previous == next_details:
            return True
        if parent.status == "todo":
            await update_issue(
                self._session,
                parent.id,
                {"status": "in_progress", "started_at": datetime.now(UTC)},
            )
        await insert_activity_log(
            self._session,
            org_id=parent.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.closeout_requested",
            entity_type="issue",
            entity_id=parent.id,
            agent_id=run.agent_id,
            run_id=run.id,
            details=next_details,
        )
        return True

    async def finalize_parent_output_request(
        self, run: HeartbeatRun, parent: Issue, *, apply: bool = True
    ) -> ParentCloseoutResult:
        context = run.context_snapshot if isinstance(run.context_snapshot, dict) else {}
        origin_run_id = context.get("delegationOriginRunId")
        store = DelegationBatchStore(self._session)
        batch = (
            await store.for_parent(
                parent.id,
                org_id=parent.org_id,
                origin_run_id=origin_run_id,
            )
            if isinstance(origin_run_id, str) and origin_run_id
            else await store.latest_for_parent(parent.id, org_id=parent.org_id)
        )
        if batch is None:
            return ParentCloseoutResult(applicable=False, completed=False)
        policy = batch.closeout_policy
        if policy["mode"] != "parent_output_required":
            return ParentCloseoutResult(applicable=False, completed=False)
        request = await self._closeout_request(run, parent)
        is_settlement_continuation = (
            context.get("wakeReason") == "issue_children_settled"
        )
        if request is None and not is_settlement_continuation:
            # Delegation and progress Runs are not parent closeout attempts. The
            # parent-output policy becomes mandatory only when the parent Agent
            # is resumed after its children settle, or when this Run explicitly
            # requested completion through `octopus issue done`.
            return ParentCloseoutResult(applicable=False, completed=False)
        children = list(batch.children)
        open_children = [
            child
            for child in children
            if child.status in {"backlog", "todo", "in_progress", "in_review"}
        ]
        if open_children:
            return ParentCloseoutResult(
                applicable=True,
                completed=False,
                error=(
                    "Parent closeout cannot be verified because delegated child "
                    f"issues are still open: {self._child_labels(open_children)}."
                ),
            )
        blocked_children = await self._unaccepted_blocked_children(run, parent)
        if blocked_children:
            return ParentCloseoutResult(
                applicable=True,
                completed=False,
                error=(
                    "Parent closeout cannot be verified because delegated child "
                    f"issues are blocked or cancelled: {self._child_labels(blocked_children)}."
                ),
            )
        if request is None:
            return ParentCloseoutResult(
                applicable=True,
                completed=False,
                error=(
                    "Parent closeout request is missing. Run `octopus issue done` "
                    "and declare the parent output with `--primary-work-product`."
                ),
            )
        declared = request.get("declaredWorkProducts")
        declared_items = declared if isinstance(declared, list) else []
        declared_paths, primary_paths = self._declaration_paths(declared_items)
        requirements = policy.get("requirements", {})
        minimum_outputs = requirements.get("minimumOutputs", 1)
        primary_required = requirements.get("primaryOutputRequired", True)
        declaration_error = self._required_declaration_error(policy, declared_items)
        if declaration_error is not None:
            return ParentCloseoutResult(
                applicable=True,
                completed=False,
                error=declaration_error,
            )
        paths_to_validate = primary_paths if primary_required else declared_paths
        matched_paths = await self._matching_parent_product_paths(
            parent,
            paths_to_validate,
            primary_only=primary_required,
        )
        if len(matched_paths) < minimum_outputs:
            missing = sorted(paths_to_validate - matched_paths)
            detail = ", ".join(missing) if missing else "no declared output was found"
            return ParentCloseoutResult(
                applicable=True,
                completed=False,
                error=(
                    "Parent closeout output validation failed: "
                    f"{detail}. Required outputs: {minimum_outputs}; "
                    f"validated outputs: {len(matched_paths)}."
                ),
            )
        if not apply:
            return ParentCloseoutResult(applicable=True, completed=True)
        target_status = (
            "in_review"
            if parent.reviewer_agent_id or parent.reviewer_user_id
            else "done"
        )
        existing_finalization = await self._session.execute(
            select(ActivityLog.details).where(
                ActivityLog.org_id == parent.org_id,
                ActivityLog.entity_type == "issue",
                ActivityLog.entity_id == parent.id,
                ActivityLog.run_id == run.id,
                ActivityLog.action == "issue.updated",
            )
        )
        if any(
            isinstance(item, dict) and item.get("reason") == "parent_closeout_validated"
            for item in existing_finalization.scalars().all()
        ):
            return ParentCloseoutResult(applicable=True, completed=True)
        values: dict[str, Any] = {"status": target_status}
        if target_status == "done":
            values["completed_at"] = datetime.now(UTC)
        await update_issue(self._session, parent.id, values)
        await insert_activity_log(
            self._session,
            org_id=parent.org_id,
            actor_type="system",
            actor_id="run_finalization_service",
            action="issue.updated",
            entity_type="issue",
            entity_id=parent.id,
            agent_id=run.agent_id,
            run_id=run.id,
            details={
                "status": target_status,
                "reason": "parent_closeout_validated",
                "validatedPrimaryWorkProducts": sorted(matched_paths),
            },
        )
        return ParentCloseoutResult(applicable=True, completed=True)

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

    async def _accepted_incomplete_child_ids(
        self, parent: Issue, batch: DelegationBatch | None
    ) -> set[str]:
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
            if (
                batch is not None
                and details.get("delegationOriginRunId") != batch.origin_run_id
            ):
                continue
            child_issue_id = details.get("childIssueId")
            if isinstance(child_issue_id, str) and child_issue_id:
                accepted.add(child_issue_id)
            child_issue_ids = details.get("childIssueIds")
            if isinstance(child_issue_ids, list):
                valid_ids = {
                    child_id
                    for child_id in child_issue_ids
                    if isinstance(child_id, str) and child_id
                }
                accepted.update(valid_ids)
        return accepted

    async def _unaccepted_blocked_children(
        self, run: HeartbeatRun, parent: Issue
    ) -> list[Issue]:
        context = run.context_snapshot if isinstance(run.context_snapshot, dict) else {}
        origin_run_id = context.get("delegationOriginRunId")
        batch = (
            await DelegationBatchStore(self._session).for_parent(
                parent.id,
                org_id=parent.org_id,
                origin_run_id=origin_run_id,
            )
            if isinstance(origin_run_id, str) and origin_run_id
            else await DelegationBatchStore(self._session).latest_for_parent(
                parent.id, org_id=parent.org_id
            )
        )
        if batch is None:
            accepted_child_ids = await self._accepted_incomplete_child_ids(parent, None)
            return [
                child
                for child in await self.children_for_run(run, parent)
                if child.status in {"blocked", "cancelled"}
                and child.id not in accepted_child_ids
            ]
        accepted_child_ids = await self._accepted_incomplete_child_ids(parent, batch)
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

    async def _closeout_request(
        self, run: HeartbeatRun, parent: Issue
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(ActivityLog.details)
            .where(
                ActivityLog.org_id == parent.org_id,
                ActivityLog.run_id == run.id,
                ActivityLog.entity_type == "issue",
                ActivityLog.entity_id == parent.id,
                ActivityLog.action == "issue.closeout_requested",
            )
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(1)
        )
        details = result.scalar_one_or_none()
        return details if isinstance(details, dict) else None

    async def _matching_parent_product_paths(
        self,
        parent: Issue,
        declared_paths: set[str],
        *,
        primary_only: bool,
    ) -> set[str]:
        if not declared_paths:
            return set()
        criteria = [
            IssueWorkProduct.org_id == parent.org_id,
            IssueWorkProduct.issue_id == parent.id,
            IssueWorkProduct.status.in_(("active", "ready")),
        ]
        if primary_only:
            criteria.append(IssueWorkProduct.is_primary.is_(True))
        product_rows = await self._session.execute(
            select(IssueWorkProduct).where(*criteria)
        )
        matched: set[str] = set()
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
            matched.update(declared_paths & product_paths)
        return matched

    @staticmethod
    def _child_labels(children: list[Issue]) -> str:
        return ", ".join(child.identifier or child.id for child in children)

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
    def _normalize_product_path(value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return value.replace("\\", "/").strip().casefold()

    def _declaration_paths(self, declarations: list[Any]) -> tuple[set[str], set[str]]:
        declared_paths = {
            normalized
            for item in declarations
            if isinstance(item, dict)
            for normalized in (self._normalize_product_path(item.get("path")),)
            if normalized
        }
        primary_paths = {
            normalized
            for item in declarations
            if isinstance(item, dict) and item.get("isPrimary") is True
            for normalized in (self._normalize_product_path(item.get("path")),)
            if normalized
        }
        return declared_paths, primary_paths

    def _required_declaration_error(
        self, policy: DelegationCloseoutPolicy, declarations: list[Any]
    ) -> str | None:
        requirements = policy.get("requirements", {})
        if requirements.get("primaryOutputRequired", True):
            _, primary_paths = self._declaration_paths(declarations)
            if not primary_paths:
                return (
                    "Parent closeout requires a primary output declaration. Retry "
                    "`octopus issue done` with `--primary-work-product <path>`."
                )
        return None
