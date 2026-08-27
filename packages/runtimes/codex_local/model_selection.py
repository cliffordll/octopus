from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..provider_config import provider_model_id, string


_MODEL_ERROR_MARKERS = (
    "does not exist",
    "model_not_found",
    "model not found",
    "not a supported model",
    "not available for this account",
    "not supported",
    "unsupported model",
    "unknown model",
)


@dataclass(frozen=True)
class CodexModelSelection:
    """Resolve one optional Codex CLI model and its safe default fallback."""

    model_id: str | None

    @classmethod
    def from_runtime_config(cls, config: dict[str, Any]) -> CodexModelSelection:
        injected_model = provider_model_id(config)
        if injected_model is not None:
            return cls(injected_model)
        configured = string(config.get("model"))
        if configured is None:
            return cls(None)
        provider, separator, model_id = configured.partition("/")
        if separator and provider.casefold() == "openai" and model_id.strip():
            return cls(model_id.strip())
        return cls(configured)

    @property
    def is_explicit(self) -> bool:
        return self.model_id is not None

    def append_to(self, args: list[str]) -> None:
        if self.model_id is not None:
            args.extend(["--model", self.model_id])

    def should_fallback(self, *, stdout: str, stderr: str) -> bool:
        if not self.is_explicit:
            return False
        message = f"{stdout}\n{stderr}".casefold()
        return any(marker in message for marker in _MODEL_ERROR_MARKERS)
