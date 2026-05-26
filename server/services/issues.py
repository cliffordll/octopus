from __future__ import annotations

from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.issues import (
    get_issue_by_id,
    list_org_issues,
)
from packages.database.schema import Issue
from packages.shared.constants.issue import (
    IssueOriginKind,
    IssuePriority,
    IssueStatus,
)
from packages.shared.types.issue import IssueDetail, IssueListItem


class IssueService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(
        self,
        org_id: str,
        *,
        status: str | None = None,
        assignee_agent_id: str | None = None,
    ) -> list[IssueListItem]:
        rows = await list_org_issues(
            self._session,
            org_id,
            status=status,
            assignee_agent_id=assignee_agent_id,
        )
        return [_to_list_item(row) for row in rows]

    async def get_by_id(self, issue_id: str) -> IssueDetail | None:
        row = await get_issue_by_id(self._session, issue_id)
        if row is None:
            return None
        return _to_detail(row)


def _to_list_item(row: Issue) -> IssueListItem:
    return IssueListItem(
        id=row.id,
        orgId=row.org_id,
        identifier=row.identifier,
        title=row.title,
        status=cast(IssueStatus, row.status),
        priority=cast(IssuePriority, row.priority),
        assigneeAgentId=row.assignee_agent_id,
        assigneeUserId=row.assignee_user_id,
        updatedAt=row.updated_at.isoformat(),
    )


def _to_detail(row: Issue) -> IssueDetail:
    return IssueDetail(
        id=row.id,
        orgId=row.org_id,
        identifier=row.identifier,
        title=row.title,
        status=cast(IssueStatus, row.status),
        priority=cast(IssuePriority, row.priority),
        assigneeAgentId=row.assignee_agent_id,
        assigneeUserId=row.assignee_user_id,
        updatedAt=row.updated_at.isoformat(),
        description=row.description,
        reviewerAgentId=row.reviewer_agent_id,
        reviewerUserId=row.reviewer_user_id,
        projectId=row.project_id,
        goalId=row.goal_id,
        parentId=row.parent_id,
        originKind=cast(IssueOriginKind, row.origin_kind),
        originId=row.origin_id,
        issueNumber=row.issue_number,
        requestDepth=row.request_depth,
        startedAt=row.started_at.isoformat() if row.started_at else None,
        completedAt=row.completed_at.isoformat() if row.completed_at else None,
        createdAt=row.created_at.isoformat(),
    )
