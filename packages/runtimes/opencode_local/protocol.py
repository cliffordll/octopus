from __future__ import annotations

import json
import re
from typing import Any

from ..session import runtime_session_id


def build_args(config: dict[str, Any]) -> list[str]:
    # Preserve legacy test/custom-command behavior where `args` prefixes the
    # command, while `extraArgs` mirrors upstream OpenCode run-subcommand flags.
    args = _string_list(config.get("args"))
    args.extend(["run", "--format", "json"])
    session_id = runtime_session_id(config)
    if session_id:
        args.extend(["--session", session_id])
    model = string(config.get("model"))
    if model:
        args.extend(["--model", model])
    variant = string(config.get("variant"))
    if variant:
        args.extend(["--variant", variant])
    args.extend(_string_list(config.get("extraArgs")))
    return args


def parse_jsonl(stdout: str) -> dict[str, Any]:
    session_id: str | None = None
    messages: list[str] = []
    errors: list[str] = []
    tool_errors: list[str] = []
    written_files: list[str] = []
    declared_work_products: list[str] = []
    primary_work_products: list[str] = []
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
                    _append_unique(
                        declared_work_products,
                        _declared_work_product_paths_from_text(text),
                    )
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
                tool_name = string(part.get("tool"))
                state = part.get("state")
                if isinstance(state, dict):
                    state_input = state.get("input")
                    if isinstance(state_input, dict):
                        command = string(state_input.get("command"))
                        if command:
                            _append_unique(
                                declared_work_products,
                                _declared_work_product_paths_from_text(command),
                            )
                            _append_unique(
                                declared_work_products,
                                _flag_values(command, "--work-product"),
                            )
                            _append_unique(
                                primary_work_products,
                                _flag_values(command, "--primary-work-product"),
                            )
                        file_path = string(state_input.get("filePath"))
                        if (
                            tool_name == "write"
                            and state.get("status") == "completed"
                            and file_path
                        ):
                            _append_unique(written_files, [file_path])
                    if state.get("status") == "error":
                        text = string(state.get("error"))
                        if text:
                            errors.append(text)
                            tool_errors.append(text)
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
        "toolErrors": tool_errors,
        "writtenFiles": written_files,
        "declaredWorkProducts": declared_work_products,
        "primaryWorkProducts": primary_work_products,
    }


_WORK_PRODUCT_FLAG_VALUE_RE = r"(?:\"([^\"]+)\"|'([^']+)'|([^\s]+))"
_WORK_PRODUCT_EXTENSIONS_RE = r"md|txt|docx|pdf|csv|json|html?"
_WORK_PRODUCT_TOKEN_RE = r"[^\s`'\"<>|:*?]+"
_WORK_PRODUCT_PATH_RE = re.compile(
    rf"(?<![\w.-])((?:{_WORK_PRODUCT_TOKEN_RE}/)+{_WORK_PRODUCT_TOKEN_RE}\.(?:{_WORK_PRODUCT_EXTENSIONS_RE}))",
    re.IGNORECASE,
)
_WORK_PRODUCT_FILENAME_RE = re.compile(
    rf"(?<![\w./-])({_WORK_PRODUCT_TOKEN_RE}\.(?:{_WORK_PRODUCT_EXTENSIONS_RE}))",
    re.IGNORECASE,
)
_WORK_PRODUCT_PATH_STRIP_CHARS = "`'\".,;:()[]{}，。；：（）【】《》"


def _flag_values(command: str, flag: str) -> list[str]:
    pattern = re.compile(rf"{re.escape(flag)}(?:=|\s+){_WORK_PRODUCT_FLAG_VALUE_RE}")
    values: list[str] = []
    for match in pattern.finditer(command):
        value = next((group for group in match.groups() if group), None)
        if value:
            values.append(value.replace("\\", "/"))
    return values


def _declared_work_product_paths_from_text(text: str) -> list[str]:
    if not text.strip():
        return []
    paths = [
        match.group(1).replace("\\", "/")
        for match in _WORK_PRODUCT_PATH_RE.finditer(text)
    ]
    filenames = [match.group(1) for match in _WORK_PRODUCT_FILENAME_RE.finditer(text)]
    paths.extend(filenames)
    if "reports/" in text or "reports\\" in text:
        paths.extend(f"reports/{filename}" for filename in filenames)
    cleaned = [
        path.strip(_WORK_PRODUCT_PATH_STRIP_CHARS)
        for path in paths
        if path.strip(_WORK_PRODUCT_PATH_STRIP_CHARS)
    ]
    unique: list[str] = []
    _append_unique(unique, cleaned)
    return unique


def _append_unique(target: list[str], values: list[str]) -> None:
    for value in values:
        normalized = value.replace("\\", "/")
        if normalized and normalized not in target:
            target.append(normalized)


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


def unknown_session(stdout: str, stderr: str, error: str | None) -> bool:
    haystack = "\n".join([stdout, stderr, error or ""]).lower()
    return any(
        marker in haystack
        for marker in (
            "unknown session",
            "session not found",
            "session id not found",
            "no session found",
            "cannot resume",
            "resume failed",
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
