from __future__ import annotations

import asyncio
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _build_config(database_url: str) -> Config:
    _ensure_sqlite_parent_directory(database_url)
    config = Config(str(_project_root() / "alembic.ini"))
    config.set_main_option(
        "script_location", str(_project_root() / "packages" / "database" / "migrations")
    )
    # 不用 set_main_option 写 sqlalchemy.url：URL-encode 的密码(如 %40/%3F)会被
    # ConfigParser 当成插值语法报错。改用 attributes 传给 env.py 直接建 engine。
    config.attributes["database_url"] = database_url
    return config


def _ensure_sqlite_parent_directory(database_url: str) -> None:
    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "sqlite":
        return
    database = parsed_url.database
    if not database or database == ":memory:":
        return
    Path(database).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _upgrade_to_head_sync(database_url: str) -> None:
    command.upgrade(_build_config(database_url), "head")


async def upgrade_to_head(database_url: str) -> None:
    await asyncio.to_thread(_upgrade_to_head_sync, database_url)
