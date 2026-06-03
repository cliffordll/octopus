from __future__ import annotations

from typing import NotRequired, TypedDict

from ..constants.organization import OrganizationStatus


class OrganizationSummary(TypedDict):
    id: str
    urlKey: str
    name: str
    status: OrganizationStatus


class OrganizationDetail(OrganizationSummary):
    description: str | None
    issuePrefix: str
    issueCounter: int
    budgetMonthlyCents: int
    spentMonthlyCents: int
    requireBoardApprovalForNewAgents: bool
    defaultChatIssueCreationMode: str
    brandColor: str | None
    createdAt: str
    updatedAt: str


class CreateOrganizationPayload(TypedDict):
    name: str
    description: NotRequired[str | None]
    budgetMonthlyCents: NotRequired[int]
    defaultChatIssueCreationMode: NotRequired[str]
    brandColor: NotRequired[str | None]
    requireBoardApprovalForNewAgents: NotRequired[bool]


class UpdateOrganizationPayload(TypedDict, total=False):
    name: str
    description: str | None
    budgetMonthlyCents: int
    defaultChatIssueCreationMode: str
    brandColor: str | None
    requireBoardApprovalForNewAgents: bool
