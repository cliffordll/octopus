from __future__ import annotations

from .errors import AccessDeniedError, RoleRequiredError
from .permission_service import PermissionService, PermissionSpec
from .policy import AccessPolicyService
from .scope_resolver import AccessScopeResolver, ScopedResource

__all__ = [
    "AccessDeniedError",
    "AccessPolicyService",
    "AccessScopeResolver",
    "RoleRequiredError",
    "ScopedResource",
    "PermissionService",
    "PermissionSpec",
]
