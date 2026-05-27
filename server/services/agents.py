from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import re
from collections.abc import Sequence
from typing import Any, cast
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import (
    create_agent,
    get_agent_by_id,
    list_org_agents,
    update_agent,
)
from packages.database.schema import Agent as AgentRow
from packages.shared.constants.agent import (
    AGENT_DICEBEAR_NOTIONISTS_ICON_PREFIX,
    DEFAULT_AGENT_RUNTIME_TYPE,
    DEFAULT_AGENT_STATUS,
    DEFAULT_AGENT_ROLE,
    AgentRole,
    AgentRuntimeType,
    AgentStatus,
    PauseReason,
)
from packages.shared.types.agent import (
    Agent,
    AgentAccessState,
    AgentChainOfCommandEntry,
    AgentDetail,
    CreateAgentPayload,
    UpdateAgentPayload,
)

_URL_KEY_PATTERN = re.compile(r"[^a-z0-9]+")


class AgentConflictError(ValueError):
    pass


def _normalize_url_key(value: str | None) -> str | None:
    if not value:
        return None
    normalized = _URL_KEY_PATTERN.sub("-", value.strip().lower()).strip("-")
    return normalized or None


def _derive_url_key(name: str | None, fallback: str | None = None) -> str:
    return _normalize_url_key(name) or _normalize_url_key(fallback) or "agent"


def _workspace_key(agent_id: str, name: str) -> str:
    normalized = re.sub(r"[^a-f0-9]", "", agent_id.lower())
    short_id = (
        normalized[:8]
        if len(normalized) >= 8
        else hashlib.sha1(agent_id.encode("utf-8")).hexdigest()[:8]
    )
    return f"{_derive_url_key(name)}--{short_id}"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _normalized_permissions(value: object, role: str) -> dict[str, bool]:
    if isinstance(value, dict) and isinstance(value.get("canCreateAgents"), bool):
        return {"canCreateAgents": bool(value["canCreateAgents"])}
    return {"canCreateAgents": role == "ceo"}


