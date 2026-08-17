from __future__ import annotations

from pathlib import Path
from typing import Any


def runtime_prompt_from_config(config: dict[str, Any]) -> str:
    return _join_prompt_sections(
        [
            _base_prompt_from_config(config),
            _tacit_memory_prompt(config),
            _agent_memory_guidance(config),
            _runtime_context_guidance(config),
            _heartbeat_prompt(config),
        ]
    )


def _base_prompt_from_config(config: dict[str, Any]) -> str:
    prompt = _string(config.get("promptTemplate"))
    if prompt:
        return prompt
    instructions_path = _resolve_instructions_path(config)
    if instructions_path is None:
        return ""
    try:
        return instructions_path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _tacit_memory_prompt(config: dict[str, Any]) -> str:
    memory_path = _resolve_tacit_memory_path(config)
    if memory_path is None:
        return ""
    try:
        memory = memory_path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not memory.strip():
        return ""
    return _join_prompt_sections(["## Tacit Agent Memory", memory])


def _resolve_tacit_memory_path(config: dict[str, Any]) -> Path | None:
    instructions_path = _resolve_instructions_path(config)
    if instructions_path is not None:
        memory_path = instructions_path.parent / "MEMORY.md"
        if not _same_path(instructions_path, memory_path):
            return memory_path
    octopus = config.get("_octopus")
    if not isinstance(octopus, dict):
        return None
    instructions_dir = _string(octopus.get("agentInstructionsDir"))
    if not instructions_dir:
        return None
    return Path(instructions_dir).expanduser() / "MEMORY.md"


def _agent_memory_guidance(config: dict[str, Any]) -> str:
    octopus = config.get("_octopus")
    if not isinstance(octopus, dict):
        return ""
    agent_home = _string(octopus.get("agentHome"))
    if not agent_home:
        return ""
    return "\n".join(
        [
            "## Agent Memory Contract",
            "",
            f"Your durable agent home is `{agent_home}`.",
            "- Keep stable preferences, operating patterns, and lessons learned in `$AGENT_HOME/instructions/MEMORY.md`.",
            "- Keep daily notes in `$AGENT_HOME/memory/YYYY-MM-DD.md`.",
            "- Keep structured long-term knowledge in `$AGENT_HOME/life/`.",
            "- Use the `para-memory-files` skill for memory file operations when it is available.",
            "- Do not store secrets, credentials, or transient task logs in long-term memory.",
            "- Do not assume `$HOME` is long-term memory; local runtimes may use it for CLI credentials and caches.",
        ]
    )


def _runtime_context_guidance(config: dict[str, Any]) -> str:
    octopus = config.get("_octopus")
    if not isinstance(octopus, dict):
        return ""
    context = octopus.get("context")
    if not isinstance(context, dict) or not isinstance(context.get("issue"), dict):
        return ""
    return "\n".join(
        [
            "## Runtime Context Contract",
            "",
            "Octopus injects runtime context directly into the process environment.",
            "- Use `octopus ... --json` from `PATH`; do not hard-code the `.octopus/bin` shim path.",
            "- Do not read or create workspace `.env` files to recover `OCTOPUS_*` values.",
            "- On Windows PowerShell, read variables as `$env:OCTOPUS_AGENT_ID`, `$env:OCTOPUS_ORG_ID`, and `$env:OCTOPUS_RUN_ID`.",
            "- In POSIX shells, read variables as `$OCTOPUS_AGENT_ID`, `$OCTOPUS_ORG_ID`, and `$OCTOPUS_RUN_ID`.",
            "- Prefer CLI commands that use injected defaults, such as `octopus agent me --json`, `octopus agent inbox --json`, and `octopus issue checkout <issue> --json`.",
        ]
    )


def _heartbeat_prompt(config: dict[str, Any]) -> str:
    octopus = config.get("_octopus")
    if not isinstance(octopus, dict):
        return ""
    context = octopus.get("context")
    if not isinstance(context, dict):
        return ""
    issue = context.get("issue")
    if not isinstance(issue, dict):
        return ""
    wake_source = _string(context.get("wakeSource")) or ""
    wake_reason = _string(context.get("wakeReason")) or ""
    if wake_reason == "issue_passive_followup":
        return _passive_followup_issue_prompt(
            agent_id=_string(octopus.get("agentId")) or "",
            agent_name=_string(octopus.get("agentName")) or "",
            issue=issue,
        )
    if wake_reason == "issue_review_closeout_missing":
        return _review_closeout_issue_prompt(
            agent_id=_string(octopus.get("agentId")) or "",
            agent_name=_string(octopus.get("agentName")) or "",
            issue=issue,
        )
    if wake_reason in {
        "issue_review_requested",
        "issue_convergence_review_requested",
    }:
        return _requested_issue_review_prompt(
            agent_id=_string(octopus.get("agentId")) or "",
            agent_name=_string(octopus.get("agentName")) or "",
            issue=issue,
        )
    if wake_source != "assignment" and wake_reason not in {
        "issue_assigned",
        "issue_execute",
        "issue_checked_out",
    }:
        return ""
    return _assignment_issue_prompt(
        agent_id=_string(octopus.get("agentId")) or "",
        agent_name=_string(octopus.get("agentName")) or "",
        issue=issue,
        context=context,
    )


