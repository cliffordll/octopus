from __future__ import annotations

from collections.abc import Mapping
import uuid
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.organizations import (
    create_organization,
    get_organization_by_id,
    list_organizations,
    update_organization,
)
from packages.database.schema import Organization
from packages.shared.constants.organization import OrganizationStatus
from packages.shared.types.organization import OrganizationDetail, OrganizationSummary

ORG_UPDATE_TO_COLUMN: dict[str, str] = {
    "name": "name",
    "description": "description",
    "budgetMonthlyCents": "budget_monthly_cents",
    "defaultChatIssueCreationMode": "default_chat_issue_creation_mode",
    "brandColor": "brand_color",
    "requireBoardApprovalForNewAgents": "require_board_approval_for_new_agents",
}


class OrgService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[OrganizationSummary]:
        rows = await list_organizations(self._session)
        return [
            OrganizationSummary(
                id=row.id,
                urlKey=row.url_key,
                name=row.name,
                status=cast(OrganizationStatus, row.status),
            )
            for row in rows
        ]

    async def get(self, org_id: str) -> OrganizationDetail | None:
        row = await get_organization_by_id(self._session, org_id)
        if row is None:
            return None
        return _to_detail(row)

    async def create(
        self,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationDetail:
        org_id = str(uuid.uuid4())
        row = await create_organization(
            self._session,
            id=org_id,
            url_key=f"org-{org_id[:8]}",
            name=str(payload["name"]).strip(),
            description=cast(str | None, payload.get("description")),
            issue_prefix=org_id[:6].upper(),
            budget_monthly_cents=cast(int, payload.get("budgetMonthlyCents", 0)),
            default_chat_issue_creation_mode=cast(
                str, payload.get("defaultChatIssueCreationMode", "manual_approval")
            ),
            brand_color=cast(str | None, payload.get("brandColor")),
            require_board_approval_for_new_agents=cast(
                bool, payload.get("requireBoardApprovalForNewAgents", True)
            ),
        )
        await insert_activity_log(
            self._session,
            org_id=row.id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.created",
            entity_type="organization",
            entity_id=row.id,
            details=dict(payload),
        )
        return _to_detail(row)

    async def update(
        self,
        org_id: str,
        payload: Mapping[str, Any],
        *,
        actor_type: str,
        actor_id: str,
    ) -> OrganizationDetail | None:
        column_updates = {
            ORG_UPDATE_TO_COLUMN[key]: value
            for key, value in payload.items()
            if key in ORG_UPDATE_TO_COLUMN
        }

        if not column_updates:
            row = await get_organization_by_id(self._session, org_id)
            return _to_detail(row) if row is not None else None

        updated = await update_organization(self._session, org_id, column_updates)
        if updated is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="organization.updated",
            entity_type="organization",
            entity_id=org_id,
            details=dict(payload),
        )
        return _to_detail(updated)


def _to_detail(row: Organization) -> OrganizationDetail:
    return OrganizationDetail(
        id=row.id,
        urlKey=row.url_key,
        name=row.name,
        status=cast(OrganizationStatus, row.status),
        description=row.description,
        issuePrefix=row.issue_prefix,
        issueCounter=row.issue_counter,
        budgetMonthlyCents=row.budget_monthly_cents,
        spentMonthlyCents=row.spent_monthly_cents,
        brandColor=row.brand_color,
        createdAt=row.created_at.isoformat(),
        updatedAt=row.updated_at.isoformat(),
    )
