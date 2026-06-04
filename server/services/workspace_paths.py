from __future__ import annotations

from pathlib import Path


def organization_workspace_relative_path(org_id: str) -> str:
    return f".octopus/workspaces/org_{org_id}"


def organization_workspace_root(org_id: str) -> Path:
    return (Path.cwd() / organization_workspace_relative_path(org_id)).resolve()


def agent_workspace_root(org_id: str, workspace_key: str) -> Path:
    return (organization_workspace_root(org_id) / "agents" / workspace_key).resolve()
