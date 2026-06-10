from __future__ import annotations

from pathlib import Path
from typing import Any

from packages.runtimes.codex_local.skills import skill_snapshot


REQUIRED_SKILL_ENTRY_FIELDS = {
    "key",
    "selectionKey",
    "runtimeName",
    "sourceRole",
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


def test_org_selection_key_materializes_to_runtime_slug(tmp_path: Path) -> None:
    org_id = "org-step17"
    org_root = tmp_path / "org-skills"
    skill_dir = org_root / "deep-research"
    skill_dir.mkdir(parents=True)
    skill_dir.joinpath("SKILL.md").write_text("Research deeply.", encoding="utf-8")
    codex_home = tmp_path / "codex-home"

    snapshot = skill_snapshot(
        runtime_type="codex_local",
        config={
            "skillsRootPath": str(org_root),
            "env": {"CODEX_HOME": str(codex_home)},
        },
        desired_skills=[f"org:organization/{org_id}/deep-research"],
        materialize=True,
    )

    assert not snapshot["warnings"]
    assert (codex_home / "skills" / "deep-research" / "SKILL.md").is_file()
    entries = {entry["key"]: entry for entry in snapshot["entries"]}
    assert entries["deep-research"]["desired"] is True
    assert entries["deep-research"]["state"] == "installed"


def test_persistent_skill_materialization_warns_on_external_name_conflict(
    tmp_path: Path,
) -> None:
    org_root = tmp_path / "org-skills"
    managed_skill = org_root / "review"
    managed_skill.mkdir(parents=True)
    managed_skill.joinpath("SKILL.md").write_text(
        "Managed review skill.", encoding="utf-8"
    )
    codex_home = tmp_path / "codex-home"
    external_skill = codex_home / "skills" / "review"
    external_skill.mkdir(parents=True)
    external_skill.joinpath("SKILL.md").write_text(
        "External review skill.", encoding="utf-8"
    )

    snapshot = skill_snapshot(
        runtime_type="codex_local",
        config={
            "skillsRootPath": str(org_root),
            "env": {"CODEX_HOME": str(codex_home)},
        },
        desired_skills=["review"],
        materialize=True,
    )

    assert snapshot["warnings"] == [
        'Skill "review" was not materialized because the runtime target is '
        "occupied by a different source."
    ]
    entries = {entry["key"]: entry for entry in snapshot["entries"]}
    assert entries["review"]["desired"] is True
    assert entries["review"]["state"] == "external"
    assert entries["review"]["managed"] is False
    assert entries["review"]["detail"] == (
        "Skill name is occupied by a non-managed entry inside the managed Codex "
        "skills home."
    )
    assert external_skill.joinpath("SKILL.md").read_text(encoding="utf-8") == (
        "External review skill."
    )
