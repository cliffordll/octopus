from __future__ import annotations

import os
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    log_level: str
    database_url: str
    pod_id: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.environ.get("OCTOPUS_HOST", "127.0.0.1"),
            port=int(os.environ.get("OCTOPUS_PORT", "8000")),
            log_level=os.environ.get("OCTOPUS_LOG_LEVEL", "info"),
            database_url=os.environ.get(
                "OCTOPUS_DATABASE_URL",
                "sqlite+aiosqlite:///./octopus.db",
            ),
            pod_id=os.environ.get("OCTOPUS_POD_ID", socket.gethostname()),
        )


def load_settings() -> Settings:
    return Settings.from_env()
