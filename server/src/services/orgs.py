from __future__ import annotations

from typing import TypedDict


class OrgSummary(TypedDict):
    id: str
    name: str
    urlKey: str
    status: str


class OrgService:
    async def list(self) -> list[OrgSummary]:
        return []
