from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from packages.database.migrations.runner import _ensure_sqlite_parent_directory
from packages.database.schema import Base
from server.services.workspace_paths import resolve_default_sqlite_database_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolve_database_url() -> str:
    # 优先 runner 经 config.attributes 注入的 URL；其次环境变量；再次 alembic.ini 的非哨兵值；
    # 最后回退实例级默认 sqlite。全程不把含 % 的 URL 写回 ConfigParser，避免插值错误。
    url = config.attributes.get("database_url")
    if not url:
        url = os.environ.get("OCTOPUS_DATABASE_URL")
    if not url:
        ini_url = config.get_main_option("sqlalchemy.url")
        if ini_url and ini_url != "sqlite+aiosqlite:///:memory:":
            url = ini_url
    if not url:
        url = resolve_default_sqlite_database_url()
    return url


def run_migrations_offline() -> None:
    url = _resolve_database_url()
    _ensure_sqlite_parent_directory(url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    url = _resolve_database_url()
    _ensure_sqlite_parent_directory(url)
    connectable = create_async_engine(url, poolclass=pool.NullPool, future=True)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
