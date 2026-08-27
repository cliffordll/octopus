from __future__ import annotations

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.schema import ActivityLog, Issue, Organization


class IssueHierarchyPolicy:
    """Own hierarchy locking and descendant settlement rules."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def lock_root(self, issue_id: str, org_id: str) -> Issue | None:
        """Serialize org hierarchy mutations with an Issue terminal transition."""

        # Organization is the stable lock key shared by every hierarchy in the
        # organization. Unlike walking the current ancestor chain, it remains
        # stable while a child is concurrently reparented and also covers
        # nested descendants. The lock is held only for the short DB mutation,
        # never for Adapter execution.
        locked_org_id = (
            await self._session.execute(
                update(Organization)
                .where(Organization.id == org_id)
                .values(updated_at=Organization.updated_at)
                .returning(Organization.id)
            )
        ).scalar_one_or_none()
        if locked_org_id is None:
            return None

        locked_id = (
            await self._session.execute(
                update(Issue)
                .where(Issue.id == issue_id, Issue.org_id == org_id)
                .values(updated_at=Issue.updated_at)
                .returning(Issue.id)
            )
        ).scalar_one_or_none()
        if locked_id is None:
            return None
        return (
            await self._session.execute(
                select(Issue)
                .where(Issue.id == locked_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()

    async def unsettled_descendants(self, parent: Issue) -> list[Issue]:
        rows = (
            (
                await self._session.execute(
                    select(Issue).where(Issue.org_id == parent.org_id)
                )
            )
            .scalars()
            .all()
        )
        children_by_parent: dict[str, list[Issue]] = {}
        for row in rows:
            if row.parent_id is not None:
                children_by_parent.setdefault(row.parent_id, []).append(row)

        accepted_child_ids = await self._accepted_incomplete_child_ids(parent)
        unsettled: list[Issue] = []
        stack = list(children_by_parent.get(parent.id, []))
        while stack:
            child = stack.pop()
            stack.extend(children_by_parent.get(child.id, []))
            if child.status == "done":
                continue
            if child.status in {"blocked", "cancelled"} and (
                "*" in accepted_child_ids or child.id in accepted_child_ids
            ):
                continue
            unsettled.append(child)
        return unsettled

    async def assert_open_ancestors(self, issue: Issue) -> None:
        """Reject active descendants below a terminal ancestor."""

        cursor = issue.parent_id
        visited: set[str] = set()
        while cursor is not None:
            if cursor in visited:
                raise ValueError("Issue parent hierarchy contains a cycle")
            visited.add(cursor)
            ancestor = (
                await self._session.execute(
                    select(Issue)
                    .where(Issue.id == cursor, Issue.org_id == issue.org_id)
                    .execution_options(populate_existing=True)
                )
            ).scalar_one_or_none()
            if ancestor is None:
                raise ValueError("Issue parent hierarchy is incomplete")
            if ancestor.status in {"done", "cancelled"}:
                raise ValueError(
                    "Cannot activate an issue below a closed ancestor. "
                    f"Reopen ancestor {ancestor.identifier or ancestor.id} first."
                )
            cursor = ancestor.parent_id

    async def assert_can_accept_descendant(self, parent: Issue) -> None:
        if parent.status in {"done", "cancelled"}:
            raise ValueError("Closed parent issue cannot accept child issues")
        await self.assert_open_ancestors(parent)

    async def _accepted_incomplete_child_ids(self, parent: Issue) -> set[str]:
        rows = (
            (
                await self._session.execute(
                    select(ActivityLog.details).where(
                        and_(
                            ActivityLog.org_id == parent.org_id,
                            ActivityLog.entity_type == "issue",
                            ActivityLog.entity_id == parent.id,
                            ActivityLog.action == "issue.incomplete_accepted",
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        accepted: set[str] = set()
        for details in rows:
            if not isinstance(details, dict):
                continue
            has_specific_children = False
            child_issue_id = details.get("childIssueId")
            if isinstance(child_issue_id, str) and child_issue_id:
                accepted.add(child_issue_id)
                has_specific_children = True
            child_issue_ids = details.get("childIssueIds")
            if isinstance(child_issue_ids, list):
                valid_ids = {
                    child_id
                    for child_id in child_issue_ids
                    if isinstance(child_id, str) and child_id
                }
                accepted.update(valid_ids)
                has_specific_children = has_specific_children or bool(valid_ids)
            if not has_specific_children:
                accepted.add("*")
        return accepted
