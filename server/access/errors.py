from __future__ import annotations


class AccessDeniedError(PermissionError):
    pass


class MembershipRequiredError(AccessDeniedError):
    pass
