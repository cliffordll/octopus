from __future__ import annotations

import logging
from typing import Literal

from packages.shared.types.heartbeat import WakeAgentPayload
from packages.shared.types.issue import IssueDetail

from .heartbeat import HeartbeatService

logger = logging.getLogger(__name__)

ActorType = Literal["user", "agent", "system"]
IssueReviewWakeupMutation = Literal[
    "status_to_in_review",
    "status_to_blocked",
    "reviewer_changed_in_review",
    "reviewer_changed_blocked",
    "create_in_review",
    "assignee_done",
]


def _issue_snapshot(issue: IssueDetail) -> dict[str, object]:
    return {
        "id": issue["id"],
        "identifier": issue.get("identifier"),
        "title": issue["title"],
        "description": issue.get("description"),
        "status": issue["status"],
        "priority": issue["priority"],
    }


def build_issue_review_wakeup_payload(
    issue: IssueDetail,
    *,
    mutation: IssueReviewWakeupMutation,
    context_source: str,
) -> WakeAgentPayload:
    blocked_instructions = (
        "The issue is blocked and has been routed to you as reviewer. Decide "
        "whether to confirm this as a human/external blocker, request changes, "
        "approve, or keep a specific follow-up open. If you confirm the blocker "
        "with `blocked`, write the next human action clearly."
        if issue["status"] == "blocked"
        else "The issue is ready for review."
    )
    return {
        "source": "review",
        "triggerDetail": "system",
        "reason": "issue_review_requested",
        "idempotencyKey": (
            f"issue:{issue['id']}:review:{mutation}:{issue.get('updatedAt')}"
        ),
        "payload": {"issueId": issue["id"], "mutation": mutation},
        "contextSnapshot": {
            "issueId": issue["id"],
            "source": context_source,
            "wakeSource": "review",
            "wakeReason": "issue_review_requested",
            "role": "reviewer",
            "issue": _issue_snapshot(issue),
            "reviewInstructions": (
                f"{blocked_instructions} Record one structured reviewer decision "
                "before exiting: approve, request_changes, needs_followup, or "
                "blocked. Use `control-plane issue review`; do not rely on a "
                "free-form comment as the durable outcome. Do not take over "
                "implementation unless explicitly asked."
            ),
        },
    }


async def queue_issue_review_wakeup(
    heartbeat: HeartbeatService,
    issue: IssueDetail,
    *,
    mutation: IssueReviewWakeupMutation,
    context_source: str,
    actor_type: ActorType,
    actor_id: str,
    actor_agent_id: str | None = None,
) -> None:
    reviewer_agent_id = issue.get("reviewerAgentId")
    if not reviewer_agent_id or issue["status"] not in {"in_review", "blocked"}:
        return
    if actor_agent_id and reviewer_agent_id == actor_agent_id:
        return
    try:
        await heartbeat.wakeup(
            reviewer_agent_id,
            build_issue_review_wakeup_payload(
                issue,
                mutation=mutation,
                context_source=context_source,
            ),
            actor_type=actor_type,
            actor_id=actor_id,
            execute_immediately=False,
        )
    except Exception:
        logger.warning(
            "failed to wake reviewer on issue review request",
            extra={"issue_id": issue["id"]},
            exc_info=True,
        )
