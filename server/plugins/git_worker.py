from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Sequence


GIT_PLUGIN_KEY = "git.local"

_READ_ONLY_TOOLS = {
    "git.status",
    "git.diff",
    "git.log",
    "git.branch.list",
}
_MUTATING_TOOLS = {
    "git.branch.create",
    "git.commit",
    "git.push",
    "git.worktree.create",
}
_ALL_TOOLS = _READ_ONLY_TOOLS | _MUTATING_TOOLS


class BuiltinGitWorker:
    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "activate":
            return {"activated": True, "builtin": True}
        if method == "deactivate":
            return {"deactivated": True, "builtin": True}
        if method == "validateConfig":
            return {"valid": True, "source": "builtin"}
        if method != "executeTool":
            return {"method": method, "params": params}
        tool_name = _string(params.get("toolName"))
        parameters = _object(params.get("parameters"))
        context = _object(params.get("context"))
        return await execute_git_tool(tool_name, parameters, context=context)


async def execute_git_tool(
    tool_name: str | None,
    parameters: dict[str, Any],
    *,
    context: dict[str, Any],
) -> dict[str, Any]:
    if tool_name not in _ALL_TOOLS:
        raise LookupError("Git tool not found")
    cwd = _workspace_cwd(context)
    await _assert_git_repository(cwd)

    if tool_name in _MUTATING_TOOLS and parameters.get("confirm") is not True:
        raise PermissionError("Mutating git tools require 'confirm: true'")

    if tool_name == "git.status":
        return await _git_result(cwd, ["status", "--short", "--branch"])
    if tool_name == "git.diff":
        args = ["diff"]
        if parameters.get("staged") is True:
            args.append("--staged")
        pathspec = _optional_string(parameters.get("pathspec"))
        if pathspec:
            args.extend(["--", pathspec])
        return await _git_result(cwd, args)
    if tool_name == "git.log":
        limit = _bounded_int(parameters.get("limit"), default=10, minimum=1, maximum=50)
        return await _git_result(
            cwd,
            ["log", f"-{limit}", "--oneline", "--decorate"],
        )
    if tool_name == "git.branch.list":
        return await _git_result(cwd, ["branch", "--list", "--verbose"])
    if tool_name == "git.branch.create":
        branch_name = _required_branch_name(parameters.get("branchName"))
        start_point = _optional_string(parameters.get("startPoint"))
        args = ["branch", branch_name]
        if start_point:
            args.append(start_point)
        return await _git_result(cwd, args)
    if tool_name == "git.commit":
        message = _required_string(parameters.get("message"), "message")
        if parameters.get("stageAll") is True:
            stage = await _run_git(cwd, ["add", "-A"])
            commit = await _run_git(cwd, ["commit", "-m", message])
            return _format_result(
                cwd, ["add", "-A && git", "commit", "-m", message], stage + commit
            )
        return await _git_result(cwd, ["commit", "-m", message])
    if tool_name == "git.push":
        remote = _optional_string(parameters.get("remote")) or "origin"
        branch = _optional_string(parameters.get("branch"))
        args = ["push", remote]
        if branch:
            args.append(branch)
        if parameters.get("setUpstream") is True:
            args.insert(1, "-u")
        return await _git_result(cwd, args)
    if tool_name == "git.worktree.create":
        branch_name = _required_branch_name(parameters.get("branchName"))
        start_point = _optional_string(parameters.get("startPoint")) or "HEAD"
        repo_root = await _repo_root(cwd)
        worktree_path = _worktree_path(repo_root, branch_name)
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        return await _git_result(
            repo_root,
            ["worktree", "add", "-b", branch_name, str(worktree_path), start_point],
            extra={"worktreePath": str(worktree_path)},
        )

    raise LookupError("Git tool not found")


def _workspace_cwd(context: dict[str, Any]) -> Path:
    candidates: list[Any] = [
        context.get("cwd"),
        context.get("workspaceCwd"),
        _object(context.get("env")).get("OCTOPUS_WORKSPACE_CWD"),
    ]
    workspace = _object(context.get("workspace"))
    workspace_context = _object(workspace.get("octopusWorkspace"))
    candidates.extend(
        [
            workspace_context.get("cwd"),
            workspace_context.get("worktreePath"),
            _object(context.get("octopusWorkspace")).get("cwd"),
        ]
    )
    for candidate in candidates:
        value = _optional_string(candidate)
        if value:
            path = Path(value).expanduser().resolve()
            if path.exists() and path.is_dir():
                return path
            raise ValueError(f"Workspace cwd does not exist: {value}")
    raise ValueError("Git tools require a runtime workspace cwd")


async def _assert_git_repository(cwd: Path) -> None:
    await _repo_root(cwd)


async def _repo_root(cwd: Path) -> Path:
    output = await _run_git(cwd, ["rev-parse", "--show-toplevel"])
    return Path(output.strip()).resolve()


def _worktree_path(repo_root: Path, branch_name: str) -> Path:
    safe_name = branch_name.replace("/", "-").replace("\\", "-")
    return repo_root / ".octopus" / "worktrees" / safe_name


async def _git_result(
    cwd: Path,
    args: Sequence[str],
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    output = await _run_git(cwd, args)
    return _format_result(cwd, list(args), output, extra=extra)


def _format_result(
    cwd: Path,
    args: list[str],
    output: str,
    *,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "ok": True,
        "cwd": str(cwd),
        "command": _format_command(["git", *args]),
        "stdout": output,
        "content": output,
        **(extra or {}),
    }


async def _run_git(cwd: Path, args: Sequence[str]) -> str:
    proc = await asyncio.create_subprocess_exec(
        "git",
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_bytes, stderr_bytes = await proc.communicate()
    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        detail = (stderr or stdout).strip() or f"git {' '.join(args)} failed"
        raise RuntimeError(detail)
    return stdout.strip()


def _format_command(parts: Sequence[str]) -> str:
    return " ".join(parts)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _optional_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _required_string(value: Any, field_name: str) -> str:
    result = _optional_string(value)
    if result is None:
        raise ValueError(f"'{field_name}' must be a non-empty string")
    return result


def _required_branch_name(value: Any) -> str:
    branch = _required_string(value, "branchName")
    if branch.startswith("-") or ".." in branch or branch.endswith(".lock"):
        raise ValueError("'branchName' is not a safe branch name")
    if any(part in branch for part in ("~", "^", ":", "?", "*", "[", "\\", " ")):
        raise ValueError("'branchName' is not a safe branch name")
    return branch


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return min(max(value, minimum), maximum)
    return default
