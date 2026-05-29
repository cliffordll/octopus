from __future__ import annotations

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
