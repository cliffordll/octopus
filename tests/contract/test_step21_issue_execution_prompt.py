from __future__ import annotations

from packages.runtimes.instructions import runtime_prompt_from_config


def test_runtime_prompt_appends_issue_context_to_agent_instructions() -> None:
    prompt = runtime_prompt_from_config(
        {
            "promptTemplate": "# SOUL.md -- CEO Persona\n\nYou are the CEO.",
            "_octopus": {
                "context": {
                    "wakeSource": "assignment",
                    "wakeReason": "issue_execute",
                    "issue": {
                        "id": "issue-hello",
                        "title": "创建 hello world 输出脚本",
                        "description": "创建一个简单脚本，输出 hello world。",
                        "status": "in_progress",
                        "priority": "low",
                    },
                }
            },
        }
    )

    assert "# SOUL.md -- CEO Persona" in prompt
    assert "You have been assigned to work on an issue" in prompt
    assert "创建 hello world 输出脚本" in prompt
    assert "输出 hello world" in prompt
