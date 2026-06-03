from __future__ import annotations

import pytest

from packages.shared.api_paths.approvals import (
    APPROVAL_APPROVE_PATH,
    APPROVAL_DETAIL_PATH,
    APPROVAL_REJECT_PATH,
    ORG_APPROVAL_LIST_PATH,
)
from packages.shared.api_paths.issues import (
    ISSUE_LIST_MISSING_ORG_PATH,
    ISSUE_DETAIL_PATH,
    ISSUE_COMMENT_LIST_PATH,
    ISSUE_REVIEW_DECISION_PATH,
    ORG_ISSUE_LIST_MISSING_ORG_PATH,
    ORG_ISSUE_LIST_PATH,
)
from packages.shared.api_paths.organizations import (
    ORG_ARCHIVE_PATH,
    ORG_DETAIL_PATH,
    ORG_LIST_PATH,
)
from packages.shared.constants.approval import (
    APPROVAL_STATUSES,
    APPROVAL_TYPES,
    DEFAULT_APPROVAL_STATUS,
)
from packages.shared.constants.issue import (
    DEFAULT_ISSUE_ORIGIN_KIND,
    DEFAULT_ISSUE_PRIORITY,
    DEFAULT_ISSUE_STATUS,
    ISSUE_ORIGIN_KINDS,
    ISSUE_PRIORITIES,
    ISSUE_STATUSES,
)
from packages.shared.constants.organization import (
    DEFAULT_ORGANIZATION_STATUS,
    ORGANIZATION_STATUSES,
)
from packages.shared.validators.approval import (
    validate_create_approval,
    validate_list_org_approvals_query,
    validate_resolve_approval,
)
from packages.shared.validators.issue import (
    validate_create_issue_comment,
    validate_create_issue,
    validate_list_org_issues_query,
    validate_record_issue_review_decision,
    validate_update_issue,
)
from packages.shared.validators.organization import (
    validate_create_organization,
    validate_update_organization,
)


def test_org_paths_values() -> None:
    assert ORG_LIST_PATH == "/api/orgs"
    assert ORG_DETAIL_PATH == "/api/orgs/{orgId}"
    assert ORG_ARCHIVE_PATH == "/api/orgs/{orgId}/archive"


def test_issue_paths_values() -> None:
    assert ISSUE_LIST_MISSING_ORG_PATH == "/api/issues"
    assert ORG_ISSUE_LIST_MISSING_ORG_PATH == "/api/orgs/issues"
    assert ORG_ISSUE_LIST_PATH == "/api/orgs/{orgId}/issues"
    assert ISSUE_DETAIL_PATH == "/api/issues/{id}"
    assert ISSUE_COMMENT_LIST_PATH == "/api/issues/{id}/comments"
    assert ISSUE_REVIEW_DECISION_PATH == "/api/issues/{id}/review-decision"


def test_approval_paths_values() -> None:
    assert ORG_APPROVAL_LIST_PATH == "/api/orgs/{orgId}/approvals"
    assert APPROVAL_DETAIL_PATH == "/api/approvals/{id}"
    assert APPROVAL_APPROVE_PATH == "/api/approvals/{id}/approve"
    assert APPROVAL_REJECT_PATH == "/api/approvals/{id}/reject"


def test_organization_statuses_match_contract() -> None:
    assert ORGANIZATION_STATUSES == ("active", "paused", "archived")
    assert DEFAULT_ORGANIZATION_STATUS == "active"


def test_issue_statuses_match_contract() -> None:
    assert ISSUE_STATUSES == (
        "backlog",
        "todo",
        "in_progress",
        "in_review",
        "done",
        "blocked",
        "cancelled",
    )
    assert DEFAULT_ISSUE_STATUS == "backlog"


def test_issue_priorities_match_contract() -> None:
    assert ISSUE_PRIORITIES == ("critical", "high", "medium", "low")
    assert DEFAULT_ISSUE_PRIORITY == "medium"


def test_issue_origin_kinds_match_contract() -> None:
    assert ISSUE_ORIGIN_KINDS == ("manual", "automation_execution")
    assert DEFAULT_ISSUE_ORIGIN_KIND == "manual"


def test_approval_types_match_contract() -> None:
    assert APPROVAL_TYPES == (
        "hire_agent",
        "approve_ceo_strategy",
        "budget_override_required",
        "chat_issue_creation",
        "chat_operation",
    )


def test_approval_statuses_match_contract() -> None:
    assert APPROVAL_STATUSES == (
        "pending",
        "revision_requested",
        "approved",
        "rejected",
        "cancelled",
    )
    assert DEFAULT_APPROVAL_STATUS == "pending"


def test_validate_create_organization_happy() -> None:
    payload = validate_create_organization({"name": "Acme"})
    assert payload["name"] == "Acme"


