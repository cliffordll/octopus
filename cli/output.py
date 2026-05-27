from __future__ import annotations

import json
from typing import Any, TextIO


def write_output(data: Any, *, json_mode: bool, stream: TextIO) -> None:
    if json_mode:
        stream.write(json.dumps(data, ensure_ascii=False, indent=2))
        stream.write("\n")
        return
    if isinstance(data, list):
        if not data:
            stream.write("No results.\n")
            return
        for item in data:
            stream.write(_summary(item))
            stream.write("\n")
        return
    stream.write(_summary(data))
    stream.write("\n")


def _summary(data: Any) -> str:
    if not isinstance(data, dict):
        return str(data)
    preferred = [
        str(data[key])
        for key in ("identifier", "name", "type", "title", "status", "id")
        if data.get(key) is not None
    ]
    if preferred:
        return " | ".join(preferred)
    return json.dumps(data, ensure_ascii=False)