class AgentService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(self, org_id: str) -> list[Agent]:
        rows = await list_org_agents(self._session, org_id)
        return [self._to_agent(row) for row in rows if row.status != "terminated"]

    async def get(self, agent_id: str) -> Agent | None:
        row = await get_agent_by_id(self._session, agent_id)
        return self._to_agent(row) if row is not None else None

    async def get_detail(self, agent_id: str) -> AgentDetail | None:
        row = await get_agent_by_id(self._session, agent_id)
        if row is None:
            return None
        detail: AgentDetail = {
            **self._to_agent(row),
            "chainOfCommand": await self._chain_of_command(row),
            "access": self._access_state(row),
        }
        return detail

    async def create_agent(
        self,
        org_id: str,
        payload: CreateAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> Agent:
        manager_id = payload.get("reportsTo")
        if manager_id is not None:
            await self._validate_manager(org_id, manager_id)
        existing = await list_org_agents(self._session, org_id)
        name = self._deduplicate_name(
            str(payload.get("name", "Agent")).strip() or "Agent", existing
        )
        agent_id = str(uuid.uuid4())
        role = cast(AgentRole, payload.get("role", DEFAULT_AGENT_ROLE))
        values: dict[str, Any] = {
            "id": agent_id,
            "org_id": org_id,
            "name": name,
            "workspace_key": _workspace_key(agent_id, name),
            "role": role,
            "title": payload.get("title"),
            "icon": payload.get("icon")
            or f"{AGENT_DICEBEAR_NOTIONISTS_ICON_PREFIX}{uuid.uuid4()}",
            "status": DEFAULT_AGENT_STATUS,
            "reports_to": payload.get("reportsTo"),
            "capabilities": payload.get("capabilities"),
            "agent_runtime_type": payload.get(
                "agentRuntimeType", DEFAULT_AGENT_RUNTIME_TYPE
            ),
            "agent_runtime_config": dict(payload.get("agentRuntimeConfig", {})),
            "runtime_config": dict(payload.get("runtimeConfig", {})),
            "budget_monthly_cents": payload.get("budgetMonthlyCents", 0),
            "spent_monthly_cents": 0,
            "permissions": _normalized_permissions(payload.get("permissions"), role),
            "metadata_json": payload.get("metadata"),
        }
        row = await create_agent(self._session, values)
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="agent.created",
            entity_type="agent",
            entity_id=row.id,
            details={"name": row.name, "role": row.role},
        )
        return self._to_agent(row)

    async def update_agent(
        self,
        agent_id: str,
        payload: UpdateAgentPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> Agent | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        if existing.status == "terminated" and payload.get("status") not in (
            None,
            "terminated",
        ):
            raise AgentConflictError("Terminated agents cannot be resumed")
        if existing.status == "pending_approval" and payload.get("status") not in (
            None,
            "pending_approval",
            "terminated",
        ):
            raise AgentConflictError(
                "Pending approval agents cannot be activated directly"
            )
        if "reportsTo" in payload:
            manager_id = payload["reportsTo"]
            if manager_id is not None:
                await self._validate_manager(existing.org_id, manager_id)
            await self._validate_no_cycle(agent_id, manager_id)
        if "name" in payload:
            next_key = _derive_url_key(payload["name"])
            for row in await list_org_agents(self._session, existing.org_id):
                if (
                    row.id != existing.id
                    and row.status != "terminated"
                    and _derive_url_key(row.name) == next_key
                ):
                    raise AgentConflictError(
                        f"Agent shortname '{next_key}' is already in use in this organization"
                    )
        patch = dict(payload)
        replace_runtime_config = patch.pop("replaceAgentRuntimeConfig", False)
        if "agentRuntimeConfig" in patch and not replace_runtime_config:
            patch["agentRuntimeConfig"] = {
                **existing.agent_runtime_config,
                **cast(dict[str, Any], patch["agentRuntimeConfig"]),
            }
        field_map = {
            "name": "name",
            "role": "role",
            "title": "title",
            "icon": "icon",
            "reportsTo": "reports_to",
            "capabilities": "capabilities",
            "agentRuntimeType": "agent_runtime_type",
            "agentRuntimeConfig": "agent_runtime_config",
            "runtimeConfig": "runtime_config",
            "budgetMonthlyCents": "budget_monthly_cents",
            "spentMonthlyCents": "spent_monthly_cents",
            "status": "status",
            "metadata": "metadata_json",
        }
        values = {
            field_map[key]: value for key, value in patch.items() if key in field_map
        }
        row = await update_agent(self._session, agent_id, values)
        if row is None:
            return None
        if patch:
            await insert_activity_log(
                self._session,
                org_id=row.org_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action="agent.updated",
                entity_type="agent",
                entity_id=row.id,
                details=patch,
            )
        return self._to_agent(row)

    async def pause_agent(
        self, agent_id: str, *, actor_type: str, actor_id: str
    ) -> Agent | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        if existing.status == "terminated":
            raise AgentConflictError("Cannot pause terminated agent")
        row = await update_agent(
            self._session,
            agent_id,
            {
                "status": "paused",
                "pause_reason": "manual",
                "paused_at": datetime.now(UTC),
            },
        )
        if row is not None:
            await self._record_lifecycle(row, "agent.paused", actor_type, actor_id)
        return self._to_agent(row) if row is not None else None

    async def resume_agent(
        self, agent_id: str, *, actor_type: str, actor_id: str
    ) -> Agent | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        if existing.status == "terminated":
            raise AgentConflictError("Cannot resume terminated agent")
        if existing.status == "pending_approval":
            raise AgentConflictError("Pending approval agents cannot be resumed")
        row = await update_agent(
            self._session,
            agent_id,
            {"status": "idle", "pause_reason": None, "paused_at": None},
        )
        if row is not None:
            await self._record_lifecycle(row, "agent.resumed", actor_type, actor_id)
        return self._to_agent(row) if row is not None else None

    async def terminate_agent(
        self, agent_id: str, *, actor_type: str, actor_id: str
    ) -> Agent | None:
        existing = await get_agent_by_id(self._session, agent_id)
        if existing is None:
            return None
        row = await update_agent(
            self._session,
            agent_id,
            {"status": "terminated", "pause_reason": None, "paused_at": None},
        )
        if row is not None:
            await self._record_lifecycle(row, "agent.terminated", actor_type, actor_id)
        return self._to_agent(row) if row is not None else None

    async def _record_lifecycle(
        self, row: AgentRow, action: str, actor_type: str, actor_id: str
    ) -> None:
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type="agent",
            entity_id=row.id,
        )

    async def _validate_manager(self, org_id: str, manager_id: str) -> None:
        manager = await get_agent_by_id(self._session, manager_id)
        if manager is None:
            raise ValueError("Manager not found")
        if manager.org_id != org_id:
            raise ValueError("Manager must belong to same organization")

    async def _validate_no_cycle(self, agent_id: str, manager_id: str | None) -> None:
        if manager_id is None:
            return
        if manager_id == agent_id:
            raise ValueError("Agent cannot report to itself")
        current = manager_id
        while current is not None:
            if current == agent_id:
                raise ValueError("Reporting relationship would create cycle")
            row = await get_agent_by_id(self._session, current)
            current = row.reports_to if row is not None else None

    def _deduplicate_name(self, requested: str, existing: Sequence[AgentRow]) -> str:
        used = {
            _derive_url_key(row.name) for row in existing if row.status != "terminated"
        }
        if _derive_url_key(requested) not in used:
            return requested
        index = 2
        while _derive_url_key(f"{requested} {index}") in used:
            index += 1
        return f"{requested} {index}"

    async def _chain_of_command(self, row: AgentRow) -> list[AgentChainOfCommandEntry]:
        chain: list[AgentChainOfCommandEntry] = []
        manager_id = row.reports_to
        while manager_id is not None:
            manager = await get_agent_by_id(self._session, manager_id)
            if manager is None:
                break
            chain.append(
                {
                    "id": manager.id,
                    "name": manager.name,
                    "role": cast(AgentRole, manager.role),
                    "title": manager.title,
                }
            )
            manager_id = manager.reports_to
        return chain

    def _access_state(self, row: AgentRow) -> AgentAccessState:
        return {
            "canAssignTasks": row.role == "ceo",
            "taskAssignSource": "ceo_role" if row.role == "ceo" else "none",
            "membership": None,
            "grants": [],
        }

    def _to_agent(self, row: AgentRow) -> Agent:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "name": row.name,
            "urlKey": _derive_url_key(row.name, row.id),
            "role": cast(AgentRole, row.role),
            "title": row.title,
            "icon": row.icon,
            "status": cast(AgentStatus, row.status),
            "reportsTo": row.reports_to,
            "capabilities": row.capabilities,
            "agentRuntimeType": cast(AgentRuntimeType, row.agent_runtime_type),
            "agentRuntimeConfig": row.agent_runtime_config,
            "runtimeConfig": row.runtime_config,
            "budgetMonthlyCents": row.budget_monthly_cents,
            "spentMonthlyCents": row.spent_monthly_cents,
            "pauseReason": cast(PauseReason | None, row.pause_reason),
            "pausedAt": _iso(row.paused_at),
            "permissions": cast(
                Any, _normalized_permissions(row.permissions, row.role)
            ),
            "lastHeartbeatAt": _iso(row.last_heartbeat_at),
            "metadata": row.metadata_json,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }
