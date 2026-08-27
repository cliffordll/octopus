from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .services.workspace_paths import resolve_octopus_server_log_dir

_SQLALCHEMY_POOL_LOGGER = "sqlalchemy.pool.impl.AsyncAdaptedQueuePool"
_FILTER_MARKER = "_octopus_cancelled_sqlite_terminate_filter"


class _CancelledSqliteTerminateFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != _SQLALCHEMY_POOL_LOGGER:
            return True
        if not record.getMessage().startswith("Exception terminating connection"):
            return True
        exc = record.exc_info[1] if record.exc_info else None
        return not _exception_chain_contains_cancelled_error(exc)


def install_sqlalchemy_pool_cancel_filter() -> None:
    logger = logging.getLogger(_SQLALCHEMY_POOL_LOGGER)
    if any(getattr(item, _FILTER_MARKER, False) for item in logger.filters):
        return
    filter_item = _CancelledSqliteTerminateFilter()
    setattr(filter_item, _FILTER_MARKER, True)
    logger.addFilter(filter_item)


def _exception_chain_contains_cancelled_error(exc: BaseException | None) -> bool:
    while exc is not None:
        if isinstance(exc, asyncio.CancelledError):
            return True
        exc = exc.__cause__ or exc.__context__
    return False


def configure_server_file_logging(log_level: str) -> Path:
    install_sqlalchemy_pool_cancel_filter()
    log_dir = resolve_octopus_server_log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "octopus.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(_log_level(log_level))
    if not _has_file_handler(root_logger, log_file):
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setLevel(_log_level(log_level))
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            )
        )
        setattr(handler, "_octopus_log_file", str(log_file))
        root_logger.addHandler(handler)

    return log_dir


def _has_file_handler(logger: logging.Logger, log_file: Path) -> bool:
    resolved = str(log_file.resolve())
    return any(
        getattr(handler, "_octopus_log_file", None) == resolved
        for handler in logger.handlers
    )


def _log_level(value: str) -> int:
    return getattr(logging, value.strip().upper(), logging.INFO)
