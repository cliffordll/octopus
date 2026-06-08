from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import uuid
from collections.abc import Sequence
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import get_agent_by_id, update_agent
from packages.database.queries.budgets import (
    create_budget_incident,
    create_budget_policy,
    find_budget_policy,
    get_budget_incident,
    get_budget_policy,
    get_open_budget_incident,
    list_budget_policies,
    list_budget_scope_runs,
    list_open_budget_incidents,
    list_relevant_budget_policies,
    observed_budget_amount,
    resolve_budget_incident,
    resolve_open_budget_incidents_for_policy,
    update_budget_policy,
)
from packages.database.queries.heartbeat import update_run
from packages.database.queries.organizations import (
    get_organization_by_id,
    update_organization,
)
from packages.database.queries.projects import get_project_by_id, update_project
from packages.database.schema import BudgetIncident as BudgetIncidentRow
from packages.database.schema import BudgetPolicy as BudgetPolicyRow
from packages.database.schema import CostEvent
from packages.database.schema import Approval
from packages.shared.constants.agent import PauseReason
from packages.shared.constants.budget import (
    BudgetIncidentStatus,
    BudgetMetric,
    BudgetScopeType,
    BudgetThresholdType,
    BudgetWindowKind,
)
from packages.shared.types.budget import (
    BudgetIncident,
    BudgetIncidentResolutionInput,
    BudgetOverview,
    BudgetPolicySummary,
    BudgetPolicyUpsertInput,
)


@dataclass(frozen=True)
class BudgetInvocationBlock:
    scope_type: BudgetScopeType
    scope_id: str
    scope_name: str
    reason: str


