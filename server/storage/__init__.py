from __future__ import annotations

import os
from pathlib import Path

from .local_disk import LocalDiskStorageProvider
from .service import DefaultStorageService, create_storage_service
from .s3_compatible import S3CompatibleStorageProvider, create_s3_compatible_client
from .types import (
    HeadObjectResult,
    PathLike,
    PutFileResult,
    StorageProvider,
    StorageService,
    StoredObject,
)


def default_storage_dir() -> Path:
    return Path(os.environ.get("OCTOPUS_STORAGE_DIR", ".octopus/storage")).resolve()


def create_local_storage_service(base_dir: PathLike) -> DefaultStorageService:
    return create_storage_service(LocalDiskStorageProvider(base_dir))


def get_storage_service() -> StorageService:
    provider = os.environ.get("OCTOPUS_STORAGE_PROVIDER", "local_disk").strip().lower()
    if provider in {"", "local", "local_disk"}:
        return create_local_storage_service(default_storage_dir())
    if provider in {"minio", "s3"}:
        return create_storage_service(
            S3CompatibleStorageProvider(
                bucket=_required_env("OCTOPUS_STORAGE_BUCKET"),
                client=create_s3_compatible_client(
                    endpoint_url=os.environ.get("OCTOPUS_STORAGE_ENDPOINT"),
                    access_key=_required_env("OCTOPUS_STORAGE_ACCESS_KEY"),
                    secret_key=_required_env("OCTOPUS_STORAGE_SECRET_KEY"),
                    region=os.environ.get("OCTOPUS_STORAGE_REGION", "us-east-1"),
                    force_path_style=_env_bool(
                        "OCTOPUS_STORAGE_FORCE_PATH_STYLE", provider == "minio"
                    ),
                ),
                provider_id=provider,
            )
        )
    raise ValueError(f"Unsupported OCTOPUS_STORAGE_PROVIDER: {provider}")


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} is required for S3-compatible storage")
    return value


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


__all__ = [
    "HeadObjectResult",
    "PathLike",
    "PutFileResult",
    "StorageProvider",
    "StorageService",
    "StoredObject",
    "S3CompatibleStorageProvider",
    "create_local_storage_service",
    "create_s3_compatible_client",
    "default_storage_dir",
    "get_storage_service",
]
