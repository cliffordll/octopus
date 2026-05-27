from __future__ import annotations

from typing import Literal

ProjectStatus = Literal["backlog", "planned", "in_progress", "completed", "cancelled"]
PROJECT_STATUSES: tuple[ProjectStatus, ...] = (
    "backlog",
    "planned",
    "in_progress",
    "completed",
    "cancelled",
)
DEFAULT_PROJECT_STATUS: ProjectStatus = "backlog"

PauseReason = Literal["manual", "budget", "system"]
PAUSE_REASONS: tuple[PauseReason, ...] = ("manual", "budget", "system")

OrganizationResourceKind = Literal["file", "directory", "url", "connector_object"]
ORGANIZATION_RESOURCE_KINDS: tuple[OrganizationResourceKind, ...] = (
    "file",
    "directory",
    "url",
    "connector_object",
)

ProjectResourceAttachmentRole = Literal[
    "working_set", "reference", "tracking", "deliverable", "background"
]
PROJECT_RESOURCE_ATTACHMENT_ROLES: tuple[ProjectResourceAttachmentRole, ...] = (
    "working_set",
    "reference",
    "tracking",
    "deliverable",
    "background",
)

PROJECT_COLORS: tuple[str, ...] = (
    "linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)",
    "linear-gradient(135deg, #7c3aed 0%, #d946ef 100%)",
    "linear-gradient(135deg, #db2777 0%, #f97316 100%)",
    "linear-gradient(135deg, #ef4444 0%, #f59e0b 100%)",
    "linear-gradient(135deg, #f97316 0%, #facc15 100%)",
    "linear-gradient(135deg, #10b981 0%, #84cc16 100%)",
    "linear-gradient(135deg, #059669 0%, #14b8a6 100%)",
    "linear-gradient(135deg, #0d9488 0%, #06b6d4 100%)",
    "linear-gradient(135deg, #0284c7 0%, #2563eb 100%)",
    "linear-gradient(135deg, #2563eb 0%, #4f46e5 100%)",
    "linear-gradient(135deg, #f43f5e 0%, #ec4899 100%)",
    "linear-gradient(135deg, #be123c 0%, #7c2d12 100%)",
    "linear-gradient(135deg, #a16207 0%, #ca8a04 100%)",
    "linear-gradient(135deg, #16a34a 0%, #0f766e 100%)",
    "linear-gradient(135deg, #0891b2 0%, #4338ca 100%)",
    "linear-gradient(135deg, #6d28d9 0%, #be185d 100%)",
    "linear-gradient(135deg, #475569 0%, #0f766e 100%)",
    "linear-gradient(135deg, #334155 0%, #7c3aed 100%)",
)