def _current_month_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    current = now or datetime.now(UTC)
    start = datetime(current.year, current.month, 1, tzinfo=UTC)
    if current.month == 12:
        end = datetime(current.year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(current.year, current.month + 1, 1, tzinfo=UTC)
    return start, end


def _resolve_window(window_kind: str) -> tuple[datetime, datetime]:
    if window_kind == "lifetime":
        return datetime(1970, 1, 1, tzinfo=UTC), datetime(9999, 1, 1, tzinfo=UTC)
    return _current_month_window()


def _policy_status(observed: int, amount: int, warn_percent: int) -> str:
    if amount <= 0:
        return "ok"
    if observed >= amount:
        return "hard_stop"
    if observed >= (amount * warn_percent + 99) // 100:
        return "warning"
    return "ok"


class BudgetService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_policy(
        self,
        org_id: str,
        payload: BudgetPolicyUpsertInput,
        *,
        actor_type: str,
        actor_id: str,
    ) -> BudgetPolicySummary:
        scope_name, scope_paused, scope_pause_reason = await self._scope_state(
            payload["scopeType"], payload["scopeId"], expected_org_id=org_id
        )
        existing = await find_budget_policy(
            self._session,
            org_id=org_id,
            scope_type=payload["scopeType"],
            scope_id=payload["scopeId"],
            metric=payload["metric"],
            window_kind=payload["windowKind"],
        )
        fields = {
            "amount": payload["amount"],
            "warn_percent": payload["warnPercent"],
            "hard_stop_enabled": payload["hardStopEnabled"],
            "notify_enabled": payload["notifyEnabled"],
            "is_active": payload["isActive"] and payload["amount"] > 0,
            "updated_by_user_id": actor_id if actor_type != "agent" else None,
        }
        if existing is None:
            row = await create_budget_policy(
                self._session,
                {
                    "id": str(uuid.uuid4()),
                    "org_id": org_id,
                    "scope_type": payload["scopeType"],
                    "scope_id": payload["scopeId"],
                    "metric": payload["metric"],
                    "window_kind": payload["windowKind"],
                    "created_by_user_id": actor_id if actor_type != "agent" else None,
                    **fields,
                },
            )
        else:
            updated = await update_budget_policy(self._session, existing.id, fields)
            assert updated is not None
            row = updated

        await self._sync_monthly_budget_field(row)
        if row.amount > 0:
            observed = await self._observed(row)
            if observed < row.amount:
                await self._resume_scope(row)
                await resolve_open_budget_incidents_for_policy(
                    self._session, row.id, status="resolved"
                )
            else:
                await self._evaluate_policy(row, observed)
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="budget.policy_upserted",
            entity_type="budget_policy",
            entity_id=row.id,
            details={
                "scopeType": row.scope_type,
                "scopeId": row.scope_id,
                "amount": row.amount,
                "windowKind": row.window_kind,
            },
        )
        return await self._summary(row, scope_name, scope_paused, scope_pause_reason)

    async def overview(self, org_id: str) -> BudgetOverview:
        rows = await list_budget_policies(self._session, org_id)
        policies = [await self._summary(row) for row in rows]
        incidents = await self._hydrate_incidents(
            await list_open_budget_incidents(self._session, org_id)
        )
        return {
            "orgId": org_id,
            "policies": policies,
            "activeIncidents": incidents,
            "pausedAgentCount": sum(
                1
                for policy in policies
                if policy["scopeType"] == "agent" and policy["paused"]
            ),
            "pausedProjectCount": sum(
                1
                for policy in policies
                if policy["scopeType"] == "project" and policy["paused"]
            ),
            "pendingApprovalCount": sum(
                1 for incident in incidents if incident["approvalStatus"] == "pending"
            ),
        }

    async def update_org_budget(self, org_id: str, amount: int) -> dict[str, int]:
        org = await update_organization(
            self._session, org_id, {"budget_monthly_cents": amount}
        )
        if org is None:
            raise LookupError("Organization not found")
        return {
            "budgetMonthlyCents": org.budget_monthly_cents,
            "spentMonthlyCents": org.spent_monthly_cents,
        }

    async def update_agent_budget(self, agent_id: str, amount: int) -> dict[str, int]:
        agent = await update_agent(
            self._session, agent_id, {"budget_monthly_cents": amount}
        )
        if agent is None:
            raise LookupError("Agent not found")
        return {
            "budgetMonthlyCents": agent.budget_monthly_cents,
            "spentMonthlyCents": agent.spent_monthly_cents,
        }

    async def evaluate_cost_event(self, event: CostEvent) -> None:
        policies = await list_relevant_budget_policies(
            self._session,
            org_id=event.org_id,
            agent_id=event.agent_id,
            project_id=event.project_id,
        )
        for policy in policies:
            if policy.amount <= 0 or policy.metric != "billed_cents":
                continue
            observed = await self._observed(policy)
            await self._evaluate_policy(policy, observed)

    async def get_invocation_block(
        self,
        org_id: str,
        agent_id: str,
        *,
        project_id: str | None = None,
    ) -> BudgetInvocationBlock | None:
        org = await get_organization_by_id(self._session, org_id)
        if org is None:
            raise LookupError("Organization not found")
        if org.status == "paused":
            return BudgetInvocationBlock(
                scope_type="organization",
                scope_id=org_id,
                scope_name=org.name,
                reason="Organization is paused because its budget hard-stop was reached."
                if org.pause_reason == "budget"
                else "Organization is paused and cannot start new work.",
            )
        agent = await get_agent_by_id(self._session, agent_id)
        if agent is None or agent.org_id != org_id:
            raise LookupError("Agent not found")
        if agent.status == "paused" and agent.pause_reason == "budget":
            return BudgetInvocationBlock(
                scope_type="agent",
                scope_id=agent_id,
                scope_name=agent.name,
                reason="Agent is paused because its budget hard-stop was reached.",
            )
        policies = await list_relevant_budget_policies(
            self._session, org_id=org_id, agent_id=agent_id, project_id=project_id
        )
        for policy in policies:
            if not policy.hard_stop_enabled or policy.amount <= 0:
                continue
            observed = await self._observed(policy)
            if observed >= policy.amount:
                scope_name, _, _ = await self._scope_state(
                    cast(BudgetScopeType, policy.scope_type), policy.scope_id
                )
                return BudgetInvocationBlock(
                    scope_type=cast(BudgetScopeType, policy.scope_type),
                    scope_id=policy.scope_id,
                    scope_name=scope_name,
                    reason=f"{scope_name} cannot start new work because its budget hard-stop is exceeded.",
                )
        return None

    async def resolve_incident(
        self,
        org_id: str,
        incident_id: str,
        payload: BudgetIncidentResolutionInput,
        *,
        actor_type: str,
        actor_id: str,
    ) -> BudgetIncident:
        incident = await get_budget_incident(self._session, incident_id)
        if incident is None or incident.org_id != org_id:
            raise LookupError("Budget incident not found")
        policy = await get_budget_policy(self._session, incident.policy_id)
        if policy is None:
            raise LookupError("Budget policy not found")

        if payload["action"] == "raise_budget_and_resume":
            amount = int(payload.get("amount", 0))
            observed = await self._observed(policy)
            if amount <= observed:
                raise ValueError("New budget must exceed current observed spend")
            updated = await update_budget_policy(
                self._session,
                policy.id,
                {
                    "amount": amount,
                    "is_active": True,
                    "updated_by_user_id": actor_id if actor_type != "agent" else None,
                },
            )
            assert updated is not None
            await self._sync_monthly_budget_field(updated)
            await self._resume_scope(updated)
            await resolve_open_budget_incidents_for_policy(
                self._session, updated.id, status="resolved"
            )
            status = "resolved"
        else:
            await resolve_budget_incident(
                self._session, incident.id, status="dismissed"
            )
            status = "dismissed"

        await insert_activity_log(
            self._session,
            org_id=incident.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="budget.incident_resolved",
            entity_type="budget_incident",
            entity_id=incident.id,
            details={"action": payload["action"], "amount": payload.get("amount")},
        )
        updated_incident = await get_budget_incident(self._session, incident.id)
        assert updated_incident is not None
        updated_incident.status = status
        return (await self._hydrate_incidents([updated_incident]))[0]

    async def _evaluate_policy(self, policy: BudgetPolicyRow, observed: int) -> None:
        soft_threshold = (policy.amount * policy.warn_percent + 99) // 100
        if policy.notify_enabled and observed >= soft_threshold:
            soft = await self._create_incident_if_needed(policy, "soft", observed)
            if soft is not None:
                await insert_activity_log(
                    self._session,
                    org_id=policy.org_id,
                    actor_type="system",
                    actor_id="budget_service",
                    action="budget.soft_threshold_crossed",
                    entity_type="budget_incident",
                    entity_id=soft.id,
                    details={
                        "scopeType": policy.scope_type,
                        "scopeId": policy.scope_id,
                    },
                )
        if policy.hard_stop_enabled and observed >= policy.amount:
            await resolve_open_budget_incidents_for_policy(
                self._session, policy.id, status="resolved"
            )
            hard = await self._create_incident_if_needed(policy, "hard", observed)
            await self._pause_and_cancel_scope(policy)
            if hard is not None:
                await insert_activity_log(
                    self._session,
                    org_id=policy.org_id,
                    actor_type="system",
                    actor_id="budget_service",
                    action="budget.hard_threshold_crossed",
                    entity_type="budget_incident",
                    entity_id=hard.id,
                    details={
                        "scopeType": policy.scope_type,
                        "scopeId": policy.scope_id,
                    },
                )

    async def _create_incident_if_needed(
        self, policy: BudgetPolicyRow, threshold_type: str, observed: int
    ) -> BudgetIncidentRow | None:
        start, end = _resolve_window(policy.window_kind)
        existing = await get_open_budget_incident(
            self._session,
            policy_id=policy.id,
            window_start=start,
            threshold_type=threshold_type,
        )
        if existing is not None:
            return None
        approval_id = None
        if threshold_type == "hard":
            approval = Approval(
                id=str(uuid.uuid4()),
                org_id=policy.org_id,
                type="budget_override_required",
                status="pending",
                payload={
                    "scopeType": policy.scope_type,
                    "scopeId": policy.scope_id,
                    "metric": policy.metric,
                    "windowKind": policy.window_kind,
                    "thresholdType": threshold_type,
                    "budgetAmount": policy.amount,
                    "observedAmount": observed,
                    "policyId": policy.id,
                    "guidance": "Raise the budget and resume the scope, or keep the scope paused.",
                },
            )
            self._session.add(approval)
            await self._session.flush()
            approval_id = approval.id
        return await create_budget_incident(
            self._session,
            {
                "id": str(uuid.uuid4()),
                "org_id": policy.org_id,
                "policy_id": policy.id,
                "scope_type": policy.scope_type,
                "scope_id": policy.scope_id,
                "metric": policy.metric,
                "window_kind": policy.window_kind,
                "window_start": start,
                "window_end": end,
                "threshold_type": threshold_type,
                "amount_limit": policy.amount,
                "amount_observed": observed,
                "status": "open",
                "approval_id": approval_id,
            },
        )

    async def _pause_and_cancel_scope(self, policy: BudgetPolicyRow) -> None:
        now = datetime.now(UTC)
        if policy.scope_type == "agent":
            await update_agent(
                self._session,
                policy.scope_id,
                {"status": "paused", "pause_reason": "budget", "paused_at": now},
            )
        elif policy.scope_type == "project":
            await update_project(
                self._session,
                policy.scope_id,
                {"pause_reason": "budget", "paused_at": now},
            )
        else:
            await update_organization(
                self._session,
                policy.scope_id,
                {"status": "paused", "pause_reason": "budget", "paused_at": now},
            )
        for run in await list_budget_scope_runs(
            self._session,
            org_id=policy.org_id,
            scope_type=policy.scope_type,
            scope_id=policy.scope_id,
        ):
            await update_run(
                self._session,
                run.id,
                {
                    "status": "cancelled",
                    "finished_at": now,
                    "error": "run cancelled by budget hard-stop",
                    "error_code": "budget_hard_stop",
                },
            )

    async def _resume_scope(self, policy: BudgetPolicyRow) -> None:
        if policy.scope_type == "agent":
            agent = await get_agent_by_id(self._session, policy.scope_id)
            if agent is not None and agent.pause_reason == "budget":
                await update_agent(
                    self._session,
                    policy.scope_id,
                    {"status": "idle", "pause_reason": None, "paused_at": None},
                )
        elif policy.scope_type == "project":
            project = await get_project_by_id(self._session, policy.scope_id)
            if project is not None and project.pause_reason == "budget":
                await update_project(
                    self._session,
                    policy.scope_id,
                    {"pause_reason": None, "paused_at": None},
                )
        else:
            org = await get_organization_by_id(self._session, policy.scope_id)
            if org is not None and org.pause_reason == "budget":
                await update_organization(
                    self._session,
                    policy.scope_id,
                    {"status": "active", "pause_reason": None, "paused_at": None},
                )

    async def _sync_monthly_budget_field(self, policy: BudgetPolicyRow) -> None:
        if policy.window_kind != "calendar_month_utc":
            return
        if policy.scope_type == "organization":
            await update_organization(
                self._session,
                policy.scope_id,
                {"budget_monthly_cents": policy.amount},
            )
        elif policy.scope_type == "agent":
            await update_agent(
                self._session,
                policy.scope_id,
                {"budget_monthly_cents": policy.amount},
            )

    async def _observed(self, policy: BudgetPolicyRow) -> int:
        start, end = _resolve_window(policy.window_kind)
        return await observed_budget_amount(
            self._session, policy, window_start=start, window_end=end
        )

    async def _summary(
        self,
        policy: BudgetPolicyRow,
        scope_name: str | None = None,
        paused: bool | None = None,
        pause_reason: str | None = None,
    ) -> BudgetPolicySummary:
        if scope_name is None or paused is None:
            scope_name, paused, pause_reason = await self._scope_state(
                cast(BudgetScopeType, policy.scope_type), policy.scope_id
            )
        observed = await self._observed(policy)
        start, end = _resolve_window(policy.window_kind)
        amount = policy.amount if policy.is_active else 0
        return {
            "policyId": policy.id,
            "orgId": policy.org_id,
            "scopeType": cast(BudgetScopeType, policy.scope_type),
            "scopeId": policy.scope_id,
            "scopeName": scope_name,
            "metric": cast("BudgetMetric", policy.metric),
            "windowKind": cast("BudgetWindowKind", policy.window_kind),
            "amount": amount,
            "observedAmount": observed,
            "remainingAmount": max(0, amount - observed) if amount > 0 else 0,
            "utilizationPercent": round((observed / amount) * 100, 2)
            if amount > 0
            else 0.0,
            "warnPercent": policy.warn_percent,
            "hardStopEnabled": policy.hard_stop_enabled,
            "notifyEnabled": policy.notify_enabled,
            "isActive": policy.is_active,
            "status": _policy_status(observed, amount, policy.warn_percent),
            "paused": paused,
            "pauseReason": cast("PauseReason | None", pause_reason),
            "windowStart": start.isoformat(),
            "windowEnd": end.isoformat(),
        }

    async def _hydrate_incidents(
        self, rows: Sequence[BudgetIncidentRow]
    ) -> list[BudgetIncident]:
        result: list[BudgetIncident] = []
        for row in rows:
            scope_name, _, _ = await self._scope_state(
                cast(BudgetScopeType, row.scope_type), row.scope_id
            )
            approval_status = None
            if row.approval_id:
                approval = await self._session.get(Approval, row.approval_id)
                approval_status = approval.status if approval is not None else None
            result.append(
                {
                    "id": row.id,
                    "orgId": row.org_id,
                    "policyId": row.policy_id,
                    "scopeType": cast(BudgetScopeType, row.scope_type),
                    "scopeId": row.scope_id,
                    "scopeName": scope_name,
                    "metric": cast("BudgetMetric", row.metric),
                    "windowKind": cast("BudgetWindowKind", row.window_kind),
                    "windowStart": row.window_start.isoformat(),
                    "windowEnd": row.window_end.isoformat(),
                    "thresholdType": cast("BudgetThresholdType", row.threshold_type),
                    "amountLimit": row.amount_limit,
                    "amountObserved": row.amount_observed,
                    "status": cast("BudgetIncidentStatus", row.status),
                    "approvalId": row.approval_id,
                    "approvalStatus": approval_status,
                    "resolvedAt": row.resolved_at.isoformat()
                    if row.resolved_at is not None
                    else None,
                    "createdAt": row.created_at.isoformat(),
                    "updatedAt": row.updated_at.isoformat(),
                }
            )
        return result

    async def _scope_state(
        self,
        scope_type: BudgetScopeType,
        scope_id: str,
        *,
        expected_org_id: str | None = None,
    ) -> tuple[str, bool, str | None]:
        if scope_type == "organization":
            org = await get_organization_by_id(self._session, scope_id)
            if org is None:
                raise LookupError("Organization not found")
            if expected_org_id is not None and org.id != expected_org_id:
                raise ValueError("Budget scope does not belong to organization")
            return (
                org.name,
                org.status == "paused" or org.paused_at is not None,
                org.pause_reason,
            )
        if scope_type == "agent":
            agent = await get_agent_by_id(self._session, scope_id)
            if agent is None:
                raise LookupError("Agent not found")
            if expected_org_id is not None and agent.org_id != expected_org_id:
                raise ValueError("Budget scope does not belong to organization")
            return agent.name, agent.status == "paused", agent.pause_reason
        project = await get_project_by_id(self._session, scope_id)
        if project is None:
            raise LookupError("Project not found")
        if expected_org_id is not None and project.org_id != expected_org_id:
            raise ValueError("Budget scope does not belong to organization")
        return project.name, project.paused_at is not None, project.pause_reason
