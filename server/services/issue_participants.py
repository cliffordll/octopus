from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.schema import Agent, Role, User


@dataclass(frozen=True, slots=True)
class IssueParticipantRef:
    type: str
    id: str


class IssueParticipantService:
    """Validates Human and Agent task participants against organization membership."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def validate_payloads(
        self,
        org_id: str,
        payloads: Sequence[Mapping[str, object]],
    ) -> None:
        participants: set[IssueParticipantRef] = set()
        for payload in payloads:
            participants.update(self._payload_participants(payload))
        if not participants:
            return

        roles = (
            (
                await self._session.execute(
                    select(Role).where(
                        Role.scope_type == "organization",
                        Role.scope_id == org_id,
                        Role.status == "active",
                    )
                )
            )
            .scalars()
            .all()
        )
        active_human_members = {
            IssueParticipantRef(role.principal_type, role.principal_id)
            for role in roles
            if role.principal_type == "user"
        }
        human_participants = {
            participant for participant in participants if participant.type == "user"
        }
        missing_members = sorted(
            human_participants - active_human_members,
            key=lambda participant: (participant.type, participant.id),
        )
        if missing_members:
            raise ValueError(
                "Issue participants must be active organization members: "
                + ", ".join(
                    f"{participant.type}:{participant.id}"
                    for participant in missing_members
                )
            )

        await self._validate_principals(org_id, participants)

    async def _validate_principals(
        self, org_id: str, participants: set[IssueParticipantRef]
    ) -> None:
        agent_ids = {
            participant.id
            for participant in participants
            if participant.type == "agent"
        }
        user_ids = {
            participant.id for participant in participants if participant.type == "user"
        }
        if agent_ids:
            agents = (
                (
                    await self._session.execute(
                        select(Agent).where(
                            Agent.id.in_(agent_ids), Agent.org_id == org_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            missing_agents = sorted(agent_ids - {agent.id for agent in agents})
            if missing_agents:
                raise ValueError(
                    "Issue agents must exist in the organization: "
                    + ", ".join(missing_agents)
                )
        if user_ids:
            users = (
                (await self._session.execute(select(User).where(User.id.in_(user_ids))))
                .scalars()
                .all()
            )
            missing_users = sorted(user_ids - {user.id for user in users})
            if missing_users:
                raise ValueError("Issue users must exist: " + ", ".join(missing_users))

    @staticmethod
    def _payload_participants(
        payload: Mapping[str, object],
    ) -> set[IssueParticipantRef]:
        fields = (
            ("assigneeAgentId", "agent"),
            ("assigneeUserId", "user"),
            ("reviewerAgentId", "agent"),
            ("reviewerUserId", "user"),
        )
        return {
            IssueParticipantRef(participant_type, value)
            for field, participant_type in fields
            if isinstance((value := payload.get(field)), str) and value
        }
