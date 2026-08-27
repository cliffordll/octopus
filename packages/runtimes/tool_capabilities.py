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
    workspace_context = workspace.get("octopusWorkspace")
    if not isinstance(workspace_context, dict):
        return ""
    worktree = _string(
        workspace_context.get("worktreePath") or workspace_context.get("cwd")
    )
    artifacts_dir = _string(workspace_context.get("orgArtifactsDir"))
    issue_artifacts_dir = _string(workspace_context.get("issueArtifactsDir"))
    git_write_policy = _string(workspace_context.get("gitWritePolicy"))
    normalized_worktree = worktree.rstrip("/\\") if worktree else None
    workspace_artifacts_dir = (
        f"{normalized_worktree}/artifacts" if normalized_worktree else None
    )
    workspace_mode = _string(workspace_context.get("mode"))
    workspace_kind = _string(workspace_context.get("workspaceKind"))
    is_shared_project_workspace = (
        workspace_mode == "shared_workspace" and workspace_kind == "project_execution"
    )
    preferred_artifacts_label = (
        "workspace worktree with a clear shared path such as `reports/`"
        if is_shared_project_workspace
        else "organization artifacts directory"
        if artifacts_dir
        else "workspace worktree or the task-specified path"
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
    if git_write_policy == "read_only":
        lines.extend(
            [
                "- Git write policy: `read_only`.",
                "- Do not run Git commands that change branches, refs, the index, the working tree, or remotes.",
                "- Do not bypass this policy by invoking Git through an absolute executable path or another process.",
            ]
        )
    if artifacts_dir:
        lines.append(f"- Organization artifacts directory: `{artifacts_dir}`")
    if workspace_artifacts_dir:
        lines.append(f"- Workspace-local artifacts path: `{workspace_artifacts_dir}`")
    if issue_artifacts_dir:
        lines.append(f"- Issue compatibility artifacts path: `{issue_artifacts_dir}`")
    lines.extend(
        [
            "- Treat the workspace worktree as the project source/download directory for this run.",
            "- Put project-specific checkouts, downloaded source bundles, dependency snapshots, and code edits under the workspace worktree.",
            f"- Prefer the {preferred_artifacts_label} for durable deliverables produced by this run, such as reports, screenshots, CSV files, mockups, logs, and handoff documents, unless the user requested a specific project path.",
            "- In shared project workspace mode, do not use `$OCTOPUS_ISSUE_ARTIFACTS_DIR` as the default deliverable target. Use `$OCTOPUS_WORKSPACE_CWD` plus a clear shared path instead, for example `reports/<name>.md`.",
            "- `OCTOPUS_ISSUE_ARTIFACTS_DIR` is only a compatibility convenience path for issue-scoped outputs, not a workspace isolation boundary or the default target for shared project work.",
            "- In shared workspace mode, files may intentionally be shared with other tasks; use clear paths and mention created or modified deliverables in closeout so they can be traced to this issue/run.",
            "- Use relative paths under the workspace worktree for source changes, patches, temporary project files, and project-local generated files.",
            "- Files written outside these managed paths may not appear as issue documents or work products.",
        ]
    )
    return "\n".join(lines)


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
