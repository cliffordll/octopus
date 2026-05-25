from __future__ import annotations

from packages.shared.src.types.organization import OrganizationSummary


class OrgService:
    async def list(self) -> list[OrganizationSummary]:
        return []
