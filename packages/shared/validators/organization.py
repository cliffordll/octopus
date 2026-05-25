from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from ..types.organization import (
    CreateOrganizationPayload,
    UpdateOrganizationPayload,
)


def _check_optional_org_fields(payload: Mapping[str, Any]) -> None:
    if "description" in payload:
        desc = payload["description"]
        if desc is not None and not isinstance(desc, str):
            raise ValueError("'description' must be a string or null")

    if "budgetMonthlyCents" in payload:
        budget = payload["budgetMonthlyCents"]
        if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
            raise ValueError("'budgetMonthlyCents' must be a non-negative integer")

    if "brandColor" in payload:
        color = payload["brandColor"]
        if color is not None and not isinstance(color, str):
            raise ValueError("'brandColor' must be a string or null")

    if "requireBoardApprovalForNewAgents" in payload:
        if not isinstance(payload["requireBoardApprovalForNewAgents"], bool):
            raise ValueError("'requireBoardApprovalForNewAgents' must be a boolean")

    if "defaultChatIssueCreationMode" in payload:
        mode = payload["defaultChatIssueCreationMode"]
        if not isinstance(mode, str) or not mode.strip():
            raise ValueError(
                "'defaultChatIssueCreationMode' must be a non-empty string"
            )


def validate_create_organization(
    payload: Mapping[str, Any],
) -> CreateOrganizationPayload:
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("'name' is required and must be a non-empty string")
    _check_optional_org_fields(payload)
    return cast(CreateOrganizationPayload, payload)


def validate_update_organization(
    payload: Mapping[str, Any],
) -> UpdateOrganizationPayload:
    if "name" in payload:
        name = payload["name"]
        if not isinstance(name, str) or not name.strip():
            raise ValueError("'name' must be a non-empty string when provided")
    _check_optional_org_fields(payload)
    return cast(UpdateOrganizationPayload, payload)
