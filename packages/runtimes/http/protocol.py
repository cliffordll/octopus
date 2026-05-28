from __future__ import annotations

import json
from typing import Any


def string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str)
    }


def json_or_text(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def payload_template(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}
