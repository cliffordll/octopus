from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.responses import Response


async def actor_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    settings = request.app.state.settings
    if not hasattr(request.state, "actor") and getattr(
        settings, "local_trusted", False
    ):
        request.state.actor = {
            "type": "board",
            "id": "local-board",
            "userId": "local-board",
            "source": "local_implicit",
        }
    return await call_next(request)
