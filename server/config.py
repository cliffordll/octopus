from __future__ import annotations

import os
from dataclasses import dataclass

from server.services.workspace_paths import resolve_default_sqlite_database_url


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    log_level: str
    database_url: str
    auto_migrate: bool
    local_trusted: bool
    heartbeat_scheduler_enabled: bool
    heartbeat_scheduler_interval_seconds: float

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            host=os.environ.get("OCTOPUS_HOST", "127.0.0.1"),
            port=int(os.environ.get("OCTOPUS_PORT", "8000")),
            log_level=os.environ.get("OCTOPUS_LOG_LEVEL", "info"),
            database_url=os.environ.get(
                "OCTOPUS_DATABASE_URL",
                resolve_default_sqlite_database_url(),
            ),
            auto_migrate=_env_bool("OCTOPUS_AUTO_MIGRATE", False),
            local_trusted=_env_bool("OCTOPUS_LOCAL_TRUSTED", False),
            heartbeat_scheduler_enabled=_env_bool(
                "OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED", True
            ),
            heartbeat_scheduler_interval_seconds=max(
                0.1,
                float(
                    os.environ.get("OCTOPUS_HEARTBEAT_SCHEDULER_INTERVAL_SECONDS", "5")
                ),
            ),
        )


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    return Settings.from_env()
