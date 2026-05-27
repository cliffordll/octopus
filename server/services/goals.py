from __future__ import annotations

from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from packages.database.queries.activity_log import insert_activity_log
from packages.database.queries.agents import get_agent_by_id
from packages.database.queries.goals import (
    create_goal,
    delete_goal,
    get_goal_by_id,
    list_org_goals,
    update_goal,
)
from packages.database.schema import Goal as GoalRow
from packages.database.schema import Issue, Project, ProjectGoal
from packages.shared.constants.goal import (
    DEFAULT_GOAL_LEVEL,
    DEFAULT_GOAL_STATUS,
    GoalLevel,
    GoalStatus,
)
from packages.shared.types.goal import (
    CreateGoalPayload,
    Goal,
    GoalDependencies,
    GoalDependencyPreview,
    UpdateGoalPayload,
)

_PREVIEW_LIMIT = 5


class GoalConflictError(ValueError):
    def __init__(self, message: str, dependencies: GoalDependencies) -> None:
        super().__init__(message)
        self.dependencies = dependencies


class GoalService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_org(self, org_id: str) -> list[Goal]:
        rows = await list_org_goals(self._session, org_id)
        return [self._to_goal(row) for row in rows]

    async def get(self, goal_id: str) -> Goal | None:
        row = await get_goal_by_id(self._session, goal_id)
        return self._to_goal(row) if row is not None else None

    async def create(
        self,
        org_id: str,
        payload: CreateGoalPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> Goal:
        await self._validate_references(org_id, None, payload)
        row = await create_goal(
            self._session,
            {
                "org_id": org_id,
                "title": str(payload["title"]).strip(),
                "description": payload.get("description"),
                "level": payload.get("level", DEFAULT_GOAL_LEVEL),
                "status": payload.get("status", DEFAULT_GOAL_STATUS),
                "parent_id": payload.get("parentId"),
                "owner_agent_id": payload.get("ownerAgentId"),
            },
        )
        await insert_activity_log(
            self._session,
            org_id=org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="goal.created",
            entity_type="goal",
            entity_id=row.id,
            details={"title": row.title},
        )
        return self._to_goal(row)

    async def update(
        self,
        goal_id: str,
        payload: UpdateGoalPayload,
        *,
        actor_type: str,
        actor_id: str,
    ) -> Goal | None:
        existing = await get_goal_by_id(self._session, goal_id)
        if existing is None:
            return None
        await self._validate_references(existing.org_id, goal_id, payload)
        column_map = {
            "title": "title",
            "description": "description",
            "level": "level",
            "status": "status",
            "parentId": "parent_id",
            "ownerAgentId": "owner_agent_id",
        }
        values: dict[str, object] = {
            column_map[key]: value
            for key, value in payload.items()
            if key in column_map and key != "title"
        }
        if "title" in payload:
            values["title"] = payload["title"].strip()
        row = await update_goal(self._session, goal_id, values)
        if row is None:
            return None
        if payload:
            await insert_activity_log(
                self._session,
                org_id=row.org_id,
                actor_type=actor_type,
                actor_id=actor_id,
                action="goal.updated",
                entity_type="goal",
                entity_id=row.id,
                details=dict(payload),
            )
        return self._to_goal(row)

    async def remove(
        self, goal_id: str, *, actor_type: str, actor_id: str
    ) -> Goal | None:
        existing = await get_goal_by_id(self._session, goal_id)
        if existing is None:
            return None
        dependencies = await self.dependencies(existing)
        if not dependencies["canDelete"]:
            raise GoalConflictError(
                "Goal cannot be deleted while it has dependencies", dependencies
            )
        row = await delete_goal(self._session, goal_id)
        if row is None:
            return None
        await insert_activity_log(
            self._session,
            org_id=row.org_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action="goal.deleted",
            entity_type="goal",
            entity_id=row.id,
        )
        return self._to_goal(row)

    async def get_default_organization_goal(self, org_id: str) -> Goal | None:
        rows = list(await list_org_goals(self._session, org_id))
        candidates = [
            row
            for row in rows
            if row.level == "organization"
            and row.status == "active"
            and row.parent_id is None
        ]
        if not candidates:
            candidates = [
                row
                for row in rows
                if row.level == "organization" and row.parent_id is None
            ]
        if not candidates:
            candidates = [row for row in rows if row.level == "organization"]
        return self._to_goal(candidates[0]) if candidates else None

    async def dependencies(self, goal: GoalRow | Goal) -> GoalDependencies:
        goal_id = goal.id if isinstance(goal, GoalRow) else goal["id"]
        org_id = goal.org_id if isinstance(goal, GoalRow) else goal["orgId"]
        level = goal.level if isinstance(goal, GoalRow) else goal["level"]
        parent_id = goal.parent_id if isinstance(goal, GoalRow) else goal["parentId"]
        child_rows = (
            (
                await self._session.execute(
                    select(GoalRow)
                    .where(GoalRow.org_id == org_id, GoalRow.parent_id == goal_id)
                    .order_by(GoalRow.created_at, GoalRow.id)
                )
            )
            .scalars()
            .all()
        )
        linked_by_id: dict[str, Project] = {}
        joined_projects = (
            (
                await self._session.execute(
                    select(Project)
                    .join(ProjectGoal, ProjectGoal.project_id == Project.id)
                    .where(
                        ProjectGoal.org_id == org_id,
                        ProjectGoal.goal_id == goal_id,
                    )
                    .order_by(Project.created_at, Project.id)
                )
            )
            .scalars()
            .all()
        )
        legacy_projects = (
            (
                await self._session.execute(
                    select(Project)
                    .where(Project.org_id == org_id, Project.goal_id == goal_id)
                    .order_by(Project.created_at, Project.id)
                )
            )
            .scalars()
            .all()
        )
        for project in [*joined_projects, *legacy_projects]:
            linked_by_id[project.id] = project
        linked_projects = list(linked_by_id.values())
        linked_issues = (
            (
                await self._session.execute(
                    select(Issue)
                    .where(Issue.org_id == org_id, Issue.goal_id == goal_id)
                    .order_by(Issue.created_at, Issue.id)
                )
            )
            .scalars()
            .all()
        )
        roots = (
            (
                await self._session.execute(
                    select(GoalRow).where(
                        GoalRow.org_id == org_id,
                        GoalRow.level == "organization",
                        GoalRow.parent_id.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        is_last_root = level == "organization" and parent_id is None and len(roots) <= 1
        blockers: list[str] = []
        if is_last_root:
            blockers.append("last_root_organization_goal")
        if child_rows:
            blockers.append("child_goals")
        if linked_projects:
            blockers.append("linked_projects")
        if linked_issues:
            blockers.append("linked_issues")
        return {
            "goalId": goal_id,
            "orgId": org_id,
            "canDelete": not blockers,
            "blockers": blockers,
            "isLastRootOrganizationGoal": is_last_root,
            "counts": {
                "childGoals": len(child_rows),
                "linkedProjects": len(linked_projects),
                "linkedIssues": len(linked_issues),
                "automations": 0,
                "costEvents": 0,
                "financeEvents": 0,
            },
            "previews": {
                "childGoals": [
                    self._preview(row.id, row.title, row.status)
                    for row in child_rows[:_PREVIEW_LIMIT]
                ],
                "linkedProjects": [
                    self._preview(row.id, row.name, row.status)
                    for row in linked_projects[:_PREVIEW_LIMIT]
                ],
                "linkedIssues": [
                    self._preview(row.id, row.title, row.identifier or row.status)
                    for row in linked_issues[:_PREVIEW_LIMIT]
                ],
                "automations": [],
            },
        }

    async def _validate_references(
        self,
        org_id: str,
        goal_id: str | None,
        payload: CreateGoalPayload | UpdateGoalPayload,
    ) -> None:
        if "ownerAgentId" in payload and payload["ownerAgentId"] is not None:
            agent = await get_agent_by_id(self._session, payload["ownerAgentId"])
            if agent is None or agent.org_id != org_id:
                raise ValueError("Goal owner must belong to the same organization")
        if "parentId" not in payload or payload["parentId"] is None:
            return
        parent_id = payload["parentId"]
        if goal_id is not None and parent_id == goal_id:
            raise ValueError("Goal cannot be its own parent")
        rows = list(await list_org_goals(self._session, org_id))
        by_id = {row.id: row for row in rows}
        if parent_id not in by_id:
            raise ValueError("Goal parent must belong to the same organization")
        if goal_id is None:
            return
        cursor: str | None = parent_id
        seen: set[str] = set()
        while cursor is not None:
            if cursor == goal_id:
                raise ValueError("Goal parent cannot create a cycle")
            if cursor in seen:
                return
            seen.add(cursor)
            parent = by_id.get(cursor)
            cursor = parent.parent_id if parent is not None else None

    @staticmethod
    def _preview(
        entity_id: str, title: str, subtitle: str | None
    ) -> GoalDependencyPreview:
        return {"id": entity_id, "title": title, "subtitle": subtitle}

    @staticmethod
    def _to_goal(row: GoalRow) -> Goal:
        return {
            "id": row.id,
            "orgId": row.org_id,
            "title": row.title,
            "description": row.description,
            "level": cast(GoalLevel, row.level),
            "status": cast(GoalStatus, row.status),
            "parentId": row.parent_id,
            "ownerAgentId": row.owner_agent_id,
            "createdAt": row.created_at.isoformat(),
            "updatedAt": row.updated_at.isoformat(),
        }
