from __future__ import annotations

from typing import Protocol


class ParentContinuationHost(Protocol):
    async def _queue_parent_continuation_for_settled_child_impl(
        self,
        child_issue_id: str,
        *,
        expected_org_id: str | None = None,
    ) -> str | None: ...


class ParentContinuationCoordinator:
    """Own the exactly-once parent wakeup boundary after child settlement."""

    def __init__(self, host: ParentContinuationHost) -> None:
        self._host = host

    async def queue_for_settled_child(
        self,
        child_issue_id: str,
        *,
        expected_org_id: str | None = None,
    ) -> str | None:
        return await self._host._queue_parent_continuation_for_settled_child_impl(
            child_issue_id,
            expected_org_id=expected_org_id,
        )
