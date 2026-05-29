from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from ..constants.project import OrganizationResourceKind


class OrganizationResource(TypedDict):
    id: str
    orgId: str
    name: str
    kind: OrganizationResourceKind
    locator: str
    description: str | None
    metadata: dict[str, Any] | None
    createdAt: str
    updatedAt: str


class CreateOrganizationResourcePayload(TypedDict):
    name: str
    kind: OrganizationResourceKind
    locator: str
    description: NotRequired[str | None]
    metadata: NotRequired[dict[str, Any] | None]


class UpdateOrganizationResourcePayload(TypedDict, total=False):
    name: str
    kind: OrganizationResourceKind
    locator: str
    description: str | None
    metadata: dict[str, Any] | None
