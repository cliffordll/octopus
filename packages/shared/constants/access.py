from __future__ import annotations

from typing import Final, Literal


MembershipPrincipalType = Literal["user", "agent"]
MembershipStatus = Literal["pending", "active", "suspended"]
InstanceUserRole = Literal["instance_admin"]
PermissionKey = Literal[
    "agents:create",
    "skills:manage",
    "users:invite",
    "users:manage_permissions",
    "tasks:assign",
    "tasks:assign_scope",
    "joins:approve",
]

MEMBERSHIP_PRINCIPAL_TYPES: Final[tuple[MembershipPrincipalType, ...]] = (
    "user",
    "agent",
)
MEMBERSHIP_STATUSES: Final[tuple[MembershipStatus, ...]] = (
    "pending",
    "active",
    "suspended",
)
INSTANCE_USER_ROLES: Final[tuple[InstanceUserRole, ...]] = ("instance_admin",)
PERMISSION_KEYS: Final[tuple[PermissionKey, ...]] = (
    "agents:create",
    "skills:manage",
    "users:invite",
    "users:manage_permissions",
    "tasks:assign",
    "tasks:assign_scope",
    "joins:approve",
)
