from __future__ import annotations

from typing import Any, cast

from packages.shared.constants.budget import (
    BUDGET_INCIDENT_RESOLUTION_ACTIONS,
    BUDGET_METRICS,
    BUDGET_SCOPE_TYPES,
    BUDGET_WINDOW_KINDS,
)
from packages.shared.types.budget import (
    BudgetIncidentResolutionInput,
    BudgetPolicyUpsertInput,
)

_POLICY_FIELDS = {
    "scopeType",
    "scopeId",
    "metric",
    "windowKind",
    "amount",
    "warnPercent",
    "hardStopEnabled",
    "notifyEnabled",
    "isActive",
}
_RESOLUTION_FIELDS = {"action", "amount", "decisionNote"}
_BUDGET_PATCH_FIELDS = {"budgetMonthlyCents"}


def validate_upsert_budget_policy(payload: dict[str, Any]) -> BudgetPolicyUpsertInput:
    unknown = set(payload) - _POLICY_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

    scope_type = _choice(payload.get("scopeType"), "scopeType", BUDGET_SCOPE_TYPES)
    scope_id = _required_string(payload.get("scopeId"), "scopeId")
    metric = _choice(payload.get("metric", "billed_cents"), "metric", BUDGET_METRICS)
    window_kind = _choice(
        payload.get("windowKind", "calendar_month_utc"),
        "windowKind",
        BUDGET_WINDOW_KINDS,
    )
    return cast(
        BudgetPolicyUpsertInput,
        {
            "scopeType": scope_type,
            "scopeId": scope_id,
            "metric": metric,
            "windowKind": window_kind,
            "amount": _nonnegative_int(payload.get("amount"), "amount"),
            "warnPercent": _int_between(
                payload.get("warnPercent", 80), "warnPercent", 1, 99
            ),
            "hardStopEnabled": _optional_bool(
                payload.get("hardStopEnabled", True), "hardStopEnabled"
            ),
            "notifyEnabled": _optional_bool(
                payload.get("notifyEnabled", True), "notifyEnabled"
            ),
            "isActive": _optional_bool(payload.get("isActive", True), "isActive"),
        },
    )


def validate_resolve_budget_incident(
    payload: dict[str, Any],
) -> BudgetIncidentResolutionInput:
    unknown = set(payload) - _RESOLUTION_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")

    action = _choice(
        payload.get("action"),
        "action",
        BUDGET_INCIDENT_RESOLUTION_ACTIONS,
    )
    result: dict[str, Any] = {"action": action}
    if action == "raise_budget_and_resume":
        if "amount" not in payload:
            raise ValueError("amount is required when raising a budget")
        result["amount"] = _nonnegative_int(payload["amount"], "amount")
    elif "amount" in payload:
        result["amount"] = _nonnegative_int(payload["amount"], "amount")
    if "decisionNote" in payload:
        value = payload["decisionNote"]
        if value is not None and not isinstance(value, str):
            raise ValueError("decisionNote must be a string or null")
        result["decisionNote"] = value
    return cast(BudgetIncidentResolutionInput, result)


def validate_budget_amount_patch(payload: dict[str, Any]) -> int:
    unknown = set(payload) - _BUDGET_PATCH_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {', '.join(sorted(unknown))}")
    if "budgetMonthlyCents" not in payload:
        raise ValueError("budgetMonthlyCents is required")
    return _nonnegative_int(payload["budgetMonthlyCents"], "budgetMonthlyCents")


def _choice(value: Any, field: str, choices: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in choices:
        raise ValueError(f"{field} must be one of: {', '.join(choices)}")
    return value


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _int_between(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field} must be an integer")
    if value < minimum or value > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return value


def _optional_bool(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be a boolean")
    return value
