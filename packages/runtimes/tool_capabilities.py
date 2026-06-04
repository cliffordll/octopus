from __future__ import annotations


def append_runtime_tool_guidance(prompt: str, runtime_type: str) -> str:
    guidance = _runtime_tool_guidance(runtime_type)
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