def test_validate_create_organization_missing_name_raises() -> None:
    with pytest.raises(ValueError, match="name"):
        validate_create_organization({})


def test_validate_create_organization_blank_name_raises() -> None:
    with pytest.raises(ValueError, match="name"):
        validate_create_organization({"name": "   "})


def test_validate_create_organization_negative_budget_raises() -> None:
    with pytest.raises(ValueError, match="budgetMonthlyCents"):
        validate_create_organization({"name": "X", "budgetMonthlyCents": -1})


def test_validate_update_organization_empty_ok() -> None:
    payload = validate_update_organization({})
    assert payload == {}


def test_validate_update_organization_invalid_bool_raises() -> None:
    with pytest.raises(ValueError, match="requireBoardApprovalForNewAgents"):
        validate_update_organization({"requireBoardApprovalForNewAgents": "yes"})


def test_validate_create_issue_happy() -> None:
    payload = validate_create_issue(
        {
            "title": "Demo issue",
            "createdByAgentId": "agent-1",
            "createdByUserId": None,
        }
    )
    assert payload["title"] == "Demo issue"
    assert payload.get("createdByAgentId") == "agent-1"
    assert payload.get("createdByUserId") is None


def test_validate_create_issue_missing_title_raises() -> None:
    with pytest.raises(ValueError, match="title"):
        validate_create_issue({})


def test_validate_create_issue_invalid_status_raises() -> None:
    with pytest.raises(ValueError, match="status"):
        validate_create_issue({"title": "X", "status": "wat"})


def test_validate_create_issue_invalid_priority_raises() -> None:
    with pytest.raises(ValueError, match="priority"):
        validate_create_issue({"title": "X", "priority": "urgent"})


def test_validate_create_issue_unknown_field_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported field"):
        validate_create_issue({"title": "X", "workspaceConfig": {}})


def test_validate_list_org_issues_query_happy() -> None:
    query = validate_list_org_issues_query({"status": "todo", "assigneeAgentId": "a1"})
    assert query.get("status") == "todo"
    assert query.get("assigneeAgentId") == "a1"


def test_validate_list_org_issues_query_invalid_status_raises() -> None:
    with pytest.raises(ValueError, match="status"):
        validate_list_org_issues_query({"status": "nope"})


def test_validate_update_issue_blank_comment_raises() -> None:
    with pytest.raises(ValueError, match="comment"):
        validate_update_issue({"comment": "   "})


def test_validate_update_issue_unknown_field_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported field"):
        validate_update_issue({"foo": "bar"})


def test_validate_create_issue_comment_happy() -> None:
    payload = validate_create_issue_comment({"body": "Looks good"})
    assert payload["body"] == "Looks good"


def test_validate_create_issue_comment_blank_body_raises() -> None:
    with pytest.raises(ValueError, match="body"):
        validate_create_issue_comment({"body": "   "})


def test_validate_create_issue_comment_unknown_field_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported field"):
        validate_create_issue_comment({"body": "ok", "author": "x"})


def test_validate_record_issue_review_decision_happy() -> None:
    payload = validate_record_issue_review_decision({"decision": "approve"})
    assert payload["decision"] == "approve"


def test_validate_record_issue_review_decision_invalid_decision_raises() -> None:
    with pytest.raises(ValueError, match="decision"):
        validate_record_issue_review_decision({"decision": "ship_it"})


def test_validate_record_issue_review_decision_unknown_field_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported field"):
        validate_record_issue_review_decision({"decision": "approve", "status": "done"})


def test_validate_create_approval_happy() -> None:
    payload = validate_create_approval(
        {"type": "hire_agent", "payload": {"agentId": "a1"}}
    )
    assert payload["type"] == "hire_agent"


def test_validate_create_approval_invalid_type_raises() -> None:
    with pytest.raises(ValueError, match="type"):
        validate_create_approval({"type": "nope", "payload": {}})


def test_validate_create_approval_missing_payload_raises() -> None:
    with pytest.raises(ValueError, match="payload"):
        validate_create_approval({"type": "hire_agent"})


def test_validate_list_org_approvals_query_invalid_status_raises() -> None:
    with pytest.raises(ValueError, match="status"):
        validate_list_org_approvals_query({"status": "draft"})


def test_validate_resolve_approval_empty_ok() -> None:
    # Upstream `resolveApprovalSchema.decidedByUserId.default("board")` in
    # `packages/shared/src/validators/approval.ts:15` applies the board
    # default when the caller omits the field.
    result = validate_resolve_approval({})
    assert result == {"decidedByUserId": "board"}


def test_validate_resolve_approval_invalid_note_type_raises() -> None:
    with pytest.raises(ValueError, match="decisionNote"):
        validate_resolve_approval({"decisionNote": 42})
