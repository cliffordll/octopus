from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from starlette.types import ASGIApp, Receive, Scope, Send


class ActorContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        settings = request.app.state.settings
        _set_actor_context(request, settings)
        await self.app(scope, receive, send)


def _set_actor_context(request: Request, settings: object) -> None:
    if not hasattr(request.state, "actor") and getattr(
        settings, "local_trusted", False
    ):
        test_agent_id = request.headers.get("x-test-agent-id")
        test_org_id = request.headers.get("x-test-org-id")
        run_id = request.headers.get("x-test-run-id") or request.headers.get(
            "x-octopus-run-id"
        )
        if test_agent_id and test_org_id:
            request.state.actor = {
                "type": "agent",
                "id": test_agent_id,
                "agentId": test_agent_id,
                "orgId": test_org_id,
                "runId": run_id,
                "source": "local_test_header",
            }
    if not hasattr(request.state, "actor") and getattr(
        settings, "local_trusted", False
    ):
        request.state.actor = {
            "type": "board",
            "id": "local-board",
            "userId": "local-board",
            "source": "local_implicit",
        }


async def actor_context_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[object]]
) -> object:
    settings = request.app.state.settings
    _set_actor_context(request, settings)
    return await call_next(request)
