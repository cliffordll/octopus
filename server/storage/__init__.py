from __future__ import annotations

import os
from pathlib import Path

from .local_disk import LocalDiskStorageProvider
from .service import DefaultStorageService, create_storage_service
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
    return create_local_storage_service(default_storage_dir())


__all__ = [
    "HeadObjectResult",
    "PathLike",
    "PutFileResult",
    "StorageProvider",
    "StorageService",
    "StoredObject",
    "create_local_storage_service",
    "default_storage_dir",
    "get_storage_service",
]
