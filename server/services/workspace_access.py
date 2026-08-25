from __future__ import annotations

from abc import ABC, abstractmethod

from .workspaces import WorkspacePreparationPlan


class WorkspaceAccessStrategy(ABC):
    """Stable extension point for workspace-mode concurrency boundaries."""

    @property
    @abstractmethod
    def lock_namespace(self) -> str:
        """Namespace used to coordinate only conflicting preparation work."""

    def lock_key(self, plan: WorkspacePreparationPlan) -> str:
        return f"{self.lock_namespace}:{plan.coordination_key}"


class SharedWorkspaceAccessStrategy(WorkspaceAccessStrategy):
    lock_namespace = "shared"


class IsolatedWorkspaceAccessStrategy(WorkspaceAccessStrategy):
    # Git mutates common source-repository metadata while adding worktrees.
    lock_namespace = "isolated-source-repo"


class OperatorBranchWorkspaceAccessStrategy(WorkspaceAccessStrategy):
    lock_namespace = "operator-branch"


class AgentWorkspaceAccessStrategy(WorkspaceAccessStrategy):
    lock_namespace = "agent-workspace"


def workspace_access_strategy(
    plan: WorkspacePreparationPlan,
) -> WorkspaceAccessStrategy:
    if plan.mode == "shared_workspace":
        return SharedWorkspaceAccessStrategy()
    if plan.mode == "isolated_workspace":
        return IsolatedWorkspaceAccessStrategy()
    if plan.mode == "operator_branch":
        return OperatorBranchWorkspaceAccessStrategy()
    return AgentWorkspaceAccessStrategy()
