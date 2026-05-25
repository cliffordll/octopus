from __future__ import annotations

from typing import Literal

OrganizationStatus = Literal["active", "paused", "archived"]

ORGANIZATION_STATUSES: tuple[OrganizationStatus, ...] = (
    "active",
    "paused",
    "archived",
)

DEFAULT_ORGANIZATION_STATUS: OrganizationStatus = "active"
