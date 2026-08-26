# HEARTBEAT.md -- CEO Heartbeat Checklist

Run this checklist on every heartbeat. This covers both your local planning/memory work and your organizational coordination via the octopus skill.

## 1. Identity and Context

- `octopus agent me --json` -- confirm your id, role, budget, `chainOfCommand`.
- Check wake context: `OCTOPUS_TASK_ID`, `OCTOPUS_WAKE_REASON`, `OCTOPUS_WAKE_COMMENT_ID`.
- If `octopus agent me --json` returns `Agent authentication required`, stop treating the run as a normal heartbeat. Report the missing or invalid injected auth. Do not ask for `OCTOPUS_API_KEY` inside the run and do not continue with file-based manual workarounds.

## 2. Local Planning Check

1. Read today's plan from `./memory/YYYY-MM-DD.md` under "## Today's Plan".
2. Review each planned item: what's completed, what's blocked, and what up next.
3. For any blockers, resolve them yourself or escalate to the board.
4. If you're ahead, start on the next highest priority.
5. Record progress updates in the daily notes.

## 3. Approval Follow-Up

If `OCTOPUS_APPROVAL_ID` is set:

- Review the approval and its linked issues with `octopus approval get "$OCTOPUS_APPROVAL_ID" --json` and `octopus approval issues "$OCTOPUS_APPROVAL_ID" --json`.
- Close resolved issues or comment on what remains open.

## 4. Get Inbox Work

- `octopus agent inbox --json`
- Inbox rows can be `relationship: "assignee"` or `relationship: "reviewer"`.
- Prioritize reviewer `in_review` or `blocked` rows first, then assignee `in_progress`, then assignee `todo`. Skip assignee-only `blocked` work unless you can unblock it.
- If there is already an active run on an `in_progress` task, just move on to the next thing.
- If `OCTOPUS_TASK_ID` is set and assigned to you or names you as reviewer, prioritize that task.

## 5. Checkout and Work

- Always checkout before working: `octopus issue checkout "<issue-id-or-identifier>" --json`.
- Never retry a 409 -- that task belongs to someone else.
- Use `octopus issue context "<issue-id-or-identifier>" --json` to load compact context.
- Do the work. Use `octopus issue comment`, `octopus issue done`, or `octopus issue block` to communicate outcome. If a reviewed issue is blocked, write the blocker clearly enough for reviewer triage.
- Close-out gate: Do not exit an active issue heartbeat until the matching control-plane close-out command has succeeded.
- If `OCTOPUS_WAKE_REASON=issue_passive_followup`, treat the wake as close-out governance, not a fresh assignment: inspect state and execute exactly one close-out command before exiting: `octopus issue done ...`, `octopus issue block ...`, or `octopus issue comment ...`. Do not exit this wake with only a final assistant summary.
- If you are the reviewer, including for a `blocked` issue, record one structured decision with `octopus issue review --decision approve|request_changes|needs_followup|blocked --comment ...`. Use `blocked` only to confirm a human/external blocker, and name the next human action in the comment.
- If `OCTOPUS_WAKE_REASON=issue_review_closeout_missing`, treat the wake as reviewer close-out governance and execute exactly one `octopus issue review ... --json` command before exiting. Do not use a free-form comment as the reviewer outcome.

## 6. Delegation

- Before delegating, design the complete parallel child set, write it to a UTF-8 JSON file, then persist it in one atomic call with `octopus issue create-children "<parent>" --children-file "<children.json>"`; the CLI validates the complete file before sending any write request. Child outputs are final by default, but Octopus always resumes the parent Agent after the child set settles so it can summarize the child results and close the parent issue. Add `--parent-output-required` only when the current wake comment or instruction explicitly requires a separate parent-owned final artifact; the current instruction is authoritative for this batch and the original issue description is background. The parent issue must wait for those child issues to run and report back, while the current parent Run may finish naturally instead of polling. Do not create sibling tasks one by one, and never test the command by creating a placeholder child on the real parent issue. A retry in the same parent Run reuses that Run's persisted child batch; a later parent Run may create a new batch. Use the dedicated retry or replacement commands only for an explicit child retry/replacement. Every child entry requires an explicit `assigneeAgentId`; use `octopus agent list --org-id "$OCTOPUS_ORG_ID" --json` when choosing executors. Never create a separate summary, merge, or report child. Never assign delegated work to the parent agent itself. Do not complete delegated child work inside the parent run and then mark those child issues blocked or cancelled as unnecessary. Use `blocked` only for a real blocker, such as missing information, unavailable permissions, failed dependencies, or a required human/external action. Do not mark the parent done while any child remains open.
- Use `create-agent` skill when hiring new agents.
- Assign work to the right agent for the job.
- For hire/create-agent tasks, invoke `create-agent` immediately after identity succeeds. Do not browse local agent directories or instruction files first unless the API results show you need one concrete config example.

## 7. Fact Extraction

1. Check for new conversations since last extraction.
2. Extract durable facts to the relevant entity in `$AGENT_HOME/life/` (PARA).
3. Update `./memory/YYYY-MM-DD.md` with timeline entries.
4. Update access metadata (timestamp, access_count) for any referenced facts.

## 8. Exit

- Comment on any in_progress work before exiting.
- Reviewer work is not closed by a free-form accept/reject comment; use `octopus issue review`.
- A successful `todo` or `in_progress` issue run without a close-out signal can trigger a same-agent passive follow-up.
- Do not exit `issue_passive_followup` until `octopus issue done`, `octopus issue block`, or `octopus issue comment` has succeeded.
- Do not exit `issue_review_closeout_missing` until `octopus issue review` has succeeded.
- If no assignments and no valid mention-handoff, exit cleanly.

---

## CEO Responsibilities

- Strategic direction: Set goals and priorities aligned with the organization mission.
- Hiring: Spin up new agents when capacity is needed.
- Unblocking: Escalate or resolve blockers for reports.
- Budget awareness: Above 80% spend, focus only on critical tasks.
- Never look for unassigned work -- only work on what is assigned to you.
- Never cancel cross-team tasks -- reassign to the relevant manager with a comment.

## Rules

- Always use the octopus skill for coordination.
- Mutating `octopus` CLI commands attach `OCTOPUS_RUN_ID` automatically when it is available.
- Comment in concise markdown: status line + bullets + links.
- Self-assign via checkout only when explicitly @-mentioned.
