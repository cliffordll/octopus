from __future__ import annotations

from packages.runtimes import git_policy
from packages.runtimes.git_policy import read_only_git_command_allowed


def test_read_only_git_policy_allows_inspection_commands() -> None:
    assert read_only_git_command_allowed(["status", "--short"])
    assert read_only_git_command_allowed(["-C", "D:/repo", "diff", "--stat"])
    assert read_only_git_command_allowed(["--no-pager", "log", "-1"])
    assert read_only_git_command_allowed(["--version"])


def test_read_only_git_policy_blocks_ref_and_worktree_mutations() -> None:
    blocked = (
        ["checkout", "main"],
        ["switch", "main"],
        ["stash"],
        ["merge", "feature"],
        ["pull", "--rebase"],
        ["push", "origin", "main"],
        ["reset", "--hard"],
        ["branch", "-D", "feature"],
        ["worktree", "add", "../other"],
        ["-c", "alias.x=!echo bypass", "x"],
    )
    for command in blocked:
        assert not read_only_git_command_allowed(command), command


def test_git_policy_main_blocks_mutation_before_real_git(monkeypatch, capsys) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("OCTOPUS_GIT_WRITE_POLICY", "read_only")
    monkeypatch.setattr(
        git_policy.subprocess,
        "call",
        lambda args: calls.append(args) or 0,
    )

    assert git_policy.main(["C:/Git/git.exe", "checkout", "main"]) == 77
    assert calls == []
    assert "blocked Git write-capable command 'checkout'" in capsys.readouterr().err

    assert git_policy.main(["C:/Git/git.exe", "status", "--short"]) == 0
    assert calls == [["C:/Git/git.exe", "status", "--short"]]
