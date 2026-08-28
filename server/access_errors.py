from __future__ import annotations


class AccessDeniedError(PermissionError):
    pass


class RoleRequiredError(AccessDeniedError):
    pass
