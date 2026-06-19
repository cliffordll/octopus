from __future__ import annotations

import uvicorn

from .app_logging import configure_server_file_logging
from .config import load_settings


def main() -> None:
    settings = load_settings()
    configure_server_file_logging(settings.log_level)
    uvicorn.run(
        "server.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
        timeout_graceful_shutdown=settings.graceful_shutdown_timeout_seconds,
    )
