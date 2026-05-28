from __future__ import annotations

from ..local_cli import LocalCliRuntimeAdapter


class ClaudeLocalRuntimeAdapter(LocalCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(
            "claude_local",
            default_command="claude",
            default_args=["--print"],
            models=[{"id": "claude-sonnet-4.5", "label": "Claude Sonnet 4.5"}],
        )
