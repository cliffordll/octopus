from __future__ import annotations

import logging
from typing import Literal

from packages.shared.types.heartbeat import WakeAgentPayload
from packages.shared.types.issue import IssueDetail

from .heartbeat import HeartbeatService

logger = logging.getLogger(__name__)


ActorType = Literal["user", "agent", "system"]


async def queue_issue_assignment_wakeup(
    heartbeat: HeartbeatService,
    issue: IssueDetail,
    *,
    reason: str,
    mutation: str,
    context_source: str,
    actor_type: ActorType,
    actor_id: str,
) -> None:
    assignee_agent_id = issue.get("assigneeAgentId")
    if not assignee_agent_id or issue["status"] == "backlog":
        return

    payload: WakeAgentPayload = {
        "source": "assignment",
        "triggerDetail": "system",
        "reason": reason,
        "payload": {"issueId": issue["id"], "mutation": mutation},
        "contextSnapshot": {
            "issueId": issue["id"],
            "source": context_source,
            "wakeSource": "assignment",
            "wakeReason": reason,
            "issue": {
                "id": issue["id"],
                "title": issue["title"],
                "description": issue.get("description"),
                "status": issue["status"],
                "priority": issue["priority"],
            },
        },
    }
    try:
        await heartbeat.wakeup(
            assignee_agent_id,
            payload,
            actor_type=actor_type,
            actor_id=actor_id,
            execute_immediately=False,
        )
    except Exception:
        logger.warning(
            "failed to wake assignee on issue assignment",
            extra={"issue_id": issue["id"]},
            exc_info=True,
        )
