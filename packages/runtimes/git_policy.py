from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence


READ_ONLY_GIT_COMMANDS = frozenset(
    {
        "blame",
        "cat-file",
        "diff",
        "diff-tree",
        "for-each-ref",
        "grep",
        "help",
        "log",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "merge-base",
        "name-rev",
        "rev-list",
        "rev-parse",
        "shortlog",
        "show",
        "show-ref",
        "status",
        "version",
        "whatchanged",
    }
)

_GLOBAL_OPTIONS_WITH_VALUES = frozenset(
    {"-C", "--git-dir", "--work-tree", "--namespace", "--super-prefix"}
)
_SAFE_GLOBAL_OPTIONS = frozenset(
    {
        "--bare",
        "--no-pager",
        "--no-replace-objects",
        "--literal-pathspecs",
        "--glob-pathspecs",
        "--noglob-pathspecs",
        "--icase-pathspecs",
    }
)


def read_only_git_command_allowed(args: Sequence[str]) -> bool:
    command = _git_subcommand(args)
    return command in READ_ONLY_GIT_COMMANDS


def _git_subcommand(args: Sequence[str]) -> str | None:
    index = 0
    while index < len(args):
        argument = args[index]
        if argument == "--version":
            return "version"
        if argument in _SAFE_GLOBAL_OPTIONS:
            index += 1
            continue
        if argument in _GLOBAL_OPTIONS_WITH_VALUES:
            index += 2
            continue
        if any(
            argument.startswith(f"{option}=")
            for option in _GLOBAL_OPTIONS_WITH_VALUES
            if option.startswith("--")
        ):
            index += 1
            continue
        if argument == "--":
            index += 1
            return args[index] if index < len(args) else None
        if argument.startswith("-"):
            # Unknown global options can alter config or command execution.
            return None
        return argument
    return None


def main(argv: Sequence[str] | None = None) -> int:
    values = list(argv if argv is not None else sys.argv[1:])
    if not values:
        print(
            "octopus git policy wrapper: missing real git executable", file=sys.stderr
        )
        return 2
    real_git, *git_args = values
    policy = os.environ.get("OCTOPUS_GIT_WRITE_POLICY", "read_write").strip().lower()
    if policy == "read_only" and not read_only_git_command_allowed(git_args):
        command = _git_subcommand(git_args) or "<unknown>"
        print(
            "octopus: blocked Git write-capable command "
            f"'{command}' because OCTOPUS_GIT_WRITE_POLICY=read_only",
            file=sys.stderr,
        )
        return 77
    return subprocess.call([real_git, *git_args])


if __name__ == "__main__":
    raise SystemExit(main())