def _passive_followup_issue_prompt(
    *, agent_id: str, agent_name: str, issue: dict[str, Any]
) -> str:
    issue_ref = _issue_ref(issue)
    return _join_prompt_sections(
        [
            _issue_header_prompt(
                agent_id=agent_id,
                agent_name=agent_name,
                issue=issue,
                intro="You have been woken for issue close-out governance.",
            ),
            "\n".join(
                [
                    "## Close-out Gate",
                    "",
                    "Wake reason: `issue_passive_followup`.",
                    "This run exists only because a previous successful issue run exited without a durable close-out signal.",
                    "Do not start new implementation work. Inspect the current issue state only enough to choose the correct close-out command.",
                    "",
                    "Before exiting, execute exactly one of these commands and confirm it succeeded:",
                    f'- work is complete: `octopus issue done "{issue_ref}" --comment "<markdown>" --json`',
                    f'- work is blocked: `octopus issue block "{issue_ref}" --comment "<markdown>" --json`',
                    f'- work remains open but has a clear next step: `octopus issue comment "{issue_ref}" --body "<markdown>" --json`',
                    "If the issue has a reviewer, `issue done` submits the work for review and the control plane moves the issue to `in_review`; only a reviewer decision can mark it done.",
                    "",
                    "A final assistant message is not a close-out signal. Do not exit until one command above succeeds.",
                ]
            ),
        ]
    )


def _review_closeout_issue_prompt(
    *, agent_id: str, agent_name: str, issue: dict[str, Any]
) -> str:
    issue_ref = _issue_ref(issue)
    return _join_prompt_sections(
        [
            _issue_header_prompt(
                agent_id=agent_id,
                agent_name=agent_name,
                issue=issue,
                intro="You have been woken to repair a missing reviewer close-out decision.",
            ),
            "\n".join(
                [
                    "## Close-out Gate",
                    "",
                    "Wake reason: `issue_review_closeout_missing`.",
                    "This run exists only because a previous reviewer run exited without a structured review decision.",
                    "Do not start new implementation work. Inspect the current issue state only enough to choose the review outcome.",
                    "",
                    "Before exiting, execute exactly one reviewer decision command and confirm it succeeded:",
                    f'`octopus issue review "{issue_ref}" --decision approve|request_changes|needs_followup|blocked --comment "<markdown>" --json`',
                    "",
                    "Do not use `octopus issue comment` as a substitute for reviewer close-out. Do not exit until `octopus issue review` succeeds.",
                ]
            ),
        ]
    )


def _requested_issue_review_prompt(
    *, agent_id: str, agent_name: str, issue: dict[str, Any]
) -> str:
    issue_ref = _issue_ref(issue)
    return _join_prompt_sections(
        [
            _issue_header_prompt(
                agent_id=agent_id,
                agent_name=agent_name,
                issue=issue,
                intro="You have been assigned to review an issue.",
            ),
            "\n".join(
                [
                    "Inspect the issue, its work products, and relevant evidence before deciding.",
                    "Do not take over implementation unless explicitly asked.",
                    "",
                    "## Review Gate",
                    "",
                    "Before exiting, execute exactly one reviewer decision command and confirm it succeeded:",
                    f'`octopus issue review "{issue_ref}" --decision approve|request_changes|needs_followup|blocked --comment "<markdown>" --json`',
                    "",
                    "Do not use `octopus issue comment` as a substitute for the structured reviewer decision.",
                    "A final assistant message is not a review decision. Do not exit until `octopus issue review` succeeds.",
                ]
            ),
        ]
    )


