from __future__ import annotations

import json
from typing import Any

from ..provider_config import model_for_cli


def build_args(config: dict[str, Any]) -> list[str]:
    args = _string_list(config.get("extraArgs", config.get("args", [])))
    args.extend(["--print", "-", "--output-format", "stream-json", "--verbose"])
    model = model_for_cli(config)
    if model:
        args.extend(["--model", model])
    effort = _string(config.get("effort") or config.get("modelReasoningEffort"))
    if effort:
        args.extend(["--effort", effort])
    max_turns = config.get("maxTurnsPerRun")
    if isinstance(max_turns, int) and not isinstance(max_turns, bool) and max_turns > 0:
        args.extend(["--max-turns", str(max_turns)])
    if config.get("dangerouslySkipPermissions") is True:
        args.extend(["--dangerously-skip-permissions"])
    if config.get("chrome") is True:
        args.append("--chrome")
    return args


def parse_stream_json(stdout: str) -> dict[str, Any]:
    session_id: str | None = None
    model = ""
    final_result: dict[str, Any] | None = None
    assistant_texts: list[str] = []
    for raw_line in stdout.splitlines():
        try:
            event = json.loads(raw_line.strip())
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "system" and event.get("subtype") == "init":
            session_id = _string(event.get("session_id")) or session_id
            model = _string(event.get("model")) or model
        elif event_type == "assistant":
            session_id = _string(event.get("session_id")) or session_id
            message = event.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list):
                    assistant_texts.extend(_assistant_texts(content))
        elif event_type == "result":
            final_result = event
            session_id = _string(event.get("session_id")) or session_id
    usage = None
    summary = "\n\n".join(assistant_texts).strip()
    cost_usd = None
    if final_result is not None:
        usage = _usage(final_result.get("usage"))
        summary = _string(final_result.get("result")) or summary
        raw_cost = final_result.get("total_cost_usd")
        if isinstance(raw_cost, (float, int)) and not isinstance(raw_cost, bool):
            cost_usd = float(raw_cost)
    return {
        "sessionId": session_id,
        "model": model,
        "usage": usage,
        "summary": summary,
        "costUsd": cost_usd,
        "resultJson": final_result,
    }


def login_required(
    stdout: str, stderr: str, result_json: dict[str, Any] | None
) -> bool:
    messages = [stdout, stderr]
    if result_json is not None:
        for key in ("result", "error", "message"):
            value = result_json.get(key)
            if isinstance(value, str):
                messages.append(value)
    text = "\n".join(messages).lower()
    return any(
        marker in text
        for marker in (
            "not logged in",
            "please log in",
            "claude login",
            "login required",
            "requires login",
            "unauthorized",
            "authentication required",
        )
    )


def describe_failure(result_json: dict[str, Any] | None) -> str | None:
    if result_json is None:
        return None
    subtype = _string(result_json.get("subtype"))
    result = _string(result_json.get("result"))
    if subtype and result:
        return f"Claude run failed: subtype={subtype}: {result}"
    if subtype:
        return f"Claude run failed: subtype={subtype}"
    return result


def max_turns(result_json: dict[str, Any] | None) -> bool:
    if result_json is None:
        return False
    subtype = (_string(result_json.get("subtype")) or "").lower()
    stop_reason = (_string(result_json.get("stop_reason")) or "").lower()
    result = _string(result_json.get("result")) or ""
    return (
        subtype == "error_max_turns"
        or stop_reason == "max_turns"
        or "max turns" in result.lower()
        or "maximum turns" in result.lower()
    )


def first_line(value: str) -> str | None:
    return next((line.strip() for line in value.splitlines() if line.strip()), None)


def string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _assistant_texts(content: list[Any]) -> list[str]:
    texts: list[str] = []
    for entry in content:
        if isinstance(entry, dict) and entry.get("type") == "text":
            text = _string(entry.get("text"))
            if text:
                texts.append(text)
    return texts


def _usage(value: Any) -> dict[str, int]:
    data = value if isinstance(value, dict) else {}
    return {
        "inputTokens": _integer(data.get("input_tokens")),
        "cachedInputTokens": _integer(data.get("cache_read_input_tokens"))
        + _integer(data.get("cache_creation_input_tokens")),
        "outputTokens": _integer(data.get("output_tokens")),
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []


def _integer(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _string(value: Any) -> str | None:
    return string(value)
