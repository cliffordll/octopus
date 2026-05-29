from __future__ import annotations

from pathlib import Path
from typing import Any

from packages.runtimes.codex_local.skills import skill_snapshot


REQUIRED_SKILL_ENTRY_FIELDS = {
    "key",
    "selectionKey",
    "runtimeName",
    "description",
    "sourceClass",
    "origin",
    "originLabel",
    "locationLabel",
    "state",
    "desired",
    "managed",
}


def test_step17_agent_skill_entries_have_stable_metadata_fields(
    tmp_path: Path,
) -> None:
    org_root = tmp_path / "org-skills"
    org_skill = org_root / "review"
    org_skill.mkdir(parents=True)
    org_skill.joinpath("SKILL.md").write_text(
        "Review code carefully.", encoding="utf-8"
    )

    codex_home = tmp_path / "codex-home"
    external_skill = codex_home / "skills" / "external-tool"
    external_skill.mkdir(parents=True)
    external_skill.joinpath("SKILL.md").write_text(
        "External installed skill.", encoding="utf-8"
    )

    snapshot = skill_snapshot(
        runtime_type="codex_local",
        config={
            "skillsRootPath": str(org_root),
            "env": {"CODEX_HOME": str(codex_home)},
            "_octopus": {"agentSkillsRootPath": str(tmp_path / "agent-skills")},
        },
        desired_skills=["review", "missing-skill"],
        materialize=False,
    )

    entries: list[dict[str, Any]] = snapshot["entries"]
    assert {entry["key"] for entry in entries} >= {
        "review",
        "external-tool",
        "missing-skill",
    }
    for entry in entries:
        assert REQUIRED_SKILL_ENTRY_FIELDS <= set(entry)
        assert entry["description"] is None or isinstance(entry["description"], str)
        assert entry["sourceClass"]
        assert entry["origin"]
