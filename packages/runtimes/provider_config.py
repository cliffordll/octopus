from __future__ import annotations

from typing import Any


def runtime_provider(config: dict[str, Any]) -> dict[str, Any] | None:
    context = config.get("_octopus")
    if not isinstance(context, dict):
        return None
    provider = context.get("runtimeProvider")
    return provider if isinstance(provider, dict) else None


def provider_model_id(config: dict[str, Any]) -> str | None:
    provider = runtime_provider(config)
    if provider is None:
        return None
    model = provider.get("model")
    if not isinstance(model, dict):
        return None
    return string(model.get("modelId"))


def model_for_cli(config: dict[str, Any]) -> str | None:
    return provider_model_id(config) or string(config.get("model"))


def apply_provider_env(
    env: dict[str, str],
    config: dict[str, Any],
    *,
    api_key_env: str,
    base_url_env: str,
) -> None:
    provider = runtime_provider(config)
    if provider is None:
        return
    api_key = string(provider.get("apiKey"))
    if api_key is not None:
        env[api_key_env] = api_key
    base_url = string(provider.get("baseUrl"))
    if base_url is not None:
        env[base_url_env] = base_url
    provider_config = provider.get("config")
    if isinstance(provider_config, dict):
        extra_env = provider_config.get("env")
        if isinstance(extra_env, dict):
            env.update(
                {
                    key: value
                    for key, value in extra_env.items()
                    if isinstance(key, str) and isinstance(value, str)
                }
            )


def string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
