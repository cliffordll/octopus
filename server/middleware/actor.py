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
        test_agent_id = request.headers.get("x-test-agent-id")
        test_org_id = request.headers.get("x-test-org-id")
        run_id = (
            request.headers.get("x-test-run-id")
            or request.headers.get("x-rudder-run-id")
            or request.headers.get("x-control-plane-run-id")
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
    return await call_next(request)
