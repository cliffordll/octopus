from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import re
from typing import Literal

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


InstructionDelivery = Literal["queued", "merged", "ignored"]


class AdapterInstructionChannel(ABC):
    """Extension point for delivering durable instructions to an Adapter owner."""

    @abstractmethod
    async def deliver(
        self,
        *,
        issue: IssueDetail,
        target: CommentWakeupTarget,
        comment_id: str,
        comment_body: str,
        actor_type: str,
        actor_id: str,
    ) -> InstructionDelivery:
        """Deliver or coalesce one instruction without starting duplicate Issue work."""


class FollowupRunInstructionChannel(AdapterInstructionChannel):
    """Deliver CLI Adapter instructions through a coalesced follow-up Run."""

    def __init__(self, session: AsyncSession, heartbeat: HeartbeatService) -> None:
        self._session = session
        self._heartbeat = heartbeat

    async def deliver(
        self,
        *,
        issue: IssueDetail,
        target: CommentWakeupTarget,
        comment_id: str,
        comment_body: str,
        actor_type: str,
        actor_id: str,
    ) -> InstructionDelivery:
        if await self._merge_into_deferred_wakeup(
            issue_id=issue["id"],
            agent_id=target.agent_id,
            comment_id=comment_id,
            comment_body=comment_body,
        ):
            return "merged"
        run = await self._heartbeat.wakeup(
            target.agent_id,
            IssueCommentWakeupCoordinator._mention_payload(
                issue=issue,
                agent_id=target.agent_id,
                comment_id=comment_id,
                comment_body=comment_body,
                explicit_mention=target.explicit_mention,
            ),
            actor_type=actor_type,
            actor_id=actor_id,
            execute_immediately=False,
        )
        return "queued" if run is not None else "ignored"

    async def _merge_into_deferred_wakeup(
        self,
        *,
        issue_id: str,
        agent_id: str,
        comment_id: str,
        comment_body: str,
    ) -> bool:
        for wakeup in await list_wakeup_requests_by_status(
            self._session,
            agent_id,
            "deferred_issue_execution",
        ):
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


class IssueCommentWakeupCoordinator:
    """Persist comment wakeups and coalesce work for an already active Issue."""

    def __init__(
        self,
        session: AsyncSession,
        heartbeat: HeartbeatService,
        agent_service: AgentService,
        *,
        policy: IssueCommentWakeupPolicy | None = None,
        channel: AdapterInstructionChannel | None = None,
    ) -> None:
        self._agent_service = agent_service
        self._policy = policy or IssueCommentWakeupPolicy()
        self._channel = channel or FollowupRunInstructionChannel(session, heartbeat)

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
            delivery = await self._channel.deliver(
                issue=issue,
                target=target,
                comment_id=comment_id,
                comment_body=comment_body,
                actor_type=actor_type,
                actor_id=actor_id,
            )
            if delivery == "merged":
                merged.append(target.agent_id)
            elif delivery == "queued":
                dispatch.append(target.agent_id)
        return CommentWakeupResult(tuple(dispatch), tuple(merged))

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
