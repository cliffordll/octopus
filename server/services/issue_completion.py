from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select, update as sqlalchemy_update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.issues import update_issue
from packages.database.schema import ActivityLog, HeartbeatRun, Issue, IssueWorkProduct

from .issue_hierarchy import IssueHierarchyPolicy


@dataclass(frozen=True)
class IssueCompletionResult:
    applicable: bool
    completed: bool
    error: str | None = None


class IssueCompletionGovernance:
    """Validate declared issue outputs before applying Agent-requested completion."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_request_if_declared(
        self,
        issue: Issue,
        *,
        run_id: str | None,
        actor_type: str,
        actor_id: str,
        comment: str | None,
        declarations: list[dict[str, Any]],
    ) -> bool:
        if actor_type != "agent" or not run_id:
            return False
        if not declarations:
            # Preserve the ordinary no-output completion path. The only case we
            # intercept is a repeated completion call from a Run that already
            # recorded structured output declarations; otherwise a second call
            # could bypass the pending validation request.
            return await self._request_by_run_id(run_id, issue) is not None
        run = await self._session.get(HeartbeatRun, run_id)
        context = (
            run.context_snapshot
            if run is not None and isinstance(run.context_snapshot, dict)
            else {}
        )
        if (
            run is None
            or run.org_id != issue.org_id
            or run.agent_id != actor_id
            or run.status != "running"
            or context.get("issueId") != issue.id
            or issue.execution_run_id != run.id
            or issue.checkout_run_id != run.id
        ):
            raise ValueError(
                "A declared-output completion request must come from the active Agent Run"
            )
        existing = await self._request(run, issue)
        declared_paths, _ = self._declaration_paths(declarations)
        if not declared_paths:
            raise ValueError("Completion output declarations must include a valid path")
        details = {
            "version": 1,
            "runId": run.id,
            "declaredWorkProducts": declarations,
            "comment": comment,
        }
        if existing == details:
            return True
        if issue.status == "todo":
            await update_issue(
                self._session,
                issue.id,
                {"status": "in_progress", "started_at": datetime.now(UTC)},
            )
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="issue.completion_requested",
            entity_type="issue",
            entity_id=issue.id,
            agent_id=run.agent_id,
            run_id=run.id,
            details=details,
        )
        return True

    async def validate(
        self, run: HeartbeatRun, issue: Issue, *, apply: bool = False
    ) -> IssueCompletionResult:
        request = await self._request(run, issue)
        if request is None:
            return IssueCompletionResult(applicable=False, completed=False)
        if apply and await self._was_finalized(run, issue):
            return IssueCompletionResult(applicable=True, completed=True)
        if apply:
            locked = await IssueHierarchyPolicy(self._session).lock_root(
                issue.id, issue.org_id
            )
            if locked is None:
                return IssueCompletionResult(
                    applicable=True,
                    completed=False,
                    error="Issue completion target no longer exists.",
                )
            issue = locked
        unsettled_descendants = await self._unsettled_descendant_labels(issue)
        if unsettled_descendants:
            return IssueCompletionResult(
                applicable=True,
                completed=False,
                error=(
                    "Issue completion cannot be validated while descendant issues "
                    f"remain unsettled: {', '.join(unsettled_descendants)}."
                ),
            )
        declarations = request.get("declaredWorkProducts")
        declared_items = declarations if isinstance(declarations, list) else []
        declared_paths, primary_paths = self._declaration_paths(declared_items)
        matched_paths = await self._matching_product_paths(
            run,
            issue,
            declared_paths,
            primary_only=False,
        )
        matched_primary_paths = await self._matching_product_paths(
            run,
            issue,
            primary_paths,
            primary_only=True,
        )
        missing_paths = sorted(
            (declared_paths - matched_paths) | (primary_paths - matched_primary_paths)
        )
        if missing_paths:
            return IssueCompletionResult(
                applicable=True,
                completed=False,
                error=(
                    "Issue completion output validation failed: "
                    f"{', '.join(missing_paths)}. Declared outputs must exist in "
                    "the managed workspace before the issue can complete."
                ),
            )
        if not apply:
            return IssueCompletionResult(applicable=True, completed=True)
        target_status = (
            "in_review" if issue.reviewer_agent_id or issue.reviewer_user_id else "done"
        )
        values: dict[str, Any] = {"status": target_status}
        if target_status == "done":
            values["completed_at"] = datetime.now(UTC)
        if not await self._transition_issue(run, issue, values):
            await self._record_stale_effect(run, issue, "completion")
            return IssueCompletionResult(
                applicable=True,
                completed=False,
                error="Issue completion was superseded by a newer issue state.",
            )
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type="system",
            actor_id="run_finalization_service",
            action="issue.updated",
            entity_type="issue",
            entity_id=issue.id,
            agent_id=run.agent_id,
            run_id=run.id,
            details={
                "status": target_status,
                "reason": "declared_outputs_validated",
                "validatedWorkProducts": sorted(matched_paths),
            },
        )
        return IssueCompletionResult(applicable=True, completed=True)

    async def block_failed_request(self, run: HeartbeatRun, issue: Issue) -> bool:
        request = await self._request(run, issue)
        if request is None or issue.status not in {"todo", "in_progress"}:
            return False
        from_status = issue.status
        if not await self._transition_issue(
            run, issue, {"status": "blocked", "completed_at": None}
        ):
            await self._record_stale_effect(run, issue, "block")
            return False
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type="system",
            actor_id="run_finalization_service",
            action="issue.updated",
            entity_type="issue",
            entity_id=issue.id,
            agent_id=run.agent_id,
            run_id=run.id,
            details={
                "status": "blocked",
                "fromStatus": from_status,
                "reason": "declared_outputs_missing",
                "runId": run.id,
                "error": run.error,
            },
        )
        return True

    async def _transition_issue(
        self, run: HeartbeatRun, issue: Issue, values: dict[str, Any]
    ) -> bool:
        result = await self._session.execute(
            sqlalchemy_update(Issue)
            .where(
                Issue.org_id == issue.org_id,
                Issue.id == issue.id,
                Issue.assignee_agent_id == run.agent_id,
                Issue.execution_run_id == run.id,
                Issue.checkout_run_id == run.id,
                Issue.status.in_(("todo", "in_progress")),
            )
            .values(**values, updated_at=datetime.now(UTC))
            .returning(Issue.id)
        )
        changed = result.scalar_one_or_none() is not None
        if changed:
            await self._session.refresh(issue)
        return changed

    async def _record_stale_effect(
        self, run: HeartbeatRun, issue: Issue, effect: str
    ) -> None:
        await insert_activity_log(
            self._session,
            org_id=issue.org_id,
            actor_type="system",
            actor_id="run_finalization_service",
            action="issue.completion_effect_skipped",
            entity_type="issue",
            entity_id=issue.id,
            agent_id=run.agent_id,
            run_id=run.id,
            details={
                "runId": run.id,
                "effect": effect,
                "reason": "stale_issue_execution",
            },
        )

    async def _request(self, run: HeartbeatRun, issue: Issue) -> dict[str, Any] | None:
        return await self._request_by_run_id(run.id, issue)

    async def _request_by_run_id(
        self, run_id: str, issue: Issue
    ) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(ActivityLog.details)
            .where(
                and_(
                    ActivityLog.org_id == issue.org_id,
                    ActivityLog.entity_type == "issue",
                    ActivityLog.entity_id == issue.id,
                    ActivityLog.run_id == run_id,
                    ActivityLog.action == "issue.completion_requested",
                )
            )
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
            .limit(1)
        )
        details = result.scalar_one_or_none()
        return details if isinstance(details, dict) else None

    async def _was_finalized(self, run: HeartbeatRun, issue: Issue) -> bool:
        result = await self._session.execute(
            select(ActivityLog.details).where(
                and_(
                    ActivityLog.org_id == issue.org_id,
                    ActivityLog.entity_type == "issue",
                    ActivityLog.entity_id == issue.id,
                    ActivityLog.run_id == run.id,
                    ActivityLog.action == "issue.updated",
                )
            )
        )
        return any(
            isinstance(details, dict)
            and details.get("reason") == "declared_outputs_validated"
            for details in result.scalars().all()
        )

    async def _matching_product_paths(
        self,
        run: HeartbeatRun,
        issue: Issue,
        expected_paths: set[str],
        *,
        primary_only: bool,
    ) -> set[str]:
        if not expected_paths:
            return set()
        criteria = [
            IssueWorkProduct.org_id == issue.org_id,
            IssueWorkProduct.issue_id == issue.id,
            IssueWorkProduct.created_by_run_id == run.id,
            IssueWorkProduct.status == "active",
        ]
        if primary_only:
            criteria.append(IssueWorkProduct.is_primary.is_(True))
        products = (
            (
                await self._session.execute(
                    select(IssueWorkProduct).where(and_(*criteria))
                )
            )
            .scalars()
            .all()
        )
        matched: set[str] = set()
        for product in products:
            metadata = (
                product.metadata_json if isinstance(product.metadata_json, dict) else {}
            )
            raw_workspace_path = metadata.get("workspacePath")
            workspace_path = self._normalize_path(raw_workspace_path)
            if (
                workspace_path is not None
                and workspace_path in expected_paths
                and isinstance(raw_workspace_path, str)
                and self._workspace_file_exists(run, metadata, raw_workspace_path)
            ):
                matched.add(workspace_path)
        return matched

    async def _unsettled_descendant_labels(self, issue: Issue) -> list[str]:
        unsettled = await IssueHierarchyPolicy(self._session).unsettled_descendants(
            issue
        )
        return sorted(child.identifier or child.id for child in unsettled)

    @staticmethod
    def _workspace_file_exists(
        run: HeartbeatRun, metadata: dict[str, Any], workspace_path: str
    ) -> bool:
        context = run.context_snapshot if isinstance(run.context_snapshot, dict) else {}
        workspace_payload = context.get("workspace")
        workspace_payload = (
            workspace_payload if isinstance(workspace_payload, dict) else {}
        )
        workspace = workspace_payload.get("octopusWorkspace")
        workspace = workspace if isinstance(workspace, dict) else {}
        source = metadata.get("source")
        root_value = (
            workspace.get("issueArtifactsDir")
            if source == "issue_artifacts_scan"
            else workspace.get("orgArtifactsDir")
            if source == "organization_artifacts_scan"
            else workspace.get("cwd")
        )
        if not isinstance(root_value, str) or not root_value.strip():
            return False
        root = Path(root_value).resolve()
        candidate = (root / workspace_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return False
        return candidate.is_file()

    @classmethod
    def _declaration_paths(cls, declarations: list[Any]) -> tuple[set[str], set[str]]:
        declared_paths = {
            path
            for item in declarations
            if isinstance(item, dict)
            for path in (cls._normalize_path(item.get("path")),)
            if path is not None
        }
        primary_paths = {
            path
            for item in declarations
            if isinstance(item, dict) and item.get("isPrimary") is True
            for path in (cls._normalize_path(item.get("path")),)
            if path is not None
        }
        return declared_paths, primary_paths

    @staticmethod
    def _normalize_path(value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return value.replace("\\", "/").strip().casefold()
