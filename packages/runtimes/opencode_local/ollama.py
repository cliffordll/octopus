from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx


DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class LocalOllamaProvider:
    """One implicit local Ollama provider resolved for an OpenCode Run."""

    model_id: str
    native_base_url: str

    @classmethod
    def from_runtime_config(
        cls, config: dict[str, Any], env: dict[str, str]
    ) -> LocalOllamaProvider | None:
        if _database_runtime_provider(config) is not None:
            return None
        model_ref = _string(config.get("model"))
        if model_ref is None or "/" not in model_ref:
            return None
        provider_id, model_id = model_ref.split("/", 1)
        if provider_id.strip().casefold() != "ollama" or not model_id.strip():
            return None
        host = _string(env.get("OLLAMA_HOST")) or DEFAULT_OLLAMA_HOST
        return cls(
            model_id=model_id.strip(),
            native_base_url=_normalize_native_base_url(host),
        )

    @property
    def openai_base_url(self) -> str:
        return f"{self.native_base_url}/v1"

    def execution_provider(self) -> dict[str, Any]:
        return {
            "providerId": "ollama",
            "name": "Ollama (local)",
            "protocol": "openai_chat_completions",
            "npmPackage": "@ai-sdk/openai-compatible",
            "baseUrl": self.openai_base_url,
            "apiKey": None,
            "config": {},
            "model": {
                "modelId": self.model_id,
                "displayName": self.model_id,
                "metadata": {},
            },
        }

    async def validate(self) -> str | None:
        tags_url = f"{self.native_base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=5.0, trust_env=False) as client:
                response = await client.get(tags_url)
                response.raise_for_status()
        except (httpx.HTTPError, OSError) as exc:
            return (
                f"Ollama is unavailable at {self.native_base_url}: {exc}. "
                "Start Ollama or set OLLAMA_HOST to the correct local address."
            )
        try:
            payload = response.json()
        except ValueError:
            return f"Ollama returned an invalid model list from {tags_url}"
        models = payload.get("models") if isinstance(payload, dict) else None
        model_items = models if isinstance(models, list) else []
        available = {
            value
            for item in model_items
            if isinstance(item, dict)
            for value in (_string(item.get("name")), _string(item.get("model")))
            if value
        }
        if self.model_id not in available:
            return (
                f'Ollama model "{self.model_id}" is not installed. '
                f"Run `ollama pull {self.model_id}` before starting this Agent."
            )
        return None


def _database_runtime_provider(config: dict[str, Any]) -> dict[str, Any] | None:
    runtime_context = config.get("_octopus")
    if not isinstance(runtime_context, dict):
        return None
    provider = runtime_context.get("runtimeProvider")
    return provider if isinstance(provider, dict) else None


def _normalize_native_base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    parsed = urlsplit(candidate)
    path = parsed.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", "")).rstrip("/")


def _string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
