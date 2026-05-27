from __future__ import annotations

from typing import Literal

GoalLevel = Literal["organization", "team", "agent", "task"]
GOAL_LEVELS: tuple[GoalLevel, ...] = ("organization", "team", "agent", "task")
DEFAULT_GOAL_LEVEL: GoalLevel = "task"

GoalStatus = Literal["planned", "active", "achieved", "cancelled"]
GOAL_STATUSES: tuple[GoalStatus, ...] = (
    "planned",
    "active",
    "achieved",
    "cancelled",
)
DEFAULT_GOAL_STATUS: GoalStatus = "planned"
