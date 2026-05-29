from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.heartbeat import get_run, list_run_events
from packages.database.schema import (
    Agent,
    HeartbeatRun,
    Issue,
    Organization,
)
from packages.shared.types.heartbeat import HeartbeatRunEvent

from .heartbeat import HeartbeatService


class RunIntelligenceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_runs(
        self,
        org_id: str,
        *,
        updated_after: str | None = None,
        created_before: str | None = None,
        run_id_prefix: str | None = None,
        agent_id: str | None = None,
        status: str | None = None,
        runtime: str | None = None,
        issue_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        statement = (
            select(HeartbeatRun, Agent, Organization)
            .join(Agent, Agent.id == HeartbeatRun.agent_id)
            .join(Organization, Organization.id == HeartbeatRun.org_id)
            .where(HeartbeatRun.org_id == org_id)
        )
        if updated_after:
            statement = statement.where(
                HeartbeatRun.updated_at > _parse_datetime(updated_after)
            )
        if created_before:
            statement = statement.where(
                HeartbeatRun.created_at < _parse_datetime(created_before)
            )
        if run_id_prefix:
            statement = statement.where(HeartbeatRun.id.like(f"{run_id_prefix}%"))
        if agent_id:
            statement = statement.where(HeartbeatRun.agent_id == agent_id)
        if status:
            statement = statement.where(HeartbeatRun.status == status)
        if runtime:
            statement = statement.where(Agent.agent_runtime_type == runtime)
        result = await self._session.execute(
            statement.order_by(
                HeartbeatRun.created_at.desc(), HeartbeatRun.id.desc()
            ).limit(max(1, min(limit, 1000)))
        )
        rows = list(result.all())
        observed = [
            await self._to_observed_run(run, agent, org)
            for run, agent, org in rows
            if _matches_issue(run, issue_id)
        ]
        return observed

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        result = await self._session.execute(
            select(HeartbeatRun, Agent, Organization)
            .join(Agent, Agent.id == HeartbeatRun.agent_id)
            .join(Organization, Organization.id == HeartbeatRun.org_id)
            .where(HeartbeatRun.id == run_id)
        )
        row = result.one_or_none()
        if row is None:
            return None
        run, agent, org = row
        return await self._to_observed_run(run, agent, org)

    async def list_events(self, run_id: str) -> list[HeartbeatRunEvent] | None:
        run = await get_run(self._session, run_id)
        if run is None:
            return None
        events = await list_run_events(self._session, run_id, limit=1000)
        heartbeat = HeartbeatService(self._session)
        return [heartbeat._to_event(event) for event in events]

    async def read_log(self, run_id: str) -> dict[str, str] | None:
        run = await get_run(self._session, run_id)
        if run is None:
            return None
        log = await HeartbeatService(self._session).read_log(run_id)
        return {"content": log["content"] if log is not None else ""}

    async def _to_observed_run(
        self, run: HeartbeatRun, agent: Agent, org: Organization
    ) -> dict[str, Any]:
        issue = await self._issue_for_run(run)
        return {
            "run": HeartbeatService(self._session)._to_run(run),
            "agentName": agent.name,
            "orgName": org.name,
            "issue": _issue_to_dict(issue) if issue is not None else None,
            "bundle": {
                "agentRuntimeType": agent.agent_runtime_type,
                "agentConfigRevisionId": None,
                "agentConfigRevisionCreatedAt": None,
                "agentConfigFingerprint": _fingerprint(agent.agent_runtime_config),
                "runtimeConfigFingerprint": _fingerprint(agent.runtime_config),
            },
            "langfuse": None,
        }

    async def _issue_for_run(self, run: HeartbeatRun) -> Issue | None:
        issue_id = _issue_id(run)
        if issue_id is None:
            return None
        return await self._session.get(Issue, issue_id)


def _matches_issue(run: HeartbeatRun, issue_id: str | None) -> bool:
    return issue_id is None or _issue_id(run) == issue_id


def _issue_id(run: HeartbeatRun) -> str | None:
    snapshot = run.context_snapshot if isinstance(run.context_snapshot, dict) else {}
    value = snapshot.get("issueId") or snapshot.get("primaryIssueId")
    return value if isinstance(value, str) and value else None


def _parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _fingerprint(value: Any) -> str:
    encoded = json.dumps(value or {}, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _issue_to_dict(issue: Issue) -> dict[str, Any]:
    return {
        "id": issue.id,
        "orgId": issue.org_id,
        "projectId": issue.project_id,
        "title": issue.title,
        "description": issue.description,
        "status": issue.status,
        "priority": issue.priority,
        "assigneeAgentId": issue.assignee_agent_id,
        "identifier": issue.identifier,
        "createdAt": issue.created_at.isoformat(),
        "updatedAt": issue.updated_at.isoformat(),
    }
