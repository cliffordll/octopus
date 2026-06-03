from __future__ import annotations

from typing import NotRequired, TypedDict

OrganizationSkillSourceType = str
OrganizationSkillTrustLevel = str
OrganizationSkillCompatibility = str
OrganizationSkillSourceBadge = str


class OrganizationSkillFileInventoryEntry(TypedDict):
    path: str
    kind: str


class OrganizationSkill(TypedDict):
    id: str
    orgId: str
    key: str
    slug: str
    name: str
    description: str | None
    markdown: str
    sourceType: OrganizationSkillSourceType
    sourceLocator: str | None
    sourceRef: str | None
    trustLevel: OrganizationSkillTrustLevel
    compatibility: OrganizationSkillCompatibility
    fileInventory: list[OrganizationSkillFileInventoryEntry]
    metadata: dict[str, object] | None
    createdAt: str
    updatedAt: str


class OrganizationSkillListItem(OrganizationSkill):
    attachedAgentCount: int
    editable: bool
    editableReason: str | None
    sourceLabel: str | None
    sourceBadge: OrganizationSkillSourceBadge
    sourcePath: str | None
    workspaceEditPath: str | None


class OrganizationSkillUsageAgent(TypedDict):
    id: str
    name: str
    urlKey: str
    agentRuntimeType: str
    desired: bool
    actualState: str | None


class OrganizationSkillDetail(OrganizationSkillListItem):
    usedByAgents: list[OrganizationSkillUsageAgent]


class OrganizationSkillUpdateStatus(TypedDict):
    supported: bool
    reason: str | None
    trackingRef: str | None
    currentRef: str | None
    latestRef: str | None
    hasUpdate: bool


class OrganizationSkillScanCandidate(TypedDict):
    sourcePath: str
    slug: str
    name: str
    description: str | None
    sourceRef: str
    alreadyImported: bool
    skillId: str | None


class OrganizationSkillScanLocalResult(TypedDict):
    candidates: list[OrganizationSkillScanCandidate]
    imported: list[OrganizationSkill]


class OrganizationSkillFileDetail(TypedDict):
    skillId: str
    path: str
    kind: str
    content: str
    language: str | None
    markdown: bool
    editable: bool


class OrganizationSkillCreatePayload(TypedDict):
    name: str
    slug: NotRequired[str | None]
    description: NotRequired[str | None]
    markdown: NotRequired[str | None]


class OrganizationSkillImportPayload(TypedDict):
    sourcePath: str
    slug: NotRequired[str | None]
    name: NotRequired[str | None]
    description: NotRequired[str | None]
    overwrite: NotRequired[bool]


class OrganizationSkillScanLocalPayload(TypedDict):
    rootPath: str
    importDiscovered: NotRequired[bool]
    overwrite: NotRequired[bool]


class OrganizationSkillFileUpdatePayload(TypedDict):
    path: str
    content: str
