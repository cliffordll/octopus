from __future__ import annotations

from typing import Literal

AgentStatus = Literal[
    "active", "paused", "idle", "running", "error", "pending_approval", "terminated"
]
AGENT_STATUSES: tuple[AgentStatus, ...] = (
    "active",
    "paused",
    "idle",
    "running",
    "error",
    "pending_approval",
    "terminated",
)

AgentRuntimeType = Literal[
    "process",
    "http",
    "claude_local",
    "codex_local",
    "gemini_local",
    "opencode_local",
    "pi_local",
    "cursor",
    "openclaw_gateway",
    "hermes_local",
]
AGENT_RUNTIME_TYPES: tuple[AgentRuntimeType, ...] = (
    "process",
    "http",
    "claude_local",
    "codex_local",
    "gemini_local",
    "opencode_local",
    "pi_local",
    "cursor",
    "openclaw_gateway",
    "hermes_local",
)

AgentRole = Literal[
    "ceo",
    "cto",
    "cmo",
    "cfo",
    "engineer",
    "designer",
    "pm",
    "qa",
    "devops",
    "researcher",
    "general",
]
AGENT_ROLES: tuple[AgentRole, ...] = (
    "ceo",
    "cto",
    "cmo",
    "cfo",
    "engineer",
    "designer",
    "pm",
    "qa",
    "devops",
    "researcher",
    "general",
)

PauseReason = Literal["manual", "budget", "system"]
PAUSE_REASONS: tuple[PauseReason, ...] = ("manual", "budget", "system")

DEFAULT_AGENT_ROLE: AgentRole = "general"
DEFAULT_AGENT_STATUS: AgentStatus = "idle"
DEFAULT_AGENT_RUNTIME_TYPE: AgentRuntimeType = "process"
AGENT_DICEBEAR_NOTIONISTS_ICON_PREFIX = "dicebear:notionists:"
