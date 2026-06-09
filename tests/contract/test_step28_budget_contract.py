from __future__ import annotations

from sqlalchemy import inspect

from packages.database.schema import BudgetIncident, BudgetPolicy
from packages.shared.constants.budget import (
    BUDGET_INCIDENT_RESOLUTION_ACTIONS,
    BUDGET_INCIDENT_STATUSES,
    BUDGET_METRICS,
    BUDGET_SCOPE_TYPES,
    BUDGET_THRESHOLD_TYPES,
    BUDGET_WINDOW_KINDS,
)
from packages.shared.validators.budget import (
    validate_resolve_budget_incident,
    validate_upsert_budget_policy,
)


def test_step28_budget_constants_match_governance_contract() -> None:
    assert BUDGET_SCOPE_TYPES == ("organization", "agent", "project")
    assert BUDGET_METRICS == ("billed_cents",)
    assert BUDGET_WINDOW_KINDS == ("calendar_month_utc", "lifetime")
    assert BUDGET_THRESHOLD_TYPES == ("soft", "hard")
    assert BUDGET_INCIDENT_STATUSES == ("open", "resolved", "dismissed")
    assert BUDGET_INCIDENT_RESOLUTION_ACTIONS == (
        "raise_budget_and_resume",
        "dismiss",
    )


def test_step28_budget_validators_apply_upstream_defaults() -> None:
    policy = validate_upsert_budget_policy(
        {
            "scopeType": "agent",
            "scopeId": "agent-1",
            "amount": 1200,
        }
    )
    assert policy == {
        "scopeType": "agent",
        "scopeId": "agent-1",
        "metric": "billed_cents",
        "windowKind": "calendar_month_utc",
        "amount": 1200,
        "warnPercent": 80,
        "hardStopEnabled": True,
        "notifyEnabled": True,
        "isActive": True,
    }

    resolution = validate_resolve_budget_incident(
        {
            "action": "raise_budget_and_resume",
            "amount": 2500,
            "decisionNote": "approved",
        }
    )
    assert resolution["action"] == "raise_budget_and_resume"
    assert resolution.get("amount") == 2500


def test_step28_budget_validators_reject_invalid_values() -> None:
    invalid_inputs = [
        {"scopeType": "user", "scopeId": "x", "amount": 1},
        {"scopeType": "agent", "scopeId": "x", "metric": "tokens", "amount": 1},
        {"scopeType": "agent", "scopeId": "x", "windowKind": "day", "amount": 1},
        {"scopeType": "agent", "scopeId": "x", "amount": -1},
        {"scopeType": "agent", "scopeId": "x", "amount": 1, "warnPercent": 100},
    ]
    for payload in invalid_inputs:
        try:
            validate_upsert_budget_policy(payload)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Expected invalid budget policy: {payload}")

    for payload in [
        {"action": "raise_budget_and_resume"},
        {"action": "raise_budget_and_resume", "amount": -1},
        {"action": "ignore"},
    ]:
        try:
            validate_resolve_budget_incident(payload)
        except ValueError:
            pass
        else:
            raise AssertionError(
                f"Expected invalid budget incident resolution: {payload}"
            )


def test_step28_budget_schema_matches_expected_tables_and_columns() -> None:
    policy_columns = set(inspect(BudgetPolicy).columns.keys())
    incident_columns = set(inspect(BudgetIncident).columns.keys())

    assert BudgetPolicy.__tablename__ == "budget_policies"
    assert {
        "id",
        "org_id",
        "scope_type",
        "scope_id",
        "metric",
        "window_kind",
        "amount",
        "warn_percent",
        "hard_stop_enabled",
        "notify_enabled",
        "is_active",
        "created_by_user_id",
        "updated_by_user_id",
        "created_at",
        "updated_at",
    } <= policy_columns

    assert BudgetIncident.__tablename__ == "budget_incidents"
    assert {
        "id",
        "org_id",
        "policy_id",
        "scope_type",
        "scope_id",
        "metric",
        "window_kind",
        "window_start",
        "window_end",
        "threshold_type",
        "amount_limit",
        "amount_observed",
        "status",
        "approval_id",
        "resolved_at",
        "created_at",
        "updated_at",
    } <= incident_columns
