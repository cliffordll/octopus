from __future__ import annotations

import importlib
import textwrap
from pathlib import Path

import pytest

from server.services.organization_import import (
    _infer_role,
    parse_company_package,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def test_import_path_constant() -> None:
    paths = importlib.import_module("packages.shared.api_paths.organizations")
    assert paths.ORG_IMPORT_PATH == "/api/orgs/import"


def test_infer_role() -> None:
    assert _infer_role("CEO / Lead Reviewer", "CEO", "ceo") == "ceo"
    assert _infer_role(None, "Senior Code Reviewer", "code-reviewer") == "qa"
    assert _infer_role(None, "Lead Designer", "design-reviewer") == "designer"
    assert _infer_role(None, None, "random-helper") == "general"


def test_parse_paperclip_package(tmp_path: Path) -> None:
    """Paperclip-native: COMPANY.md + .paperclip.yaml + agents/<slug>/AGENTS.md."""
    root = tmp_path / "redoak"
    _write(
        root / "COMPANY.md",
        """
        ---
        name: RedOak Review
        slug: redoak-review
        description: A boutique review agency
        schema: agentcompanies/v1
        ---
        Body text.
    """,
    )
    _write(
        root / ".paperclip.yaml",
        "schema: paperclip/v1\nagents:\n  ci:\n    inputs: {}\n",
    )
    _write(
        root / "agents/ceo/AGENTS.md",
        """
        ---
        name: CEO
        title: CEO / Lead Reviewer
        reportsTo: null
        skills: []
        ---
        You are the CEO.
    """,
    )
    _write(
        root / "agents/code-reviewer/AGENTS.md",
        """
        ---
        name: Code Reviewer
        title: Senior Code Reviewer
        reportsTo: ceo
        skills:
          - pragmatic-code-review
        ---
        You review code.
    """,
    )
    _write(
        root / "skills/pragmatic-code-review/SKILL.md",
        "---\nname: Pragmatic Code Review\n---\nReview.\n",
    )

    manifest = parse_company_package(root)

    assert manifest["organization"]["name"] == "RedOak Review"
    assert manifest["organization"]["slug"] == "redoak-review"
    agents = {a["slug"]: a for a in manifest["agents"]}
    assert set(agents) == {"ceo", "code-reviewer"}
    assert agents["ceo"]["role"] == "ceo"
    assert agents["ceo"]["reportsToSlug"] is None
    assert agents["code-reviewer"]["reportsToSlug"] == "ceo"
    assert agents["code-reviewer"]["skills"] == ["pragmatic-code-review"]
    # Paperclip packages have no SOUL.md -> AGENTS.md body becomes the octopus entry
    assert "You review code." in agents["code-reviewer"]["bundle"]["SOUL.md"]
    assert manifest["skillsDir"] is not None


def test_parse_octopus_package(tmp_path: Path) -> None:
    """Octopus-exported: ORGANIZATION.md + .octopus.yaml(role/adapter) + SOUL.md."""
    root = tmp_path / "movie"
    _write(
        root / "ORGANIZATION.md",
        """
        ---
        name: 电影策划
        slug: movie
        ---
        Body.
    """,
    )
    _write(
        root / ".octopus.yaml",
        """
        schema: octopus/v1
        agents:
          agent-3:
            role: ceo
            adapter:
              type: opencode_local
              config:
                model: deepseek/deepseek-v4-pro
    """,
    )
    _write(
        root / "agents/agent-3/AGENTS.md",
        "---\nname: 创意总监\nreportsTo: null\n---\nAgents body.\n",
    )
    _write(
        root / "agents/agent-3/SOUL.md",
        "# Creative Director\nYou are the creative director.\n",
    )

    manifest = parse_company_package(root)

    agent = manifest["agents"][0]
    assert agent["slug"] == "agent-3"
    assert agent["role"] == "ceo"  # taken from .octopus.yaml extension
    assert agent["runtimeType"] == "opencode_local"
    assert agent["model"] == "deepseek/deepseek-v4-pro"
    # explicit SOUL.md is preferred over the AGENTS.md body
    assert "Creative Director" in agent["bundle"]["SOUL.md"]
    assert "MEMORY.md" not in agent["bundle"]  # not provided in this package


def test_missing_org_file_raises(tmp_path: Path) -> None:
    (tmp_path / "agents").mkdir()
    with pytest.raises(ValueError):
        parse_company_package(tmp_path)
