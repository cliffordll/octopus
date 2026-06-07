from __future__ import annotations

import logging
from pathlib import Path

from .services.workspace_paths import resolve_octopus_server_log_dir


def configure_server_file_logging(log_level: str) -> Path:
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
