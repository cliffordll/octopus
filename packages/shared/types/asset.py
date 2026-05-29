from __future__ import annotations

from typing import TypedDict


class Asset(TypedDict):
    id: str
    orgId: str
    provider: str
    objectKey: str
    contentType: str
    byteSize: int
    sha256: str
    originalFilename: str | None
    createdByAgentId: str | None
    createdByUserId: str | None
    createdAt: str
    updatedAt: str
    contentPath: str
