from __future__ import annotations

import json
from typing import Any


def build_args(config: dict[str, Any]) -> list[str]:
    args = _string_list(config.get("extraArgs", config.get("args", [])))
    args.extend(["run", "--format", "json"])
    model = string(config.get("model"))
    if model:
        args.extend(["--model", model])
    variant = string(config.get("variant"))
    if variant:
        args.extend(["--variant", variant])
    return args


def parse_jsonl(stdout: str) -> dict[str, Any]:
    session_id: str | None = None
    messages: list[str] = []
    errors: list[str] = []
    usage = {"inputTokens": 0, "cachedInputTokens": 0, "outputTokens": 0}
    cost_usd = 0.0
    for raw_line in stdout.splitlines():
        try:
            event = json.loads(raw_line.strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        current_session_id = string(event.get("sessionID"))
        if current_session_id:
            session_id = current_session_id
        event_type = event.get("type")
        if event_type == "text":
            part = event.get("part")
            if isinstance(part, dict):
                text = string(part.get("text"))
                if text:
                    messages.append(text)
        elif event_type == "step_finish":
            part = event.get("part")
            if isinstance(part, dict):
                tokens = part.get("tokens")
                token_data = tokens if isinstance(tokens, dict) else {}
                cache = token_data.get("cache")
                cache_data = cache if isinstance(cache, dict) else {}
                usage["inputTokens"] += _integer(token_data.get("input"))
                usage["cachedInputTokens"] += _integer(cache_data.get("read"))
                usage["outputTokens"] += _integer(token_data.get("output")) + _integer(
                    token_data.get("reasoning")
                )
                cost_usd += _float(part.get("cost"))
        elif event_type == "tool_use":
            part = event.get("part")
            if isinstance(part, dict):
                state = part.get("state")
                if isinstance(state, dict) and state.get("status") == "error":
                    text = string(state.get("error"))
                    if text:
                        errors.append(text)
        elif event_type == "error":
            text = error_text(event.get("error") or event.get("message"))
            if text:
                errors.append(text)
    return {
        "sessionId": session_id,
        "summary": "\n\n".join(messages).strip(),
        "usage": usage,
        "costUsd": cost_usd,
        "errorMessage": "\n".join(errors) if errors else None,
    }


def error_text(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, dict):
        data = value.get("data")
        if isinstance(data, dict):
            text = string(data.get("message"))
            if text:
                return text
        for key in ("message", "error", "name", "code"):
            text = string(value.get(key))
            if text:
                return text
    return None


def provider(model: str | None) -> str | None:
    if not model or "/" not in model:
        return None
    return model.split("/", 1)[0].strip() or None


def model_unavailable(stdout: str, stderr: str, error: str | None) -> bool:
    haystack = "\n".join([stdout, stderr, error or ""]).lower()
    return any(
        marker in haystack
        for marker in ("model unavailable", "unknown model", "model not found")
    )


def auth_required(stdout: str, stderr: str, error: str | None) -> bool:
    haystack = "\n".join([stdout, stderr, error or ""]).lower()
    return any(
        marker in haystack
        for marker in (
            "auth required",
            "authentication required",
            "unauthorized",
            "api key",
        )
    )


def first_line(value: str) -> str | None:
    return next((line.strip() for line in value.splitlines() if line.strip()), None)


def string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _float(value: Any) -> float:
    return (
        float(value)
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else 0.0
    )
