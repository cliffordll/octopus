from __future__ import annotations

from pathlib import Path
from typing import Any


def runtime_prompt_from_config(config: dict[str, Any]) -> str:
    prompt = _string(config.get("promptTemplate"))
    if prompt:
        return prompt
    instructions_path = _resolve_instructions_path(config)
    if instructions_path is None:
        return ""
    try:
        return instructions_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _resolve_instructions_path(config: dict[str, Any]) -> Path | None:
    raw_path = _string(config.get("instructionsFilePath"))
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    cwd = _string(config.get("cwd"))
    if not cwd:
        return None
    cwd_path = Path(cwd).expanduser()
    if not cwd_path.is_absolute():
        return None
    return cwd_path / path


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
