# HEARTBEAT.md -- Agent Heartbeat Checklist

Run this checklist on every heartbeat.

## 1. Identity and Context

- Confirm your id, role, budget, chainOfCommand.
- Check wake context for task triggers.

## 2. Local Planning Check

1. Read today's plan from memory.
2. Review planned items: completed, blocked, upcoming.
3. Resolve blockers or escalate.
4. Record progress updates.

## 3. Approval Follow-Up

If approval context is set, review linked issues and close/comment.

## 4. Get Inbox Work

- Check `control-plane agent inbox --json` for both assignee and reviewer rows.
- Prioritize reviewer `in_review` or `blocked` rows first, then assignee `in_progress`, then assignee `todo`.

## 5. Checkout and Work

- Always checkout before working.
- Do the work. Update status and comment when done.
- For delegated child issues, the parent issue must wait for those child issues to run and report back before summarizing their results. Do not complete delegated child work inside the parent run and then mark those child issues blocked or cancelled as unnecessary. Use `blocked` only for a real blocker, such as missing information, unavailable permissions, failed dependencies, or a required human/external action.
- Close-out gate: Do not exit an active issue heartbeat until the matching control-plane close-out command has succeeded.
- If `OCTOPUS_WAKE_REASON=issue_passive_followup`, inspect current issue state first, then execute exactly one close-out command before exiting: `control-plane issue done ...`, `control-plane issue block ...`, or `control-plane issue comment ...`. If a reviewed issue is blocked, write the blocker clearly enough for reviewer triage. Do not exit this wake with only a final assistant summary.
- If you are the reviewer, including for a `blocked` issue, record a structured review decision with `control-plane issue review --decision approve|request_changes|needs_followup|blocked --comment ...`. Use `blocked` only to confirm a human/external blocker, and name the next human action in the comment.
- If `OCTOPUS_WAKE_REASON=issue_review_closeout_missing`, inspect current state and execute exactly one `control-plane issue review ... --json` command before exiting. Do not use a free-form comment as the reviewer outcome.

## 6. Exit

- Comment on in_progress work before exiting.
- Reviewer work is not closed by a free-form accept/reject comment; use `control-plane issue review`.
- A successful `todo` or `in_progress` issue run without a close-out signal can trigger a same-agent passive follow-up.
- Do not exit `issue_passive_followup` until `control-plane issue done`, `control-plane issue block`, or `control-plane issue comment` has succeeded.
- Do not exit `issue_review_closeout_missing` until `control-plane issue review` has succeeded.
- Exit cleanly if no assignments.
