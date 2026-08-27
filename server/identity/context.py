from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .principal import PrincipalRef


@dataclass(frozen=True, slots=True)
class IdentityContext:
    principal: PrincipalRef
    org_id: str | None
    membership_id: str | None = None
    membership_role: str | None = None
    permissions: frozenset[str] = field(default_factory=frozenset)
    permission_scopes: dict[str, dict[str, Any] | None] = field(default_factory=dict)
    source: str = "unknown"
    run_id: str | None = None
    is_instance_admin: bool = False
    reason: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None

    @property
    def has_active_membership(self) -> bool:
        return self.membership_id is not None
