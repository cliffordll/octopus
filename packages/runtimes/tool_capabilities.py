from __future__ import annotations

from typing import Any


def append_runtime_tool_guidance(prompt: str, runtime_type: str) -> str:
    guidance = _runtime_tool_guidance(runtime_type)
    return _join_guidance(prompt, guidance)


def append_runtime_workspace_guidance(
    prompt: str, workspace: dict[str, Any] | None
) -> str:
    guidance = _workspace_guidance(workspace)
    return _join_guidance(prompt, guidance)


def _join_guidance(prompt: str, guidance: str) -> str:
    if not guidance:
        return prompt
    sections = [section.strip() for section in (prompt, guidance) if section.strip()]
    return "\n\n".join(sections)


def _runtime_tool_guidance(runtime_type: str) -> str:
    if runtime_type == "opencode_local":
        return "\n".join(
            [
                "## Runtime Tool Capability",
                "",
                "Do not guess tool input schemas. Use only the tool arguments supported by the local runtime.",
                "",
                "OpenCode local tool rules:",
                "",
                "- `bash` requires both `description` and `command`.",
                "- `description` must briefly explain why the command is being run.",
                "- `command` must contain the shell command to execute.",
                "- Do not call `bash` with only `command`; that is an invalid tool call.",
            ]
        )
    if runtime_type in {"codex_local", "claude_local"}:
        return "\n".join(
            [
                "## Runtime Tool Capability",
                "",
                "Do not guess tool input schemas. Use only the tool arguments supported by the local runtime.",
            ]
        )
    return ""


def _workspace_guidance(workspace: dict[str, Any] | None) -> str:
    if not isinstance(workspace, dict):
        return ""
    workspace_context = workspace.get("rudderWorkspace")
    if not isinstance(workspace_context, dict):
        return ""
    worktree = _string(
        workspace_context.get("worktreePath") or workspace_context.get("cwd")
    )
    artifacts_dir = _string(workspace_context.get("orgArtifactsDir"))
    if not worktree and not artifacts_dir:
        return ""
    lines = [
        "## Workspace Output Contract",
        "",
        "Write durable task deliverables only inside the Octopus-managed workspace paths.",
    ]
    if worktree:
        lines.append(f"- Workspace worktree: `{worktree}`")
    if artifacts_dir:
        lines.append(f"- Organization artifacts directory: `{artifacts_dir}`")
    lines.extend(
        [
            "- Read external source paths when the task asks for analysis. Do not write generated deliverables into external source paths.",
            "- Prefer the organization artifacts directory for durable files produced by this run.",
            "- Prefer relative paths under the workspace worktree for reports, plans, summaries, patches, and generated documents.",
            "- Files written outside these managed paths may not appear as issue documents or work products.",
        ]
    )
    return "\n".join(lines)


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
