from __future__ import annotations

from typing import Final, Literal


AccessPrincipalType = Literal["user", "agent"]
AccessScopeType = Literal["instance", "organization"]
RoleName = Literal["root", "owner", "member"]
RoleStatus = Literal["pending", "active", "suspended"]
PermissionKey = Literal[
    "agents:create",
    "agents:manage",
    "skills:manage",
    "users:invite",
    "users:manage_permissions",
    "tasks:assign",
    "approvals:decide",
    "organizations:manage",
    "documents:manage",
    "runtime:manage",
    "costs:manage",
    "projects:manage",
    "goals:manage",
    "workspaces:manage",
]

INSTANCE_SCOPE_ID: Final[str] = "instance"

ACCESS_PRINCIPAL_TYPES: Final[tuple[AccessPrincipalType, ...]] = (
    "user",
    "agent",
)
ACCESS_SCOPE_TYPES: Final[tuple[AccessScopeType, ...]] = (
    "instance",
    "organization",
)
ROLE_NAMES: Final[tuple[RoleName, ...]] = ("root", "owner", "member")
ROLE_STATUSES: Final[tuple[RoleStatus, ...]] = (
    "pending",
    "active",
    "suspended",
)
PERMISSION_KEYS: Final[tuple[PermissionKey, ...]] = (
    "agents:create",
    "agents:manage",
    "skills:manage",
    "users:invite",
    "users:manage_permissions",
    "tasks:assign",
    "approvals:decide",
    "organizations:manage",
    "documents:manage",
    "runtime:manage",
    "costs:manage",
    "projects:manage",
    "goals:manage",
    "workspaces:manage",
)
