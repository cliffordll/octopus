from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from packages.shared.types.observability import LogReadResult


def read_local_file_log(
    base_dir: str | Path,
    log_ref: str | None,
    *,
    offset: int = 0,
    limit_bytes: int = 256_000,
) -> LogReadResult:
    if not log_ref:
        return {"content": "", "endOffset": 0, "eof": True}

    root = Path(base_dir).resolve()
    relative = Path(log_ref)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("Invalid log reference")

    path = (root / relative).resolve()
    if root != path and root not in path.parents:
        raise ValueError("Invalid log reference")
    if not path.exists():
        return {"content": "", "endOffset": 0, "eof": True}

    start = max(0, offset)
    limit = max(1, min(limit_bytes, 1_000_000))
    size = path.stat().st_size
    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read(limit)
    end_offset = start + len(data)
    eof = end_offset >= size
    result: dict[str, Any] = {
        "content": data.decode("utf-8", errors="replace"),
        "endOffset": end_offset,
        "eof": eof,
    }
    if not eof:
        result["nextOffset"] = end_offset
    return cast(LogReadResult, result)


def append_local_file_log(
    base_dir: str | Path,
    log_ref: str,
    *,
    stream: str,
    chunk: str,
    timestamp: datetime | None = None,
) -> None:
    path = _resolve_local_file_log_path(base_dir, log_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "stream": stream,
        "chunk": chunk,
        "ts": (timestamp or datetime.now(UTC)).isoformat(),
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False))
        handle.write("\n")


def finalize_local_file_log(
    base_dir: str | Path, log_ref: str | None
) -> dict[str, Any]:
    if not log_ref:
        return {"logBytes": 0, "logSha256": None, "logCompressed": False}
    path = _resolve_local_file_log_path(base_dir, log_ref)
    if not path.exists():
        return {"logBytes": 0, "logSha256": None, "logCompressed": False}
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    return {
        "logBytes": size,
        "logSha256": digest.hexdigest(),
        "logCompressed": False,
    }


def _resolve_local_file_log_path(base_dir: str | Path, log_ref: str) -> Path:
    root = Path(base_dir).resolve()
    relative = Path(log_ref)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("Invalid log reference")

    path = (root / relative).resolve()
    if root != path and root not in path.parents:
        raise ValueError("Invalid log reference")
    return path
