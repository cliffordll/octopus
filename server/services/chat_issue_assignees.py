from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.agents import get_agent_by_id
from server.roles.directory import RoleDirectoryEntry, RoleDirectoryService


class ChatIssueAssigneeResolver:
    """Resolve chat-proposed member names into typed organization principals."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._directory = RoleDirectoryService(session)

    async def resolve(self, org_id: str, proposal: Mapping[str, Any]) -> dict[str, Any]:
        resolved = dict(proposal)
        agent_ref = self._reference(resolved.get("assigneeAgentId"))
        user_ref = self._reference(resolved.get("assigneeUserId"))
        if not agent_ref and not user_ref:
            return resolved

        if agent_ref and not user_ref:
            agent = await get_agent_by_id(self._session, agent_ref)
            if agent is not None and agent.org_id == org_id:
                return resolved

        entries = [
            entry
            for entry in await self._directory.list_organization(org_id)
            if entry.role.status == "active"
        ]
        reference = user_ref or agent_ref
        assert reference is not None
        expected_type = "user" if user_ref else None
        match = self._match(entries, reference, expected_type=expected_type)
        resolved.pop("assigneeAgentId", None)
        resolved.pop("assigneeUserId", None)
        resolved[
            "assigneeUserId"
            if match.role.principal_type == "user"
            else "assigneeAgentId"
        ] = match.role.principal_id
        return resolved

    @staticmethod
    def _reference(value: object) -> str | None:
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _match(
        entries: list[RoleDirectoryEntry],
        reference: str,
        *,
        expected_type: str | None,
    ) -> RoleDirectoryEntry:
        normalized = reference.casefold()
        exact_id = [
            entry
            for entry in entries
            if entry.role.principal_id == reference
            and (expected_type is None or entry.role.principal_type == expected_type)
        ]
        candidates = exact_id or [
            entry
            for entry in entries
            if entry.display_name.casefold() == normalized
            and (expected_type is None or entry.role.principal_type == expected_type)
        ]
        if not candidates and expected_type == "user":
            candidates = [
                entry
                for entry in entries
                if entry.display_name.casefold() == normalized
                or entry.role.principal_id == reference
            ]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise ValueError(
                f"Issue assignee '{reference}' is not an active organization member"
            )
        raise ValueError(
            f"Issue assignee '{reference}' is ambiguous; use the member ID"
        )
