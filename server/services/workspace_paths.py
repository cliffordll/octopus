from __future__ import annotations

import os
from pathlib import Path
import re

DEFAULT_INSTANCE_ID = "default"
INSTANCE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _expand_home_prefix(value: str) -> Path:
    if value == "~":
        return Path.home()
    if value.startswith("~/") or value.startswith("~\\"):
        return Path.home() / value[2:]
    return Path(value)


def resolve_octopus_home_dir() -> Path:
    raw_home = os.environ.get("OCTOPUS_HOME", "").strip()
    home = _expand_home_prefix(raw_home) if raw_home else Path.home() / ".octopus"
    return home.resolve()


def resolve_octopus_instance_id() -> str:
    instance_id = (
        os.environ.get("OCTOPUS_INSTANCE_ID", "").strip() or DEFAULT_INSTANCE_ID
    )
    if not INSTANCE_ID_RE.fullmatch(instance_id):
        raise ValueError(f"Invalid OCTOPUS_INSTANCE_ID '{instance_id}'.")
    return instance_id


def resolve_octopus_instance_root() -> Path:
    return (
        resolve_octopus_home_dir() / "instances" / resolve_octopus_instance_id()
    ).resolve()


def organization_workspace_relative_path(org_id: str) -> str:
    return f"organizations/{org_id}/workspaces"


def organization_workspace_root(org_id: str) -> Path:
    return (
        resolve_octopus_instance_root() / organization_workspace_relative_path(org_id)
    ).resolve()


def agent_workspace_root(org_id: str, workspace_key: str) -> Path:
    return (organization_workspace_root(org_id) / "agents" / workspace_key).resolve()
