from __future__ import annotations

from pathlib import Path
import shutil
from typing import Any
from urllib.parse import urlparse


_PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)

_BLOCKING_PROXY_VALUES = {
    "http://127.0.0.1:9",
    "https://127.0.0.1:9",
    "socks5://127.0.0.1:9",
    "http://localhost:9",
    "https://localhost:9",
    "socks5://localhost:9",
}


def local_cli_environment_checks(
    *,
    config: dict[str, Any],
    command: str,
    command_label: str,
    auth_env_keys: tuple[str, ...],
    auth_hint: str,
) -> list[dict[str, str | None]]:
    env = config.get("env")
    env_data = env if isinstance(env, dict) else {}
    return [
        _cwd_check(config),
        _command_check(command, command_label),
        _auth_check(env_data, auth_env_keys, auth_hint),
    ]


def aggregate_status(checks: list[dict[str, str | None]]) -> str:
    statuses = {check["status"] for check in checks}
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    return "ok"


def http_url_check(value: Any) -> dict[str, str | None]:
    url = _string(value)
    if url is None:
        return {
            "id": "url",
            "label": "HTTP endpoint",
            "status": "failed",
            "message": "HTTP adapter requires agentRuntimeConfig.url.",
            "hint": "Set url to the endpoint the adapter should invoke.",
        }
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return {
            "id": "url",
            "label": "HTTP endpoint",
            "status": "failed",
            "message": "HTTP endpoint must be an absolute http(s) URL.",
            "hint": "Use a URL such as https://example.test/invoke.",
        }
    return {
        "id": "url",
        "label": "HTTP endpoint",
        "status": "ok",
        "message": "HTTP endpoint is configured.",
        "hint": None,
    }


def _cwd_check(config: dict[str, Any]) -> dict[str, str | None]:
    cwd = config.get("cwd")
    if cwd is None:
        return {
            "id": "cwd",
            "label": "Working directory",
            "status": "ok",
            "message": "No cwd configured; runtime will use the server process cwd.",
            "hint": None,
        }
    if not isinstance(cwd, str) or not cwd.strip():
        return {
            "id": "cwd",
            "label": "Working directory",
            "status": "failed",
            "message": "cwd must be a non-empty string when configured.",
            "hint": "Set cwd to an existing workspace directory.",
        }
    path = Path(cwd).expanduser()
    if not path.exists() or not path.is_dir():
        return {
            "id": "cwd",
            "label": "Working directory",
            "status": "failed",
            "message": f"Working directory does not exist: {cwd}",
            "hint": "Create the directory or update agentRuntimeConfig.cwd.",
        }
    return {
        "id": "cwd",
        "label": "Working directory",
        "status": "ok",
        "message": f"Working directory exists: {cwd}",
        "hint": None,
    }


def resolve_runtime_executable(command: str) -> str:
    """Best-effort resolution of a CLI command name to an absolute path.

    On Windows, plain command names such as ``codex`` map to wrappers like
    ``codex.CMD`` that ``asyncio.create_subprocess_exec`` cannot launch
    without the explicit extension. Using ``shutil.which`` mirrors the same
    PATHEXT-aware lookup the test-environment helper already performs.
    When ``shutil.which`` cannot resolve the name (e.g. tests that monkeypatch
    subprocess startup with a fake command) the original value is returned so
    the caller's existing error path keeps working.
    """
    return shutil.which(command) or command


def clear_inherited_blocking_proxy_env(
    env: dict[str, str], *, explicit_keys: set[str] | None = None
) -> None:
    """Remove known sandbox blackhole proxy settings from runtime children.

    Codex-hosted development shells commonly set proxy variables to
    ``127.0.0.1:9`` to prevent network access. Local runtime adapters inherit the
    server process environment, so those values make child CLIs fail even when
    the user did not configure a proxy for the agent. Explicit agent runtime env
    always wins and is left untouched.
    """
    explicit = explicit_keys or set()
    for key in _PROXY_ENV_KEYS:
        value = _string(env.get(key))
        if key not in explicit and value and value.lower() in _BLOCKING_PROXY_VALUES:
            env.pop(key, None)


def _command_check(command: str, label: str) -> dict[str, str | None]:
    resolved = shutil.which(command)
    if resolved is None:
        return {
            "id": "command",
            "label": label,
            "status": "failed",
            "message": f"Runtime command is not resolvable on PATH: {command}",
            "hint": "Install the CLI or configure agentRuntimeConfig.command with an executable path.",
        }
    return {
        "id": "command",
        "label": label,
        "status": "ok",
        "message": f"Runtime command is resolvable: {resolved}",
        "hint": None,
    }


def _auth_check(
    env_data: dict[Any, Any],
    keys: tuple[str, ...],
    hint: str,
) -> dict[str, str | None]:
    present = [key for key in keys if _string(env_data.get(key))]
    if present:
        return {
            "id": "auth",
            "label": "Authentication",
            "status": "ok",
            "message": f"Authentication env is configured: {', '.join(present)}",
            "hint": None,
        }
    return {
        "id": "auth",
        "label": "Authentication",
        "status": "warning",
        "message": "No API key env was provided; runtime may rely on local CLI login.",
        "hint": hint,
    }


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
