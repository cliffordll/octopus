from __future__ import annotations

from dataclasses import dataclass

from .context import IdentityContext
from .principal import PrincipalRef


@dataclass(frozen=True, slots=True)
class SystemContextDefinition:
    capabilities: frozenset[str]


class SystemIdentityContextFactory:
    _definitions = {
        "heartbeat": SystemContextDefinition(
            frozenset({"runs:inspect", "runs:dispatch"})
        ),
        "run_dispatch": SystemContextDefinition(frozenset({"runs:dispatch"})),
        "run_recovery": SystemContextDefinition(
            frozenset({"runs:inspect", "runs:recover", "runs:finalize"})
        ),
        "run_finalization": SystemContextDefinition(frozenset({"runs:finalize"})),
    }

    def create(
        self,
        *,
        system_id: str,
        org_id: str,
        reason: str,
        entity_type: str,
        entity_id: str,
    ) -> IdentityContext:
        definition = self._definitions.get(system_id)
        if definition is None:
            raise ValueError(f"Unregistered system principal: {system_id}")
        if not reason.strip():
            raise ValueError("System context reason must not be empty")
        return IdentityContext(
            principal=PrincipalRef(type="system", id=system_id),
            org_id=org_id,
            permissions=definition.capabilities,
            source="system_internal",
            reason=reason,
            entity_type=entity_type,
            entity_id=entity_id,
        )