def _assignment_issue_prompt(
    *, agent_id: str, agent_name: str, issue: dict[str, Any], context: dict[str, Any]
) -> str:
    issue_ref = _issue_ref(issue)
    return _join_prompt_sections(
        [
            _issue_header_prompt(
                agent_id=agent_id,
                agent_name=agent_name,
                issue=issue,
                intro="You have been assigned to work on an issue.",
            ),
            (
                "Your task is to review this issue and begin working on it. "
                "Use the available tools to explore the codebase, understand "
                "the requirements, and implement a solution."
            ),
            _rerun_reconcile_prompt(issue_ref, context),
            _subtask_coordination_prompt(issue_ref, issue),
            _child_deliverable_convergence_prompt(issue_ref, context),
            "\n".join(
                [
                    "## Close-out Gate",
                    "",
                    "Every issue run must leave a durable close-out signal in the control plane before exiting.",
                    "A final assistant message is not a close-out signal.",
                    "",
                    "Before exiting, execute exactly one of these commands and confirm it succeeded:",
                    f'- work is complete: `octopus issue done "{issue_ref}" --comment "<markdown>" --json`',
                    f'- work is blocked: `octopus issue block "{issue_ref}" --comment "<markdown>" --json`',
                    f'- work remains open but has a clear next step: `octopus issue comment "{issue_ref}" --body "<markdown>" --json`',
                    "If the issue has a reviewer, `issue done` submits the work for review and the control plane moves the issue to `in_review`; only a reviewer decision can mark it done.",
                    "",
                    "Do not exit until one command above succeeds.",
                ]
            ),
        ]
    )


def _rerun_reconcile_prompt(issue_ref: str, context: dict[str, Any]) -> str:
    child_outputs = context.get("childOutputs")
    if not isinstance(child_outputs, dict):
        return ""
    children = child_outputs.get("children")
    total = child_outputs.get("totalChildCount")
    if not isinstance(children, list) or not children:
        return ""
    stage = _string(context.get("parentExecutionStage")) or "rerun_reconcile"
    guidance = [
        "## Parent Rerun Reconcile",
        "",
        f"This parent issue already has {total or len(children)} direct child issue(s). Treat this run as a rerun/reconcile pass, not a blank first execution.",
        f"Current parent execution stage: `{stage}`.",
        f'Inspect existing children with `octopus issue children "{issue_ref}" --include-work-products --json` before creating, replacing, cancelling, or completing work.',
        "Reuse the persisted child split. Retry or explicitly replace blocked work with the dedicated child recovery commands; do not submit another initial split or silently create sibling tasks for the same work.",
        "A normal rerun is reconciliation, not replanning. Replanning the child set requires an explicit operator action outside this run.",
    ]
    for child in children[:12]:
        if not isinstance(child, dict):
            continue
        label = (
            _string(child.get("identifier"))
            or _string(child.get("id"))
            or "child issue"
        )
        title = _string(child.get("title")) or "Untitled child issue"
        status = _string(child.get("status")) or "unknown"
        products = child.get("workProducts")
        product_count = len(products) if isinstance(products, list) else 0
        guidance.append(f"- {label}: {title} ({status}, workProducts={product_count})")
    return "\n".join(guidance)


def _child_deliverable_convergence_prompt(
    issue_ref: str, context: dict[str, Any]
) -> str:
    if _string(context.get("wakeReason")) != "issue_children_settled":
        return ""
    prompt = _string(context.get("childWorkProductsPrompt"))
    products = context.get("childPrimaryWorkProducts")
    blocked_children = context.get("blockedChildIssues")
    if (
        not prompt
        and not isinstance(products, list)
        and not isinstance(blocked_children, list)
    ):
        return ""
    guidance = [
        "## Parent Deliverable Convergence",
        "",
        "Wake reason: `issue_children_settled`.",
        "All direct child issues are now terminal. Your job is to synthesize their primary deliverables into the parent issue's final deliverable.",
        "Do not finish by only summarizing child task status. Produce a parent-owned final report or artifact first.",
        f'Use `octopus issue get "{issue_ref}" --json` if you need the current registered work products and child provenance.',
    ]
    if prompt:
        guidance.extend(["", prompt])
    if isinstance(blocked_children, list) and blocked_children:
        guidance.extend(["", "## Blocked or Cancelled Child Issues", ""])
        for child in blocked_children:
            if not isinstance(child, dict):
                continue
            label = (
                _string(child.get("identifier"))
                or _string(child.get("title"))
                or "child issue"
            )
            title = _string(child.get("title")) or "Untitled child issue"
            status = _string(child.get("status")) or "blocked"
            guidance.append(f"- {label}: {title} ({status})")
        guidance.extend(
            [
                "",
                "Do not mark the parent issue done while any child is blocked or cancelled unless the user explicitly asked for an incomplete deliverable. Either fix/retry the missing child work, create a replacement child, or block the parent issue with a clear missing-output explanation.",
            ]
        )
    guidance.extend(
        [
            "",
            "Before closing out, write the final deliverable to the user-requested path or a clear shared path under `$OCTOPUS_WORKSPACE_CWD` such as `reports/<name>.md`. Use `$OCTOPUS_ISSUE_ARTIFACTS_DIR` only as a compatibility fallback, not as the default target for shared project work.",
        ]
    )
    return "\n".join(guidance)


