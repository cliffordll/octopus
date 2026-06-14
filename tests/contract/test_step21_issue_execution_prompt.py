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
    assert "## Close-out Gate" in prompt
    assert "Every issue run must leave a durable close-out signal" in prompt
    assert 'control-plane issue done "issue-hello"' in prompt
    assert 'control-plane issue block "issue-hello"' in prompt
    assert 'control-plane issue comment "issue-hello"' in prompt
    assert (
        "If the issue has a reviewer, `issue done` submits the work for review"
        in prompt
    )


def test_runtime_prompt_hard_gates_passive_followup_closeout() -> None:
    prompt = runtime_prompt_from_config(
        {
            "promptTemplate": "# Base\n\nYou are an agent.",
            "_octopus": {
                "agentId": "agent-1",
                "agentName": "engineer-1",
                "context": {
                    "wakeSource": "passive_issue_followup",
                    "wakeReason": "issue_passive_followup",
                    "issue": {
                        "id": "issue-closeout",
                        "identifier": "OCT-17",
                        "title": "写一首关于夏天的五言律诗",
                        "description": "创作五言律诗。",
                        "status": "in_progress",
                        "priority": "medium",
                    },
                },
            },
        }
    )

    assert "## Close-out Gate" in prompt
    assert "issue_passive_followup" in prompt
    assert "Do not start new implementation work" in prompt
    assert 'control-plane issue done "OCT-17"' in prompt
    assert 'control-plane issue block "OCT-17"' in prompt
    assert 'control-plane issue comment "OCT-17"' in prompt
    assert (
        "If the issue has a reviewer, `issue done` submits the work for review"
        in prompt
    )
    assert "Do not exit" in prompt


def test_runtime_prompt_hard_gates_missing_review_closeout() -> None:
    prompt = runtime_prompt_from_config(
        {
            "promptTemplate": "# Base\n\nYou are a reviewer.",
            "_octopus": {
                "agentId": "agent-2",
                "agentName": "reviewer-1",
                "context": {
                    "wakeSource": "review",
                    "wakeReason": "issue_review_closeout_missing",
                    "issue": {
                        "id": "issue-review",
                        "identifier": "OCT-18",
                        "title": "修复 closeout",
                        "description": "评审修复结果。",
                        "status": "in_review",
                        "priority": "high",
                    },
                },
            },
        }
    )

    assert "## Close-out Gate" in prompt
    assert "issue_review_closeout_missing" in prompt
    assert "Do not start new implementation work" in prompt
    assert 'control-plane issue review "OCT-18"' in prompt
    assert "--decision approve|request_changes|needs_followup|blocked" in prompt
    assert "Do not exit" in prompt


def test_runtime_prompt_hard_gates_requested_issue_review() -> None:
    prompt = runtime_prompt_from_config(
        {
            "promptTemplate": "# Base\n\nYou are a reviewer.",
            "_octopus": {
                "agentId": "agent-3",
                "agentName": "reviewer-2",
                "context": {
                    "wakeSource": "review",
                    "wakeReason": "issue_review_requested",
                    "role": "reviewer",
                    "issue": {
                        "id": "issue-review-requested",
                        "identifier": "OCT-21",
                        "title": "评审富贵树文章",
                        "description": "检查文章质量并给出结构化评审结论。",
                        "status": "in_review",
                        "priority": "medium",
                    },
                },
            },
        }
    )

    assert "You have been assigned to review an issue" in prompt
    assert "评审富贵树文章" in prompt
    assert "检查文章质量" in prompt
    assert "## Review Gate" in prompt
    assert 'control-plane issue review "OCT-21"' in prompt
    assert "--decision approve|request_changes|needs_followup|blocked" in prompt
    assert "Do not take over implementation" in prompt
    assert "Do not exit" in prompt
