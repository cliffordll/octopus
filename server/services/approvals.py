from __future__ import annotations

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.approvals import (
    get_approval_by_id,
    list_org_approvals,
)
from packages.database.schema import Approval
from packages.shared.constants.approval import ApprovalStatus, ApprovalType
from packages.shared.types.approval import ApprovalDetail, ApprovalListItem


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self,
        org_id: str,
        *,
        status: str | None = None,
    ) -> list[ApprovalListItem]:
        rows = await list_org_approvals(self._session, org_id, status=status)
        return [_to_list_item(row) for row in rows]

    async def get_by_id(self, approval_id: str) -> ApprovalDetail | None:
        row = await get_approval_by_id(self._session, approval_id)
        if row is None:
            return None
        return _to_detail(row)


def _to_list_item(row: Approval) -> ApprovalListItem:
    return ApprovalListItem(
        id=row.id,
        orgId=row.org_id,
        type=cast(ApprovalType, row.type),
        status=cast(ApprovalStatus, row.status),
        requestedByAgentId=row.requested_by_agent_id,
        requestedByUserId=row.requested_by_user_id,
        createdAt=row.created_at.isoformat(),
    )


def _to_detail(row: Approval) -> ApprovalDetail:
    return ApprovalDetail(
        id=row.id,
        orgId=row.org_id,
        type=cast(ApprovalType, row.type),
        status=cast(ApprovalStatus, row.status),
        requestedByAgentId=row.requested_by_agent_id,
        requestedByUserId=row.requested_by_user_id,
        createdAt=row.created_at.isoformat(),
        payload=row.payload,
        decisionNote=row.decision_note,
        decidedByUserId=row.decided_by_user_id,
        decidedAt=row.decided_at.isoformat() if row.decided_at else None,
        updatedAt=row.updated_at.isoformat(),
    )
