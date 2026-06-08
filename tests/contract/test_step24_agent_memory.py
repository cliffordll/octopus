from __future__ import annotations

from pathlib import Path

from packages.runtimes.context_env import apply_runtime_context_env
from packages.runtimes.instructions import runtime_prompt_from_config
from packages.runtimes.types import RuntimeExecutionContext


def test_runtime_prompt_loads_sibling_tacit_memory(tmp_path: Path) -> None:
    instructions_root = tmp_path / "agent-home" / "instructions"
    instructions_root.mkdir(parents=True)
    soul = instructions_root / "SOUL.md"
    soul.write_text("Base operating instructions.", encoding="utf-8")
    memory = instructions_root / "MEMORY.md"
    memory.write_text("Prefer concise status updates.", encoding="utf-8")

    prompt = runtime_prompt_from_config(
        {
            "instructionsFilePath": str(soul),
            "_octopus": {"agentHome": str(tmp_path / "agent-home")},
        }
    )

    assert "Base operating instructions." in prompt
    assert "## Tacit Agent Memory" in prompt
    assert "Prefer concise status updates." in prompt
    assert "## Agent Memory Contract" in prompt
    assert "$AGENT_HOME/memory/YYYY-MM-DD.md" in prompt
    assert "$AGENT_HOME/life/" in prompt
    assert "Do not assume `$HOME` is long-term memory" in prompt


def test_runtime_prompt_does_not_auto_load_daily_or_life_memory(
    tmp_path: Path,
) -> None:
    agent_home = tmp_path / "agent-home"
    instructions_root = agent_home / "instructions"
    daily_root = agent_home / "memory"
    life_root = agent_home / "life"
    instructions_root.mkdir(parents=True)
    daily_root.mkdir()
    life_root.mkdir()
    soul = instructions_root / "SOUL.md"
    soul.write_text("Base instructions.", encoding="utf-8")
    instructions_root.joinpath("MEMORY.md").write_text(
        "Stable memory.", encoding="utf-8"
    )
    daily_root.joinpath("2026-06-08.md").write_text(
        "Daily note should stay lazy.", encoding="utf-8"
    )
    life_root.joinpath("profile.md").write_text(
        "Life note should stay lazy.", encoding="utf-8"
    )

    prompt = runtime_prompt_from_config(
        {
            "instructionsFilePath": str(soul),
            "_octopus": {"agentHome": str(agent_home)},
        }
    )

    assert "Stable memory." in prompt
    assert "Daily note should stay lazy." not in prompt
    assert "Life note should stay lazy." not in prompt


def test_runtime_prompt_can_load_tacit_memory_from_octopus_instructions_dir(
    tmp_path: Path,
) -> None:
    instructions_root = tmp_path / "agent-home" / "instructions"
    instructions_root.mkdir(parents=True)
    instructions_root.joinpath("MEMORY.md").write_text(
        "Fallback memory path works.", encoding="utf-8"
    )

    prompt = runtime_prompt_from_config(
        {
            "_octopus": {
                "agentHome": str(tmp_path / "agent-home"),
                "agentInstructionsDir": str(instructions_root),
            }
        }
    )

    assert "Fallback memory path works." in prompt


def test_runtime_context_env_falls_back_to_agent_memory_paths_from_octopus() -> None:
    env: dict[str, str] = {}
    apply_runtime_context_env(
        env,
        RuntimeExecutionContext(
            run_id="run-24",
            agent_id="agent-24",
            org_id="org-24",
            agent_name="Memory Agent",
            config={
                "_octopus": {
                    "agentHome": "D:/agents/agent-24",
                    "agentInstructionsDir": "D:/agents/agent-24/instructions",
                    "agentMemoryDir": "D:/agents/agent-24/memory",
                    "agentLifeDir": "D:/agents/agent-24/life",
                    "agentSkillsRootPath": "D:/agents/agent-24/skills",
                }
            },
            workspace={"rudderWorkspace": {"cwd": "D:/workspaces/task-24"}},
            on_log=lambda stream, chunk: None,
        ),
    )

    assert env["AGENT_HOME"] == "D:/agents/agent-24"
    assert env["RUDDER_AGENT_ROOT"] == "D:/agents/agent-24"
    assert env["RUDDER_AGENT_INSTRUCTIONS_DIR"] == "D:/agents/agent-24/instructions"
    assert env["RUDDER_AGENT_MEMORY_DIR"] == "D:/agents/agent-24/memory"
    assert env["RUDDER_AGENT_LIFE_DIR"] == "D:/agents/agent-24/life"
    assert env["RUDDER_AGENT_SKILLS_DIR"] == "D:/agents/agent-24/skills"
