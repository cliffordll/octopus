from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.schema import Issue
from packages.shared.types.issue import DelegationCloseoutPolicy


DELEGATION_ORIGIN_KIND = "delegation"
DEFAULT_DELEGATION_CLOSEOUT_POLICY: DelegationCloseoutPolicy = {
    "version": 1,
    "mode": "child_outputs_are_final",
}
PARENT_OUTPUT_REQUIRED_POLICY: DelegationCloseoutPolicy = {
    "version": 1,
    "mode": "parent_output_required",
    "requirements": {
        "minimumOutputs": 1,
        "primaryOutputRequired": True,
    },
}


@dataclass(frozen=True)
class DelegationBatch:
    parent_id: str
    origin_run_id: str | None
    closeout_policy: DelegationCloseoutPolicy
    children: tuple[Issue, ...]

    @property
    def requires_parent_output(self) -> bool:
        return self.closeout_policy["mode"] == "parent_output_required"


def normalize_closeout_policy(value: object) -> DelegationCloseoutPolicy:
    if not isinstance(value, dict):
        return cast(DelegationCloseoutPolicy, dict(DEFAULT_DELEGATION_CLOSEOUT_POLICY))
    mode = value.get("mode")
    if mode == "parent_output_required":
        raw_requirements = value.get("requirements")
        requirements = raw_requirements if isinstance(raw_requirements, dict) else {}
        minimum_outputs = requirements.get("minimumOutputs", 1)
        primary_required = requirements.get("primaryOutputRequired", True)
        return {
            "version": 1,
            "mode": "parent_output_required",
            "requirements": {
                "minimumOutputs": (
                    minimum_outputs
                    if isinstance(minimum_outputs, int)
                    and not isinstance(minimum_outputs, bool)
                    and minimum_outputs >= 1
                    else 1
                ),
                "primaryOutputRequired": primary_required is not False,
            },
        }
    return cast(DelegationCloseoutPolicy, dict(DEFAULT_DELEGATION_CLOSEOUT_POLICY))


def closeout_policy_from_context(context: object) -> DelegationCloseoutPolicy:
    if isinstance(context, dict):
        return normalize_closeout_policy(context.get("closeoutPolicy"))
    return cast(DelegationCloseoutPolicy, dict(DEFAULT_DELEGATION_CLOSEOUT_POLICY))


class DelegationBatchStore:
    """Owns persistence queries for one parent-Run child delegation batch."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def for_child(self, child: Issue) -> DelegationBatch | None:
        if child.parent_id is None:
            return None
        if child.origin_kind != DELEGATION_ORIGIN_KIND or child.origin_run_id is None:
            return await self.for_parent(
                child.parent_id,
                org_id=child.org_id,
                origin_run_id=None,
                delegated=False,
                fallback_policy=PARENT_OUTPUT_REQUIRED_POLICY,
            )
        return await self.for_parent(
            child.parent_id,
            org_id=child.org_id,
            origin_run_id=child.origin_run_id,
            delegated=True,
        )

    async def latest_for_parent(
        self, parent_id: str, *, org_id: str
    ) -> DelegationBatch | None:
        """Return the newest persisted delegated batch for a parent."""

        latest_origin = (
            await self._session.execute(
                select(Issue.origin_run_id)
                .where(
                    Issue.org_id == org_id,
                    Issue.parent_id == parent_id,
                    Issue.origin_kind == DELEGATION_ORIGIN_KIND,
                    Issue.origin_run_id.is_not(None),
                    Issue.hidden_at.is_(None),
                )
                .order_by(Issue.created_at.desc(), Issue.issue_number.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_origin is None:
            return None
        return await self.for_parent(
            parent_id,
            org_id=org_id,
            origin_run_id=latest_origin,
        )

    async def for_parent(
        self,
        parent_id: str,
        *,
        org_id: str,
        origin_run_id: str | None,
        delegated: bool = True,
        fallback_policy: DelegationCloseoutPolicy | None = None,
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
        policies = {
            _policy_key(
                normalize_closeout_policy(child.closeout_policy or fallback_policy)
            )
            for child in rows
        }
        if len(policies) != 1:
            raise ValueError("Delegation batch has conflicting closeout policies")
        return DelegationBatch(
            parent_id=parent_id,
            origin_run_id=origin_run_id,
            closeout_policy=normalize_closeout_policy(
                rows[0].closeout_policy or fallback_policy
            ),
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


def _policy_key(policy: DelegationCloseoutPolicy) -> tuple[Any, ...]:
    requirements = policy.get("requirements", {})
    return (
        policy["version"],
        policy["mode"],
        requirements.get("minimumOutputs"),
        requirements.get("primaryOutputRequired"),
    )
