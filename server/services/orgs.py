from __future__ import annotations

from packages.shared.types.organization import OrganizationSummary


class OrgService:
    async def list(self) -> list[OrganizationSummary]:
        return []
