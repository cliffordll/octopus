from __future__ import annotations

from dataclasses import dataclass
import re

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.heartbeat import (
    list_wakeup_requests_by_status,
    update_wakeup_request,
)
from packages.shared.types.agent import Agent
from packages.shared.types.heartbeat import WakeAgentPayload
from packages.shared.types.issue import IssueDetail

from .agents import AgentService
from .heartbeat import HeartbeatService


_MENTION_PATTERN = re.compile(r"@([A-Za-z0-9][A-Za-z0-9_.-]*)")
_DEFERRED_CONTEXT_KEY = "__deferredContextSnapshot"


@dataclass(frozen=True)
class CommentWakeupTarget:
    agent_id: str
    explicit_mention: bool


@dataclass(frozen=True)
class CommentWakeupDecision:
    targets: tuple[CommentWakeupTarget, ...]


class IssueCommentWakeupPolicy:
    """Preserve Issue ownership while accepting comments as durable commands."""

    @staticmethod
    def mentioned_tokens(body: str) -> set[str]:
        return {
            match.group(1).strip().lower() for match in _MENTION_PATTERN.finditer(body)
        }

    def decide(
        self,
        *,
        issue: IssueDetail,
        body: str,
        agents: list[Agent],
        actor_type: str,
        actor_id: str,
    ) -> CommentWakeupDecision:
        if issue["status"] in {"backlog", "done", "cancelled"}:
            return CommentWakeupDecision(())
        tokens = self.mentioned_tokens(body)
        assignee_agent_id = issue.get("assigneeAgentId")
        targets: list[CommentWakeupTarget] = []
        for agent in agents:
            if assignee_agent_id:
                if agent["id"] != assignee_agent_id:
                    continue
                if actor_type == "agent" and actor_id == agent["id"]:
                    continue
                targets.append(
                    CommentWakeupTarget(
                        agent_id=agent["id"],
                        explicit_mention=False,
                    )
                )
                continue
            aliases = {
                value.lower()
                for value in (agent["id"], agent["name"], agent["urlKey"])
                if isinstance(value, str) and value
            }
            explicitly_mentioned = not tokens.isdisjoint(aliases)
            if not explicitly_mentioned:
                continue
            if actor_type == "agent" and actor_id == agent["id"]:
                continue
            targets.append(
                CommentWakeupTarget(
                    agent_id=agent["id"],
                    explicit_mention=explicitly_mentioned,
                )
            )
        unique = {target.agent_id: target for target in targets}
        return CommentWakeupDecision(tuple(unique.values()))


@dataclass(frozen=True)
class CommentWakeupResult:
    dispatch_agent_ids: tuple[str, ...]
    merged_agent_ids: tuple[str, ...]


class IssueCommentWakeupCoordinator:
    """Persist comment wakeups and coalesce work for an already active Issue."""

    def __init__(
        self,
        session: AsyncSession,
        heartbeat: HeartbeatService,
        agent_service: AgentService,
        *,
        policy: IssueCommentWakeupPolicy | None = None,
    ) -> None:
        self._session = session
        self._heartbeat = heartbeat
        self._agent_service = agent_service
        self._policy = policy or IssueCommentWakeupPolicy()

    async def process(
        self,
        *,
        issue: IssueDetail,
        comment_id: str,
        comment_body: str,
        actor_type: str,
        actor_id: str,
    ) -> CommentWakeupResult:
        agents = await self._agent_service.list_for_org(issue["orgId"])
        decision = self._policy.decide(
            issue=issue,
            body=comment_body,
            agents=agents,
            actor_type=actor_type,
            actor_id=actor_id,
        )
        dispatch: list[str] = []
        merged: list[str] = []
        for target in decision.targets:
            agent_id = target.agent_id
            if await self._merge_into_deferred_wakeup(
                issue_id=issue["id"],
                agent_id=agent_id,
                comment_id=comment_id,
                comment_body=comment_body,
            ):
                merged.append(agent_id)
                continue
            run = await self._heartbeat.wakeup(
                agent_id,
                self._mention_payload(
                    issue=issue,
                    agent_id=agent_id,
                    comment_id=comment_id,
                    comment_body=comment_body,
                    explicit_mention=target.explicit_mention,
                ),
                actor_type=actor_type,
                actor_id=actor_id,
                execute_immediately=False,
            )
            if run is not None:
                dispatch.append(agent_id)
        return CommentWakeupResult(tuple(dispatch), tuple(merged))

    async def _merge_into_deferred_wakeup(
        self,
        *,
        issue_id: str,
        agent_id: str,
        comment_id: str,
        comment_body: str,
    ) -> bool:
        for status in ("deferred_issue_execution",):
            wakeups = await list_wakeup_requests_by_status(
                self._session,
                agent_id,
                status,
            )
            for wakeup in wakeups:
                payload = dict(wakeup.payload or {})
                if payload.get("issueId") != issue_id:
                    continue
                context = dict(payload.get(_DEFERRED_CONTEXT_KEY) or {})
                comment_ids = [
                    value
                    for value in context.get("commentIds", [])
                    if isinstance(value, str)
                ]
                previous_comment_id = context.get("commentId")
                if (
                    isinstance(previous_comment_id, str)
                    and previous_comment_id not in comment_ids
                ):
                    comment_ids.append(previous_comment_id)
                if comment_id in comment_ids:
                    return True
                comment_ids.append(comment_id)
                context.update(
                    {
                        "commentId": comment_id,
                        "commentIds": comment_ids,
                        "commentBody": comment_body,
                    }
                )
                payload[_DEFERRED_CONTEXT_KEY] = context
                await update_wakeup_request(
                    self._session,
                    wakeup.id,
                    {
                        "payload": payload,
                        "coalesced_count": wakeup.coalesced_count + 1,
                    },
                )
                return True
        return False

    @staticmethod
    def _mention_payload(
        *,
        issue: IssueDetail,
        agent_id: str,
        comment_id: str,
        comment_body: str,
        explicit_mention: bool,
    ) -> WakeAgentPayload:
        reason = (
            "issue_comment_mentioned" if explicit_mention else "issue_comment_added"
        )
        source = "on_demand" if explicit_mention else "assignment"
        mutation = "comment_mention" if explicit_mention else "comment"
        wake_source = "mention" if explicit_mention else "assignment"
        return {
            "source": source,
            "triggerDetail": "system",
            "reason": reason,
            "idempotencyKey": (
                f"issue:{issue['id']}:comment:{comment_id}:mention:{agent_id}"
            ),
            "payload": {
                "issueId": issue["id"],
                "mutation": mutation,
                "commentId": comment_id,
            },
            "contextSnapshot": {
                "issueId": issue["id"],
                "source": "issue.comment",
                "wakeSource": wake_source,
                "wakeReason": reason,
                "commentId": comment_id,
                "commentBody": comment_body,
                "issue": {
                    "id": issue["id"],
                    "title": issue["title"],
                    "description": issue.get("description"),
                    "status": issue["status"],
                    "priority": issue["priority"],
                },
            },
        }
