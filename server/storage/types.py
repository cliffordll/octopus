from __future__ import annotations

from pathlib import Path
from typing import NotRequired, Protocol, TypedDict


class PutFileResult(TypedDict):
    provider: str
    objectKey: str
    contentType: str
    byteSize: int
    sha256: str
    originalFilename: str | None


class HeadObjectResult(TypedDict):
    exists: bool
    contentLength: NotRequired[int]
    lastModified: NotRequired[str]


class StoredObject(TypedDict):
    content: bytes
    contentLength: int
    lastModified: str | None


class StorageProvider(Protocol):
    id: str

    async def put_object(
        self,
        *,
        object_key: str,
        body: bytes,
        content_type: str,
        content_length: int,
    ) -> None: ...

    async def get_object(self, object_key: str) -> StoredObject: ...

    async def head_object(self, object_key: str) -> HeadObjectResult: ...

    async def delete_object(self, object_key: str) -> None: ...


class StorageService(Protocol):
    provider: str

    async def put_file(
        self,
        *,
        org_id: str,
        namespace: str,
        original_filename: str | None,
        content_type: str,
        body: bytes,
    ) -> PutFileResult: ...

    async def get_object_bytes(self, org_id: str, object_key: str) -> bytes: ...

    async def head_object(self, org_id: str, object_key: str) -> HeadObjectResult: ...

    async def delete_object(self, org_id: str, object_key: str) -> None: ...


PathLike = str | Path
