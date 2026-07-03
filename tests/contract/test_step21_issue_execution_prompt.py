from __future__ import annotations

from packages.runtimes.instructions import runtime_prompt_from_config
from packages.runtimes.tool_capabilities import append_runtime_workspace_guidance


def test_shared_project_workspace_prompt_prefers_workspace_cwd_for_reports() -> None:
    prompt = append_runtime_workspace_guidance(
        "Create the requested report.",
        {
            "octopusWorkspace": {
                "cwd": "D:/coding/test/dev_test",
                "worktreePath": "D:/coding/test/dev_test",
                "mode": "shared_workspace",
                "workspaceKind": "project_execution",
                "orgArtifactsDir": "D:/coding/octopus/.octopus/instances/dev/organizations/org/workspaces/artifacts",
                "issueArtifactsDir": "D:/coding/octopus/.octopus/instances/dev/organizations/org/workspaces/artifacts/issues/issue-4",
            }
        },
    )

    assert "## Workspace Output Contract" in prompt
    assert "Workspace worktree: `D:/coding/test/dev_test`" in prompt
    assert "Prefer the workspace worktree with a clear shared path" in prompt
    assert "reports/" in prompt
    assert "$OCTOPUS_WORKSPACE_CWD" in prompt
    assert "do not use `$OCTOPUS_ISSUE_ARTIFACTS_DIR` as the default deliverable target" in prompt
    assert "Issue compatibility artifacts path" in prompt


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
    assert "## Runtime Context Contract" in prompt
    assert "do not hard-code the `.octopus/bin` shim path" in prompt
    assert "Do not read or create workspace `.env` files" in prompt
    assert "$env:OCTOPUS_AGENT_ID" in prompt
    assert "## Close-out Gate" in prompt
    assert "Every issue run must leave a durable close-out signal" in prompt
    assert 'octopus issue done "issue-hello"' in prompt
    assert 'octopus issue block "issue-hello"' in prompt
    assert 'octopus issue comment "issue-hello"' in prompt
    assert (
        "If the issue has a reviewer, `issue done` submits the work for review"
        in prompt
    )


def test_runtime_prompt_requires_real_child_issues_for_subtasks() -> None:
    prompt = runtime_prompt_from_config(
        {
            "promptTemplate": "# Base\n\nYou are an agent.",
            "_octopus": {
                "context": {
                    "wakeSource": "assignment",
                    "wakeReason": "issue_execute",
                    "issue": {
                        "id": "issue-parent",
                        "identifier": "OCT-42",
                        "title": "五岳名山诗歌创作 - 管理汇总",
                        "description": "主任务负责管理进度，拆分五个子任务并汇总审核。",
                        "status": "in_progress",
                        "priority": "medium",
                    },
                }
            },
        }
    )

    assert "## Subtask Coordination" in prompt
    assert "Product-visible subtasks must be Octopus child issues" in prompt
    assert (
        'octopus issue create --org-id "$OCTOPUS_ORG_ID" --parent-id "OCT-42"'
        in prompt
    )
    assert "--status todo" in prompt
    assert "--assignee-agent-id" in prompt
    assert 'octopus agent list --org-id "$OCTOPUS_ORG_ID"' in prompt
    assert (
        "Do not mark the parent issue done while child issues are still open" in prompt
    )
    assert "add a progress comment and exit the current run" in prompt
    assert "Do not poll or wait for delegated children" in prompt
    assert "Never assign a delegated child issue to yourself" in prompt
    assert (
        "Do not complete delegated child work inside the parent run and then mark those child issues blocked or cancelled as unnecessary"
        in prompt
    )
    assert "Use `blocked` only for a real blocker" in prompt
    assert "internal `task` subagent call" in prompt
    assert "do not appear in the board" in prompt
    assert "childKey" not in prompt
    assert "--child-key" not in prompt


def test_runtime_prompt_reconciles_existing_children_on_rerun() -> None:
    prompt = runtime_prompt_from_config(
        {
            "promptTemplate": "# Base\n\nYou are an agent.",
            "_octopus": {
                "context": {
                    "wakeSource": "assignment",
                    "wakeReason": "issue_execute",
                    "parentExecutionStage": "children_blocked",
                    "childOutputs": {
                        "totalChildCount": 2,
                        "children": [
                            {
                                "id": "child-1",
                                "identifier": "OCT-101",
                                "title": "东海介绍",
                                "status": "done",
                                "workProducts": [{"id": "wp-1"}],
                            },
                            {
                                "id": "child-2",
                                "identifier": "OCT-102",
                                "title": "西海介绍",
                                "status": "blocked",
                                "workProducts": [],
                            },
                        ],
                    },
                    "issue": {
                        "id": "issue-parent",
                        "identifier": "OCT-100",
                        "title": "介绍四海",
                        "description": "重新执行并处理已有子任务。",
                        "status": "in_progress",
                        "priority": "medium",
                    },
                }
            },
        }
    )

    assert "## Parent Rerun Reconcile" in prompt
    assert "not a blank first execution" in prompt
    assert "children_blocked" in prompt
    assert "东海介绍" in prompt
    assert "西海介绍" in prompt
    assert "Do not ignore existing children" in prompt
    assert "childKey" not in prompt
    assert "--child-key" not in prompt


def test_runtime_prompt_converges_child_primary_products_after_children_settle() -> None:
    prompt = runtime_prompt_from_config(
        {
            "promptTemplate": "# Base\n\nYou are an agent.",
            "_octopus": {
                "context": {
                    "wakeSource": "assignment",
                    "wakeReason": "issue_children_settled",
                    "childPrimaryWorkProducts": [
                        {
                            "id": "wp-xishi",
                            "title": "西施.md",
                            "summary": "西施介绍",
                            "sourceIssueTitle": "西施介绍",
                        }
                    ],
                    "childWorkProductsPrompt": "## Child Primary Work Products\n\n- 西施介绍: 西施.md — 西施介绍",
                    "blockedChildIssues": [
                        {
                            "id": "child-taihu",
                            "identifier": "OCT-91",
                            "title": "太湖介绍",
                            "status": "blocked",
                        }
                    ],
                    "issue": {
                        "id": "issue-parent",
                        "identifier": "OCT-88",
                        "title": "四大美女报告",
                        "description": "汇总四个子任务并生成最终报告。",
                        "status": "in_progress",
                        "priority": "medium",
                    },
                }
            },
        }
    )

    assert "## Parent Deliverable Convergence" in prompt
    assert "issue_children_settled" in prompt
    assert "All direct child issues are now terminal" in prompt
    assert "西施.md" in prompt
    assert "parent issue's final deliverable" in prompt
    assert "Blocked or Cancelled Child Issues" in prompt
    assert "太湖介绍" in prompt
    assert "Do not mark the parent issue done" in prompt
    assert "$OCTOPUS_WORKSPACE_CWD" in prompt
    assert "Use `$OCTOPUS_ISSUE_ARTIFACTS_DIR` only as a compatibility fallback" in prompt
    assert "not as the default target for shared project work" in prompt
    assert 'octopus issue done "OCT-88"' in prompt


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
    assert 'octopus issue done "OCT-17"' in prompt
    assert 'octopus issue block "OCT-17"' in prompt
    assert 'octopus issue comment "OCT-17"' in prompt
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
    assert 'octopus issue review "OCT-18"' in prompt
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
    assert 'octopus issue review "OCT-21"' in prompt
    assert "--decision approve|request_changes|needs_followup|blocked" in prompt
    assert "Do not take over implementation" in prompt
    assert "Do not exit" in prompt
