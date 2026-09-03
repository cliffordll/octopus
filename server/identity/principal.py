from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, cast


PrincipalType = Literal["user", "agent", "system"]
AccessPrincipalType = Literal["user", "agent"]


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
        if actor_type not in {"user", "agent", "system"}:
            raise ValueError(f"Unsupported actor type: {actor_type}")
        return cls(type=cast(PrincipalType, actor_type), id=actor_id)

    def access_type(self) -> AccessPrincipalType:
        if self.type == "system":
            raise ValueError("System principals do not have persisted access roles")
        return cast(AccessPrincipalType, self.type)
