from __future__ import annotations

from typing import NotRequired, TypedDict

from ..constants.goal import GoalLevel, GoalStatus


class Goal(TypedDict):
    id: str
    orgId: str
    title: str
    description: str | None
    level: GoalLevel
    status: GoalStatus
    parentId: str | None
    ownerAgentId: str | None
    createdAt: str
    updatedAt: str


class GoalDependencyPreview(TypedDict):
    id: str
    title: str
    subtitle: str | None


class GoalDependencyCounts(TypedDict):
    childGoals: int
    linkedProjects: int
    linkedIssues: int
    automations: int
    costEvents: int
    financeEvents: int


class GoalDependencyPreviews(TypedDict):
    childGoals: list[GoalDependencyPreview]
    linkedProjects: list[GoalDependencyPreview]
    linkedIssues: list[GoalDependencyPreview]
    automations: list[GoalDependencyPreview]


class GoalDependencies(TypedDict):
    goalId: str
    orgId: str
    canDelete: bool
    blockers: list[str]
    isLastRootOrganizationGoal: bool
    counts: GoalDependencyCounts
    previews: GoalDependencyPreviews


class GoalMutationFields(TypedDict, total=False):
    description: NotRequired[str | None]
    level: GoalLevel
    status: GoalStatus
    parentId: NotRequired[str | None]
    ownerAgentId: NotRequired[str | None]


class CreateGoalPayload(GoalMutationFields):
    title: str


class UpdateGoalPayload(GoalMutationFields, total=False):
    title: str
