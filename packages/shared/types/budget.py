from __future__ import annotations

from typing import NotRequired, TypedDict

from packages.shared.constants.agent import PauseReason
from packages.shared.constants.budget import (
    BudgetIncidentResolutionAction,
    BudgetIncidentStatus,
    BudgetMetric,
    BudgetScopeType,
    BudgetThresholdType,
    BudgetWindowKind,
)


class BudgetPolicy(TypedDict):
    id: str
    orgId: str
    scopeType: BudgetScopeType
    scopeId: str
    metric: BudgetMetric
    windowKind: BudgetWindowKind
    amount: int
    warnPercent: int
    hardStopEnabled: bool
    notifyEnabled: bool
    isActive: bool
    createdByUserId: str | None
    updatedByUserId: str | None
    createdAt: str
    updatedAt: str


class BudgetPolicySummary(TypedDict):
    policyId: str
    orgId: str
    scopeType: BudgetScopeType
    scopeId: str
    scopeName: str
    metric: BudgetMetric
    windowKind: BudgetWindowKind
    amount: int
    observedAmount: int
    remainingAmount: int
    utilizationPercent: float
    warnPercent: int
    hardStopEnabled: bool
    notifyEnabled: bool
    isActive: bool
    status: str
    paused: bool
    pauseReason: PauseReason | None
    windowStart: str
    windowEnd: str


class BudgetIncident(TypedDict):
    id: str
    orgId: str
    policyId: str
    scopeType: BudgetScopeType
    scopeId: str
    scopeName: str
    metric: BudgetMetric
    windowKind: BudgetWindowKind
    windowStart: str
    windowEnd: str
    thresholdType: BudgetThresholdType
    amountLimit: int
    amountObserved: int
    status: BudgetIncidentStatus
    approvalId: str | None
    approvalStatus: str | None
    resolvedAt: str | None
    createdAt: str
    updatedAt: str


class BudgetOverview(TypedDict):
    orgId: str
    policies: list[BudgetPolicySummary]
    activeIncidents: list[BudgetIncident]
    pausedAgentCount: int
    pausedProjectCount: int
    pendingApprovalCount: int


class BudgetPolicyUpsertInput(TypedDict):
    scopeType: BudgetScopeType
    scopeId: str
    metric: BudgetMetric
    windowKind: BudgetWindowKind
    amount: int
    warnPercent: int
    hardStopEnabled: bool
    notifyEnabled: bool
    isActive: bool


class BudgetIncidentResolutionInput(TypedDict):
    action: BudgetIncidentResolutionAction
    amount: NotRequired[int]
    decisionNote: NotRequired[str | None]