def _subtask_coordination_prompt(issue_ref: str, issue: dict[str, Any]) -> str:
    text = " ".join(
        [
            _string(issue.get("title")) or "",
            _string(issue.get("description")) or "",
        ]
    ).lower()
    if not any(
        marker in text
        for marker in (
            "subtask",
            "sub-task",
            "child task",
            "split",
            "delegate",
            "子任务",
            "拆分",
            "分解",
            "并行",
        )
    ):
        return ""
    return "\n".join(
        [
            "## Subtask Coordination",
            "",
            "This issue asks for split or delegated work. Product-visible subtasks must be Octopus child issues.",
            'List available agents first with `octopus agent list --org-id "$OCTOPUS_ORG_ID" --json` when you need to choose who should execute child issues.',
            f'Before creating any child issue, first check existing children with `octopus issue children "{issue_ref}" --include-work-products --json`. Reuse the persisted split on reruns; do not recreate it.',
            "Submit the complete set of real, parallel subtasks in one atomic call with "
            f'`octopus issue create-children "{issue_ref}" --children-json \'[{{"title":"<subtask>","description":"<details>","assigneeAgentId":"<agent-id>"}}]\' --json`. '
            "Do not create delegated siblings one at a time.",
            "Do not create a child whose job is to summarize, merge, or report on the other children. After all children settle, Octopus wakes this parent issue and the parent owns the final synthesis and deliverable.",
            "Set `--assignee-agent-id` explicitly for every delegated child issue. Prefer a suitable agent other than yourself when one is available.",
            "Never assign a delegated child issue to yourself. If you will do that work inside the parent run, do not create a child issue for it.",
            "After the atomic child creation succeeds, add a progress comment and exit the current run. Octopus releases the issue execution lock, runs the children, and wakes the parent again after every child is terminal.",
            "Do not poll or wait for delegated children inside the current runtime process because that keeps the issue execution slot occupied.",
            "Do not complete delegated child work inside the parent run and then mark those child issues blocked or cancelled as unnecessary.",
            "Use `blocked` only for a real blocker, such as missing information, unavailable permissions, failed dependencies, or a required human/external action. If an existing child is blocked or cancelled, do not recreate the same sibling; retry/reassign it, create an explicit replacement child that references the blocked child, or block the parent with the missing output.",
            "Do not mark the parent issue done while child issues are still open; wait for child issues to finish, or explicitly close/cancel them with a reason.",
            "Do not treat a runtime-local planning list, todo item, or internal `task` subagent call as an Octopus subtask. Those are execution helpers only and do not appear in the board.",
            "If the work should stay inside the parent run, do not create delegated child issues for it; say that explicitly in the close-out comment.",
        ]
    )


def _issue_header_prompt(
    *, agent_id: str, agent_name: str, issue: dict[str, Any], intro: str
) -> str:
    agent_label = agent_id
    if agent_name:
        agent_label = f"{agent_id} ({agent_name})" if agent_id else agent_name
    return "\n".join(
        [
            f"You are agent {agent_label}. {intro}",
            "",
            "## Task Context",
            "",
            f"**Issue:** {_string(issue.get('title')) or ''}",
            f"**ID:** {_issue_ref(issue)}",
            f"**Status:** {_string(issue.get('status')) or ''}",
            f"**Priority:** {_string(issue.get('priority')) or ''}",
            "",
            "**Description:**",
            _string(issue.get("description")) or "",
        ]
    )


def _issue_ref(issue: dict[str, Any]) -> str:
    return _string(issue.get("identifier")) or _string(issue.get("id")) or ""


def _resolve_instructions_path(config: dict[str, Any]) -> Path | None:
    raw_path = _string(config.get("instructionsFilePath"))
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if path.is_absolute():
        return path
    cwd = _string(config.get("cwd"))
    if not cwd:
        return None
    cwd_path = Path(cwd).expanduser()
    if not cwd_path.is_absolute():
        return None
    return cwd_path / path


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _join_prompt_sections(sections: list[str]) -> str:
    return "\n\n".join(section.strip() for section in sections if section.strip())


def _same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left.absolute() == right.absolute()
