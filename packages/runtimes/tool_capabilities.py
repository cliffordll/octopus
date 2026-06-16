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
    workspace_artifacts_dir = (
        f"{worktree.rstrip('/\\\\')}/artifacts" if worktree else None
    )
    preferred_artifacts_label = (
        "workspace artifacts directory"
        if workspace_artifacts_dir
        else "organization artifacts directory"
    )
    if not worktree and not artifacts_dir:
        return ""
    lines = [
        "## Workspace Output Contract",
        "",
        "Write durable task deliverables only inside the Octopus-managed workspace paths.",
    ]
    if worktree:
        lines.append(f"- Workspace worktree: `{worktree}`")
    if workspace_artifacts_dir:
        lines.append(f"- Workspace artifacts directory: `{workspace_artifacts_dir}`")
    elif artifacts_dir:
        lines.append(f"- Organization artifacts directory: `{artifacts_dir}`")
    lines.extend(
        [
            "- Treat the workspace worktree as the project source/download directory for this run.",
            "- Put project-specific checkouts, downloaded source bundles, dependency snapshots, and code edits under the workspace worktree.",
            f"- Prefer the {preferred_artifacts_label} for durable deliverables produced by this run, such as reports, screenshots, CSV files, mockups, logs, and handoff documents.",
            "- Use relative paths under the workspace worktree for source changes, patches, temporary project files, and project-local generated files.",
            "- Files written outside these managed paths may not appear as issue documents or work products.",
        ]
    )
    return "\n".join(lines)


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
