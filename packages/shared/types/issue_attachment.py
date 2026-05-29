from __future__ import annotations

from typing import TypedDict


class IssueAttachment(TypedDict):
    id: str
    orgId: str
    issueId: str
    issueCommentId: str | None
    assetId: str
    usage: str
    provider: str
    objectKey: str
    contentType: str
    byteSize: int
    sha256: str
    originalFilename: str | None
    createdAt: str
    updatedAt: str
    contentPath: str
