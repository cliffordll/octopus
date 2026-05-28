from __future__ import annotations

from ..local_cli import LocalCliRuntimeAdapter


class OpenCodeLocalRuntimeAdapter(LocalCliRuntimeAdapter):
    def __init__(self) -> None:
        super().__init__(
            "opencode_local",
            default_command="opencode",
            models=[{"id": "opencode/default", "label": "OpenCode Default"}],
        )
