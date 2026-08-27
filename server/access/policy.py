from __future__ import annotations

from server.identity.context import IdentityContext

from .errors import AccessDeniedError, MembershipRequiredError


class AccessPolicyService:
    def can_access_organization(self, context: IdentityContext, org_id: str) -> bool:
        if context.org_id != org_id:
            return False
        if context.principal.type == "system":
            return bool(context.permissions)
        return context.is_instance_admin or context.has_active_membership

    def require_organization_access(
        self, context: IdentityContext, org_id: str
    ) -> None:
        if not self.can_access_organization(context, org_id):
            raise MembershipRequiredError(
                "Principal does not have active organization access"
            )

    def has_permission(self, context: IdentityContext, permission: str) -> bool:
        if context.is_instance_admin:
            return True
        return permission in context.permissions

    def require_permission(
        self, context: IdentityContext, org_id: str, permission: str
    ) -> None:
        self.require_organization_access(context, org_id)
        if not self.has_permission(context, permission):
            raise AccessDeniedError(f"Missing permission: {permission}")
