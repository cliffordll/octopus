from __future__ import annotations

from server.identity.context import IdentityContext

from .errors import AccessDeniedError, RoleRequiredError


class AccessPolicyService:
    def can_access_organization(self, context: IdentityContext, org_id: str) -> bool:
        if context.org_id != org_id:
            return False
        if context.principal.type == "system":
            return bool(context.permissions)
        return context.is_root or context.has_active_role

    def require_organization_access(
        self, context: IdentityContext, org_id: str
    ) -> None:
        if not self.can_access_organization(context, org_id):
            raise RoleRequiredError(
                "Principal does not have active organization access"
            )

    def has_permission(self, context: IdentityContext, permission: str) -> bool:
        if context.is_root or context.role == "owner":
            return True
        if permission not in context.permissions:
            return False
        # Constraint evaluators are intentionally opt-in. Treat an unevaluated
        # constraint as denied instead of silently widening it to full access.
        return not context.permission_constraints.get(permission)

    def require_permission(
        self, context: IdentityContext, org_id: str, permission: str
    ) -> None:
        self.require_organization_access(context, org_id)
        if not self.has_permission(context, permission):
            raise AccessDeniedError(f"Missing permission: {permission}")
