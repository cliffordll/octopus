from __future__ import annotations

import asyncio
import contextlib
import os
import time
from typing import Any

from ..common import runtime_subprocess_kwargs
from .protocol import string

_CACHE_TTL_SECONDS = 60.0
_CACHE: dict[tuple[str, str, tuple[str, ...]], tuple[float, list[dict[str, str]]]] = {}


async def list_models(config: dict[str, Any] | None = None) -> list[dict[str, str]]:
    config = config or {}
    command = (
        string(config.get("command"))
        or os.environ.get("RUDDER_OPENCODE_COMMAND")
        or "opencode"
    )
    args = _string_list(config.get("extraArgs", config.get("args", [])))
    cwd = string(config.get("cwd")) or os.getcwd()
    key = (command, cwd, tuple(args))
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]
    try:
        models = await _discover(command, args, cwd, config)
    except Exception:
        return []
    _CACHE[key] = (now + _CACHE_TTL_SECONDS, models)
    return models


async def _discover(
    command: str, args: list[str], cwd: str, config: dict[str, Any]
) -> list[dict[str, str]]:
    env = dict(os.environ)
    configured_env = config.get("env")
    if isinstance(configured_env, dict):
        env.update(
            {
                key: value
                for key, value in configured_env.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        )
    process = await asyncio.create_subprocess_exec(
        command,
        *args,
        "models",
        cwd=cwd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        **runtime_subprocess_kwargs(),
    )
    try:
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=20)
    except TimeoutError:
        process.kill()
        with contextlib.suppress(Exception):
            await process.communicate()
        await process.wait()
        return []
    if (process.returncode or 0) != 0:
        return []
    return _parse_models(stdout.decode(errors="replace"))


def _parse_models(stdout: str) -> list[dict[str, str]]:
    seen: set[str] = set()
    models: list[dict[str, str]] = []
    for raw in stdout.splitlines():
        first = raw.strip().split(maxsplit=1)[0] if raw.strip() else ""
        if "/" not in first:
            continue
        provider, model = first.split("/", 1)
        if not provider.strip() or not model.strip():
            continue
        model_id = f"{provider.strip()}/{model.strip()}"
        if model_id in seen:
            continue
        seen.add(model_id)
        models.append({"id": model_id, "label": model_id})
    return sorted(models, key=lambda item: item["id"].lower())


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return list(value)
    return []
