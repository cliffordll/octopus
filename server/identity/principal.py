from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast


PrincipalType = Literal["user", "agent", "system"]
MembershipPrincipalType = Literal["user", "agent"]


@dataclass(frozen=True, slots=True)
class PrincipalRef:
    type: PrincipalType
    id: str

    def __post_init__(self) -> None:
        if self.type not in {"user", "agent", "system"}:
            raise ValueError(f"Unsupported principal type: {self.type}")
        if not self.id.strip():
            raise ValueError("Principal id must not be empty")

    @classmethod
    def from_actor(cls, actor_type: str, actor_id: str) -> PrincipalRef:
        normalized_type = "user" if actor_type == "board" else actor_type
        if normalized_type not in {"user", "agent", "system"}:
            raise ValueError(f"Unsupported actor type: {actor_type}")
        return cls(type=cast(PrincipalType, normalized_type), id=actor_id)

    def membership_type(self) -> MembershipPrincipalType:
        if self.type == "system":
            raise ValueError("System principals do not have organization memberships")
        return cast(MembershipPrincipalType, self.type)
