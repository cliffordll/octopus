from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from .types import HeadObjectResult, PathLike, StoredObject


class LocalDiskStorageProvider:
    id = "local_disk"

    def __init__(self, base_dir: PathLike) -> None:
        self._root = Path(base_dir).resolve()

    async def put_object(
        self,
        *,
        object_key: str,
        body: bytes,
        content_type: str,
        content_length: int,
    ) -> None:
        target = self._resolve(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f"{target.name}.tmp")
        temp.write_bytes(body)
        temp.replace(target)

    async def get_object(self, object_key: str) -> StoredObject:
        target = self._resolve(object_key)
        if not target.is_file():
            raise FileNotFoundError("Object not found")
        stat = target.stat()
        return {
            "content": target.read_bytes(),
            "contentLength": stat.st_size,
            "lastModified": datetime.fromtimestamp(stat.st_mtime, UTC).isoformat(),
        }

    async def head_object(self, object_key: str) -> HeadObjectResult:
        target = self._resolve(object_key)
        if not target.is_file():
            return {"exists": False}
        stat = target.stat()
        return {"exists": True, "contentLength": stat.st_size}

    async def delete_object(self, object_key: str) -> None:
        target = self._resolve(object_key)
        try:
            target.unlink()
        except FileNotFoundError:
            return

    def _resolve(self, object_key: str) -> Path:
        normalized = _normalize_object_key(object_key)
        target = (self._root / normalized).resolve()
        if not _is_relative_to(target, self._root):
            raise ValueError("Invalid object key path")
        return target


def _normalize_object_key(object_key: str) -> str:
    normalized = object_key.replace("\\", "/").strip()
    if not normalized or normalized.startswith("/"):
        raise ValueError("Invalid object key")
    parts = [part for part in normalized.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("Invalid object key")
    return "/".join(parts)


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
