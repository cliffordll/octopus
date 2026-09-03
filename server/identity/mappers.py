from __future__ import annotations

from collections.abc import Mapping
from typing import ClassVar

from .principal import PrincipalRef


class DualPrincipalMapper:
    user_field: ClassVar[str]
    agent_field: ClassVar[str]

    def __init_subclass__(cls) -> None:
        super().__init_subclass__()
        if not getattr(cls, "user_field", None) or not getattr(
            cls, "agent_field", None
        ):
            raise TypeError("Dual principal mappers must declare both fields")

    @classmethod
    def read(cls, record: object) -> PrincipalRef | None:
        user_id = cls._value(record, cls.user_field)
        agent_id = cls._value(record, cls.agent_field)
        if user_id is not None and agent_id is not None:
            raise ValueError(
                f"Both {cls.user_field} and {cls.agent_field} are populated"
            )
        if user_id is not None:
            return PrincipalRef(type="user", id=str(user_id))
        if agent_id is not None:
            return PrincipalRef(type="agent", id=str(agent_id))
        return None

    @classmethod
    def write_values(cls, principal: PrincipalRef | None) -> dict[str, str | None]:
        if principal is None:
            return {cls.user_field: None, cls.agent_field: None}
        if principal.type == "system":
            raise ValueError("System principals cannot populate user/agent fields")
        return {
            cls.user_field: principal.id if principal.type == "user" else None,
            cls.agent_field: principal.id if principal.type == "agent" else None,
        }

    @staticmethod
    def _value(record: object, field: str) -> object:
        if isinstance(record, Mapping):
            return record.get(field)
        return getattr(record, field, None)


class IssueAssigneeMapper(DualPrincipalMapper):
    user_field = "assignee_user_id"
    agent_field = "assignee_agent_id"


class IssueReviewerMapper(DualPrincipalMapper):
    user_field = "reviewer_user_id"
    agent_field = "reviewer_agent_id"


class IssueCreatorMapper(DualPrincipalMapper):
    user_field = "created_by_user_id"
    agent_field = "created_by_agent_id"


class CommentAuthorMapper(DualPrincipalMapper):
    user_field = "author_user_id"
    agent_field = "author_agent_id"


class ApprovalRequesterMapper(DualPrincipalMapper):
    user_field = "requested_by_user_id"
    agent_field = "requested_by_agent_id"


class DocumentCreatorMapper(DualPrincipalMapper):
    user_field = "created_by_user_id"
    agent_field = "created_by_agent_id"
