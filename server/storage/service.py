from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import PurePosixPath
import re
from uuid import uuid4

from .types import HeadObjectResult, PutFileResult, StorageProvider


_SAFE_SEGMENT_RE = re.compile(r"[^A-Za-z0-9._-]+")


class DefaultStorageService:
    def __init__(self, provider: StorageProvider) -> None:
        self._provider = provider
        self.provider = provider.id

    async def put_file(
        self,
        *,
        org_id: str,
        namespace: str,
        original_filename: str | None,
        content_type: str,
        body: bytes,
    ) -> PutFileResult:
        _validate_org_id(org_id)
        clean_namespace = _normalize_namespace(namespace)
        clean_filename = _sanitize_filename(original_filename)
        object_key = _build_object_key(org_id, clean_namespace, clean_filename)
        await self._provider.put_object(
            object_key=object_key,
            body=body,
            content_type=content_type,
            content_length=len(body),
        )
        return {
            "provider": self.provider,
            "objectKey": object_key,
            "contentType": content_type,
            "byteSize": len(body),
            "sha256": sha256(body).hexdigest(),
            "originalFilename": original_filename,
        }

    async def get_object_bytes(self, org_id: str, object_key: str) -> bytes:
        self._assert_org_object(org_id, object_key)
        stored = await self._provider.get_object(object_key)
        return stored["content"]

    async def head_object(self, org_id: str, object_key: str) -> HeadObjectResult:
        self._assert_org_object(org_id, object_key)
        return await self._provider.head_object(object_key)

    async def delete_object(self, org_id: str, object_key: str) -> None:
        self._assert_org_object(org_id, object_key)
        await self._provider.delete_object(object_key)

    def _assert_org_object(self, org_id: str, object_key: str) -> None:
        _validate_org_id(org_id)
        normalized = _normalize_object_key(object_key)
        if not normalized.startswith(f"{org_id}/"):
            raise ValueError("Object does not belong to organization")


def create_storage_service(provider: StorageProvider) -> DefaultStorageService:
    return DefaultStorageService(provider)


def _validate_org_id(org_id: str) -> None:
    if not org_id or "/" in org_id or "\\" in org_id:
        raise ValueError("Invalid organization id")


def _normalize_namespace(namespace: str) -> str:
    normalized = namespace.replace("\\", "/").strip("/")
    parts = [_sanitize_segment(part) for part in normalized.split("/") if part]
    if not parts:
        raise ValueError("Invalid storage namespace")
    return "/".join(parts)


def _sanitize_filename(original_filename: str | None) -> str:
    fallback = "file"
    if not original_filename:
        return fallback
    name = PurePosixPath(original_filename.replace("\\", "/")).name.strip()
    if not name or name in {".", ".."}:
        return fallback
    sanitized = _SAFE_SEGMENT_RE.sub("-", name).strip(".-")
    return sanitized[:160] or fallback


def _sanitize_segment(value: str) -> str:
    sanitized = _SAFE_SEGMENT_RE.sub("-", value).strip(".-")
    if not sanitized or sanitized in {".", ".."}:
        raise ValueError("Invalid storage namespace")
    return sanitized[:80]


def _build_object_key(org_id: str, namespace: str, filename: str) -> str:
    now = datetime.now(UTC)
    return f"{org_id}/{namespace}/{now:%Y/%m/%d}/{uuid4().hex}-{filename}"


def _normalize_object_key(object_key: str) -> str:
    normalized = object_key.replace("\\", "/").strip()
    if not normalized or normalized.startswith("/"):
        raise ValueError("Invalid object key")
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("Invalid object key")
    return "/".join(parts)
