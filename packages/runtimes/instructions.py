from __future__ import annotations

from pathlib import Path
from typing import Any


def runtime_prompt_from_config(config: dict[str, Any]) -> str:
    return _join_prompt_sections(
        [
            _base_prompt_from_config(config),
            _tacit_memory_prompt(config),
            _agent_memory_guidance(config),
            _heartbeat_prompt(config),
        ]
    )


def _base_prompt_from_config(config: dict[str, Any]) -> str:
    prompt = _string(config.get("promptTemplate"))
    if prompt:
        return prompt
    instructions_path = _resolve_instructions_path(config)
    if instructions_path is None:
        return ""
    try:
        return instructions_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _tacit_memory_prompt(config: dict[str, Any]) -> str:
    memory_path = _resolve_tacit_memory_path(config)
    if memory_path is None:
        return ""
    try:
        memory = memory_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not memory.strip():
        return ""
    return _join_prompt_sections(["## Tacit Agent Memory", memory])


def _resolve_tacit_memory_path(config: dict[str, Any]) -> Path | None:
    instructions_path = _resolve_instructions_path(config)
    if instructions_path is not None:
        memory_path = instructions_path.parent / "MEMORY.md"
        if not _same_path(instructions_path, memory_path):
            return memory_path
    octopus = config.get("_octopus")
    if not isinstance(octopus, dict):
        return None
    instructions_dir = _string(octopus.get("agentInstructionsDir"))
    if not instructions_dir:
        return None
    return Path(instructions_dir).expanduser() / "MEMORY.md"


def _agent_memory_guidance(config: dict[str, Any]) -> str:
    octopus = config.get("_octopus")
    if not isinstance(octopus, dict):
        return ""
    agent_home = _string(octopus.get("agentHome"))
    if not agent_home:
        return ""
    return "\n".join(
        [
            "## Agent Memory Contract",
            "",
            f"Your durable agent home is `{agent_home}`.",
            "- Keep stable preferences, operating patterns, and lessons learned in `$AGENT_HOME/instructions/MEMORY.md`.",
            "- Keep daily notes in `$AGENT_HOME/memory/YYYY-MM-DD.md`.",
            "- Keep structured long-term knowledge in `$AGENT_HOME/life/`.",
            "- Use the `para-memory-files` skill for memory file operations when it is available.",
            "- Do not store secrets, credentials, or transient task logs in long-term memory.",
            "- Do not assume `$HOME` is long-term memory; local runtimes may use it for CLI credentials and caches.",
        ]
    )


def _heartbeat_prompt(config: dict[str, Any]) -> str:
    octopus = config.get("_octopus")
    if not isinstance(octopus, dict):
        return ""
    context = octopus.get("context")
    if not isinstance(context, dict):
        return ""
    issue = context.get("issue")
    if not isinstance(issue, dict):
        return ""
    wake_source = _string(context.get("wakeSource")) or ""
    wake_reason = _string(context.get("wakeReason")) or ""
    if wake_source != "assignment" and wake_reason not in {
        "issue_assigned",
        "issue_execute",
        "issue_checked_out",
    }:
        return ""
    return _assignment_issue_prompt(
        agent_id=_string(octopus.get("agentId")) or "",
        agent_name=_string(octopus.get("agentName")) or "",
        issue=issue,
    )


def _assignment_issue_prompt(
    *, agent_id: str, agent_name: str, issue: dict[str, Any]
) -> str:
    agent_label = agent_id
    if agent_name:
        agent_label = f"{agent_id} ({agent_name})" if agent_id else agent_name
    return "\n".join(
        [
            f"You are agent {agent_label}. You have been assigned to work on an issue.",
            "",
            "## Task Context",
            "",
            f"**Issue:** {_string(issue.get('title')) or ''}",
            f"**ID:** {_string(issue.get('id')) or ''}",
            f"**Status:** {_string(issue.get('status')) or ''}",
            f"**Priority:** {_string(issue.get('priority')) or ''}",
            "",
            "**Description:**",
            _string(issue.get("description")) or "",
            "",
            (
                "Your task is to review this issue and begin working on it. "
                "Use the available tools to explore the codebase, understand "
                "the requirements, and implement a solution."
            ),
        ]
    )


def _resolve_instructions_path(config: dict[str, Any]) -> Path | None:
    raw_path = _string(config.get("instructionsFilePath"))
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    cwd = _string(config.get("cwd"))
    if not cwd:
        return None
    cwd_path = Path(cwd).expanduser()
    if not cwd_path.is_absolute():
        return None
    return cwd_path / path


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _join_prompt_sections(sections: list[str]) -> str:
    return "\n\n".join(section.strip() for section in sections if section.strip())


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()
