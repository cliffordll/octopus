from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.schema import Issue
from packages.shared.constants.issue import (
    DEFAULT_DELEGATION_CLOSEOUT_MODE,
    DelegationCloseoutMode,
)


DELEGATION_ORIGIN_KIND = "delegation"


@dataclass(frozen=True)
class DelegationBatch:
    parent_id: str
    origin_run_id: str | None
    closeout_mode: DelegationCloseoutMode
    children: tuple[Issue, ...]

    @property
    def requires_parent_summary(self) -> bool:
        return self.closeout_mode == "parent_summary"


def closeout_mode_from_context(context: object) -> DelegationCloseoutMode:
    if isinstance(context, dict):
        value = context.get("closeoutMode")
        if value in {"parent_summary", "child_outputs"}:
            return value
    return DEFAULT_DELEGATION_CLOSEOUT_MODE


class DelegationBatchStore:
    """Owns persistence queries for one parent-Run child delegation batch."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_child(self, child: Issue) -> DelegationBatch | None:
        if child.parent_id is None:
            return None
        return await self.for_parent(
            child.parent_id,
            org_id=child.org_id,
            origin_run_id=child.origin_run_id,
            delegated=child.origin_kind == DELEGATION_ORIGIN_KIND,
        )

    async def for_parent(
        self,
        parent_id: str,
        *,
        org_id: str,
        origin_run_id: str | None,
        delegated: bool = True,
    ) -> DelegationBatch | None:
        criteria = [
            Issue.org_id == org_id,
            Issue.parent_id == parent_id,
            Issue.hidden_at.is_(None),
        ]
        if delegated:
            criteria.extend(
                (
                    Issue.origin_kind == DELEGATION_ORIGIN_KIND,
                    Issue.origin_run_id == origin_run_id,
                )
            )
        rows = (
            (
                await self._session.execute(
                    select(Issue)
                    .where(and_(*criteria))
                    .order_by(Issue.issue_number, Issue.id)
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            return None
        modes = {
            child.closeout_mode or DEFAULT_DELEGATION_CLOSEOUT_MODE for child in rows
        }
        if len(modes) != 1:
            raise ValueError("Delegation batch has conflicting closeout modes")
        return DelegationBatch(
            parent_id=parent_id,
            origin_run_id=origin_run_id,
            closeout_mode=cast(DelegationCloseoutMode, modes.pop()),
            children=tuple(rows),
        )

    async def existing_for_creation(
        self,
        parent: Issue,
        *,
        origin_run_id: str | None,
    ) -> DelegationBatch | None:
        return await self.for_parent(
            parent.id,
            org_id=parent.org_id,
            origin_run_id=origin_run_id,
        )
