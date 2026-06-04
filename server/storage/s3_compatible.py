from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from .types import HeadObjectResult, StoredObject


class S3CompatibleStorageProvider:
    def __init__(self, *, bucket: str, client: Any, provider_id: str = "s3") -> None:
        if not bucket.strip():
            raise ValueError("Storage bucket is required")
        self.id = provider_id
        self._bucket = bucket
        self._client = client

    async def put_object(
        self,
        *,
        object_key: str,
        body: bytes,
        content_type: str,
        content_length: int,
    ) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=object_key,
            Body=body,
            ContentType=content_type,
            ContentLength=content_length,
        )

    async def get_object(self, object_key: str) -> StoredObject:
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._bucket,
                Key=object_key,
            )
        except Exception as exc:
            if _is_not_found_error(exc):
                raise FileNotFoundError("Object not found") from exc
            raise
        body = response.get("Body")
        content = await asyncio.to_thread(body.read) if hasattr(body, "read") else b""
        last_modified = response.get("LastModified")
        return {
            "content": content,
            "contentLength": _int_or_len(response.get("ContentLength"), content),
            "lastModified": _iso_datetime(last_modified),
        }

    async def head_object(self, object_key: str) -> HeadObjectResult:
        try:
            response = await asyncio.to_thread(
                self._client.head_object,
                Bucket=self._bucket,
                Key=object_key,
            )
        except Exception as exc:
            if _is_not_found_error(exc):
                return {"exists": False}
            raise
        content_length = response.get("ContentLength")
        if isinstance(content_length, int) and not isinstance(content_length, bool):
            return {"exists": True, "contentLength": content_length}
        return {"exists": True}

    async def delete_object(self, object_key: str) -> None:
        await asyncio.to_thread(
            self._client.delete_object,
            Bucket=self._bucket,
            Key=object_key,
        )


def create_s3_compatible_client(
    *,
    endpoint_url: str | None,
    access_key: str,
    secret_key: str,
    region: str,
    force_path_style: bool,
) -> Any:
    try:
        from boto3.session import Session
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError(
            "boto3 is required when OCTOPUS_STORAGE_PROVIDER is 'minio' or 's3'"
        ) from exc

    config = Config(s3={"addressing_style": "path" if force_path_style else "virtual"})
    return Session().client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=config,
    )


def _is_not_found_error(exc: Exception) -> bool:
    if isinstance(exc, KeyError):
        return True
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    error = response.get("Error")
    if not isinstance(error, dict):
        return False
    return str(error.get("Code")) in {"404", "NoSuchKey", "NotFound"}


def _int_or_len(value: object, content: bytes) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return len(content)


def _iso_datetime(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return None
