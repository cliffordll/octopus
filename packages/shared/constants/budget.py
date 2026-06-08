from __future__ import annotations

from typing import Literal

BudgetScopeType = Literal["organization", "agent", "project"]
BUDGET_SCOPE_TYPES: tuple[BudgetScopeType, ...] = (
    "organization",
    "agent",
    "project",
)

BudgetMetric = Literal["billed_cents"]
BUDGET_METRICS: tuple[BudgetMetric, ...] = ("billed_cents",)

BudgetWindowKind = Literal["calendar_month_utc", "lifetime"]
BUDGET_WINDOW_KINDS: tuple[BudgetWindowKind, ...] = (
    "calendar_month_utc",
    "lifetime",
)

BudgetThresholdType = Literal["soft", "hard"]
BUDGET_THRESHOLD_TYPES: tuple[BudgetThresholdType, ...] = ("soft", "hard")

BudgetIncidentStatus = Literal["open", "resolved", "dismissed"]
BUDGET_INCIDENT_STATUSES: tuple[BudgetIncidentStatus, ...] = (
    "open",
    "resolved",
    "dismissed",
)

BudgetIncidentResolutionAction = Literal["raise_budget_and_resume", "dismiss"]
BUDGET_INCIDENT_RESOLUTION_ACTIONS: tuple[BudgetIncidentResolutionAction, ...] = (
    "raise_budget_and_resume",
    "dismiss",
)
