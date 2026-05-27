from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _build_config(database_url: str) -> Config:
    config = Config(str(_project_root() / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    config.set_main_option(
        "script_location", str(_project_root() / "packages" / "database" / "migrations")
    )
    return config


def _upgrade_to_head_sync(database_url: str) -> None:
    command.upgrade(_build_config(database_url), "head")


async def upgrade_to_head(database_url: str) -> None:
    await asyncio.to_thread(_upgrade_to_head_sync, database_url)
