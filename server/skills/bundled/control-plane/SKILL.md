---
name: control-plane
description: Interact with the control plane through the `control-plane` CLI to manage tasks, approvals, comments, issue documents, and organization skills during heartbeats. Use for control plane coordination only, not for the domain work itself.
---

# control-plane skill

You run in **heartbeats**: short execution windows triggered by control plane. Each heartbeat, wake up, inspect assigned work, do one useful chunk, communicate clearly, and exit.

This skill is now **CLI-first**.

- Use `control-plane ... --json` for control-plane work.
- Use `control-plane agent capabilities --json` when you need machine-readable discovery of supported commands.
- Use `references/cli-reference.md` for the stable command catalog.
- Treat `references/api-reference.md` as **internal/debug/compatibility** documentation, not the normal agent interface. API fallback is allowed only when a CLI command exits nonzero with a diagnostic error, or when a runtime/packaging bug makes a required `control-plane ... --json` command return exit 0 with empty stdout; record that fallback in the issue comment or run notes.
- If a remote runtime wake text explicitly says **HTTP compatibility mode**, follow that wake text for that run. Otherwise use the CLI.

## Authentication

control plane injects the runtime context for you. Common env vars:

- `OCTOPUS_AGENT_ID`
- `OCTOPUS_ORG_ID`
- `OCTOPUS_API_URL`
- `OCTOPUS_API_KEY`
- `OCTOPUS_RUN_ID`

Optional wake-context vars may also appear:

- `OCTOPUS_TASK_ID`
- `OCTOPUS_WAKE_REASON`
- `OCTOPUS_WAKE_COMMENT_ID`
- `OCTOPUS_APPROVAL_ID`
- `OCTOPUS_APPROVAL_STATUS`
- `OCTOPUS_LINKED_ISSUE_IDS`

Rules:

- Never ask for `OCTOPUS_API_KEY` inside a normal heartbeat.
- Never hard-code the API URL.
- For local adapters and packaged desktop, `control-plane` is expected to already be on `PATH`.
- In manual local CLI mode outside heartbeats, use `control-plane agent local-cli <agent-ref> --org-id <org-id>` to mint an agent key, optionally install bundled control-plane skills locally, and print the required `OCTOPUS_*` exports.

## Shared Workspace

Each organization has one system-managed shared workspace root at:

- `~/.control-plane/instances/<instance>/organizations/<org-id>/workspaces`

Important files and conventions:

- Structured shared references live in the org `Resources` catalog. Agents do not receive the whole org catalog automatically.
- If a run or chat is linked to a project, control plane injects only that project's attached resources into the runtime context.
- If you need broader org-wide resources, query the org resource catalog explicitly instead of assuming it is already in the prompt.
- Use Workspaces for disk-backed shared files, plans, and skill packages.
- When you need to place durable generated output on disk, prefer `$OCTOPUS_ORG_ARTIFACTS_DIR` for screenshots, images, mockups, reports, CSVs, handoff logs, and other user-visible files. Use `/tmp` only for transient scratch files and temporary verification artifacts.
- For other shared output, prefer the managed workspace paths control plane injected for this run such as `$OCTOPUS_ORG_PLANS_DIR`, `$OCTOPUS_ORG_SKILLS_DIR`, and the active `$OCTOPUS_WORKSPACE_CWD` or `$OCTOPUS_ORG_WORKSPACE_ROOT`. Do not invent new top-level `projects/` folders.
- If a `resources.md` file exists, treat it like a normal workspace file rather than a reserved control plane surface.
- Agent-specific files live under `workspaces/agents/<workspace-key>/...`.
- New projects do not create or configure their own workspace roots.

## Heartbeat Procedure

Follow this order unless the wake context clearly requires a different first step.

**Step 1 — Identity.** If identity is not already known, run:

```bash
control-plane agent me --json
```

Use the result for your id, org, role, budget, and `chainOfCommand`.

**Step 2 — Approval follow-up.** If `OCTOPUS_APPROVAL_ID` is set, review it first:

```bash
control-plane approval get "$OCTOPUS_APPROVAL_ID" --json
control-plane approval issues "$OCTOPUS_APPROVAL_ID" --json
```

For each linked issue:

- mark it done if the approval fully resolves the work
- or add a comment explaining what remains open and what happens next

**Step 3 — Get assignments.** Prefer the compact inbox:

```bash
control-plane agent inbox --json
```

Inbox rows include a `relationship` field:

- `assignee`: execution work you own
- `reviewer`: review or blocker-triage work where the issue is in `in_review`
  or `blocked`

Prioritize active close-out work first: reviewer rows with `status:
`"in_review"` or `"blocked"`, then assignee `in_progress`, then assignee
`todo`. Skip assignee-only `blocked` work unless you can actually unblock it.

If `OCTOPUS_TASK_ID` is set and the task is assigned to you or names you as
reviewer, prioritize it first.

**Step 4 — Mention-triggered wakes.** If `OCTOPUS_WAKE_COMMENT_ID` is set, read the relevant issue context before doing anything else on that task:

```bash
control-plane issue context "$OCTOPUS_TASK_ID" --wake-comment-id "$OCTOPUS_WAKE_COMMENT_ID" --json
```

If the comment explicitly asks you to take ownership, you may self-assign by checkout. Otherwise respond only if useful and continue with your assigned work.
An `@Name` mention is a request for attention or collaboration. It does not transfer issue ownership, reopen an issue, or authorize competing runs unless the comment explicitly asks for that handoff and the normal workflow permits it.

**Step 5 — Checkout before work.** Never start work without checkout.

```bash
control-plane issue checkout "<issue-id-or-identifier>" --json
```

Rules:

- `issue checkout` defaults `--agent-id` from `OCTOPUS_AGENT_ID`
- mutating CLI commands automatically attach `OCTOPUS_RUN_ID` when present
- a `409` means another agent owns the task; do not retry it

**Step 6 — Understand context.** Prefer the compact heartbeat context instead of replaying everything:

```bash
control-plane issue context "<issue-id-or-identifier>" --json
```

Comment reading rules:

- if `OCTOPUS_WAKE_COMMENT_ID` is set, fetch context with that wake comment first
- if you already know the thread and only need updates, use:

```bash
control-plane issue comments list "<issue-id-or-identifier>" --after "<last-comment-id>" --order asc --json
```

- use the full comment list only when cold-starting or when incremental context is not enough

**Step 7 — Do the work.** Use your normal tools for the domain task itself.

**Step 8 — Communicate outcome.**

**Close-out gate.** Do not exit an issue heartbeat until you have produced the
durable close-out signal that matches your role and wake reason. A natural
language summary in the final assistant message is not a close-out signal.
Use the CLI command, check that it exits successfully, and only then exit.

Before exiting an active `todo` or `in_progress` issue run, leave exactly one clear close-out signal. Use a progress comment if work remains, `issue done` if complete, `issue block` if blocked, or an explicit handoff comment when ownership changes. If the issue has a reviewer, `issue done` submits the work for review: control plane moves the issue to `in_review` and wakes the reviewer; only a structured reviewer decision can mark the issue done. If the issue has a reviewer, `issue block` is also a reviewer handoff: write the blocker clearly enough for the reviewer to decide next steps. control plane may wake you again with `OCTOPUS_WAKE_REASON=issue_passive_followup` when a successful run exits without that signal.

Do not claim that review was triggered unless the issue has
`reviewerAgentId`. Without either reviewer field, `issue done` marks the issue
`done` directly and `in_review` is rejected. `reviewerUserId` routes the issue
to human review but does not create a reviewer agent run.

If `OCTOPUS_WAKE_REASON=issue_passive_followup`, this run exists only because
the previous successful run did not leave a close-out signal. Do not do fresh
implementation work first. Inspect current issue state, then execute exactly
one of these commands before exiting:

- work is complete: `control-plane issue done "<issue-id-or-identifier>" --comment "<markdown>" --json`
- work is blocked: `control-plane issue block "<issue-id-or-identifier>" --comment "<markdown>" --json`
- work remains open but has a clear next step: `control-plane issue comment "<issue-id-or-identifier>" --body "<markdown>" --json`

For passive follow-up, a final assistant answer such as "done", "looks good",
or "I will follow up" is not enough. Do not exit until one of the three CLI
commands above succeeds.

Before exiting a reviewer run or an inbox row with `relationship: "reviewer"`,
leave exactly one structured reviewer decision. Do not rely on free-form
comments such as "reject" or "accepted" as the durable outcome. Reviewer rows
may be `in_review` or `blocked`; blocked reviewer work is blocker triage, not
permission to take over implementation unless explicitly asked:

- approve:

```bash
control-plane issue review "<issue-id-or-identifier>" --decision approve --comment "<markdown>" --json
```

- request changes and return the issue to the assignee:

```bash
control-plane issue review "<issue-id-or-identifier>" --decision request_changes --comment "<markdown>" --json
```

- keep the issue in its current review/blocker state because specific evidence
  or follow-up is still missing:

```bash
control-plane issue review "<issue-id-or-identifier>" --decision needs_followup --comment "<markdown>" --json
```

- block the issue:

```bash
control-plane issue review "<issue-id-or-identifier>" --decision blocked --comment "<markdown>" --json
```

Use `blocked` to confirm a human/external blocker. The comment must name the next human action; control plane records a human handoff and removes the issue from repeated reviewer pickup until the board changes the issue.

If `OCTOPUS_WAKE_REASON=issue_review_closeout_missing`, your previous reviewer
run succeeded without `control-plane issue review`. This is a correction run,
not a new review assignment. Inspect current state and execute exactly one
`control-plane issue review ... --decision approve|request_changes|needs_followup|blocked --comment ... --json`
command before exiting. Do not use `control-plane issue comment` as the
reviewer outcome in this wake.

- progress-only update:

```bash
control-plane issue comment "<issue-id-or-identifier>" --body "<markdown>" [--image "<path>"] --json
```

- completion:

```bash
control-plane issue done "<issue-id-or-identifier>" --comment "<markdown>" [--image "<path>"] --json
```

If the issue has a reviewer, this command means "ready for review" and moves
the issue to `in_review`; it does not bypass the reviewer or directly complete
the issue.

- blocker:

```bash
control-plane issue block "<issue-id-or-identifier>" --comment "<markdown>" [--image "<path>"] --json
```

- generic patch when workflow commands are not enough:

Add `--image "<path>"` one or more times when the close-out/progress comment should include local screenshots or images. Supported local image types are PNG, JPEG, WebP, and GIF; the CLI uploads them as issue attachments and appends Markdown image links.

If your comment mentions a screenshot path or uses a screenshot as validation evidence, attach that file with `--image "<path>"`. Do not leave only a local `/tmp/...` or workspace image path in the comment, because board users may not be able to inspect it from control plane.

```bash
control-plane issue update "<issue-id-or-identifier>" ... --json
```

**Step 9 — Delegate if needed.** When the issue or user asks to split work into
subtasks, child tasks, or parallel delegated tasks, those product-visible
subtasks must be real Octopus child issues. Create them with the generic create
surface before treating the work as delegated:

```bash
control-plane issue create --org-id "$OCTOPUS_ORG_ID" ... [--label-id "<label-id>"] [--label "<label-name>"] --json
```

Before delegating child issues, list available agents when you need to choose the executor:

```bash
control-plane agent list --org-id "$OCTOPUS_ORG_ID" --json
```

Before creating a child issue, list existing children for the parent and reuse the existing child when the title already matches:

```bash
control-plane issue list --org-id "$OCTOPUS_ORG_ID" --parent-id "<parent-id-or-identifier>" --json
```

Delegated child issues must be assigned explicitly and should be moved into executable work:

```bash
control-plane issue create --org-id "$OCTOPUS_ORG_ID" --parent-id "<parent-id-or-identifier>" --title "<subtask title>" --description "<details>" --status todo --assignee-agent-id "<agent-id>" --json
```

When you create an issue as an authenticated agent without an assignee, do not assume another agent will pick it up. For delegated subtasks, always pass an explicit `--assignee-agent-id`; prefer a suitable agent other than yourself when one is available.

Do not mark the parent issue done while child issues are still open. Wait for child issues to finish, or explicitly close/cancel them with a reason.

When the organization has a mature issue label taxonomy, agent-created issues must choose at least one label. List the available labels first when you are not sure which one applies:

```bash
control-plane issue labels list --org-id "$OCTOPUS_ORG_ID" --json
```

Always set `parentId`. Set `goalId` unless you are intentionally creating top-level management work.

Runtime-local todo lists, planning checkboxes, or internal subagent/task tool
calls are execution helpers only. They do not create Octopus board subtasks and
must not be reported as product-visible child tasks.

## Organization Skills Workflow

When you need to create a skill for yourself, prefer an agent-private skill:

```bash
control-plane agent skills create "$OCTOPUS_AGENT_ID" --name "<name>" --description "<description>" --enable --json
```

This creates the package under `AGENT_HOME/skills` and does not require organization skill mutation permission.

When a board user, CEO, or manager asks you to find, import, inspect, or assign organization skills:

1. Read `references/organization-skills.md`
2. Use the CLI surfaces in this order:

```bash
control-plane skill scan-local --org-id "$OCTOPUS_ORG_ID" --json
control-plane skill scan-projects --org-id "$OCTOPUS_ORG_ID" --json
control-plane skill import --org-id "$OCTOPUS_ORG_ID" --source "<source>" --json
control-plane skill list --org-id "$OCTOPUS_ORG_ID" --json
control-plane skill get "<skill-id>" --org-id "$OCTOPUS_ORG_ID" --json
control-plane skill file "<skill-id>" --org-id "$OCTOPUS_ORG_ID" --path SKILL.md --json
control-plane agent skills enable "<agent-id>" "<selection-ref>" --json
control-plane agent skills sync "<agent-id>" --desired-skills "<csv>" --json
```

Use `skills enable` when adding one or more skills because it preserves the
agent's existing enabled selections. Use `skills sync` only when you intend to
replace the full optional enabled-skill set.

After creating or copying a skill under `AGENT_HOME/skills/<slug>/`, check the
agent's Skills snapshot. If the skill is installed but not enabled, say:
installed but not enabled; future runs will not load it until enabled.

Do not fall back to raw `curl` for this workflow in local adapters or packaged desktop.

## Planning And Issue Documents

If asked to make or revise a plan, update the issue document with key `plan` instead of appending plan text to the issue description.

Typical flow:

```bash
control-plane issue documents get "<issue-id-or-identifier>" plan --json
control-plane issue documents revisions "<issue-id-or-identifier>" plan --json
control-plane issue documents put "<issue-id-or-identifier>" plan --title "Plan" --format markdown --body "<markdown>" --json
control-plane issue comment "<issue-id-or-identifier>" --body "<mention that the plan document was updated>" --json
```

Planning rules:

- do not mark the issue done when the request was only to create or revise a plan
- reassign back to the requester if that is the expected workflow
- when you reference the plan in comments, link directly to `#document-plan`

## Critical Rules

- Always checkout before doing task work.
- Never retry a `409` from checkout.
- Never look for unassigned work.
- Self-assign only on explicit @-mention handoff.
- Always communicate before exit on active work, except blocked issues with no new context.
- Treat `issue_passive_followup` as close-out governance, not a fresh assignment: inspect current state, then comment, finish, block, or hand off explicitly.
- Treat `issue_review_closeout_missing` as review close-out governance: inspect
  current state, including blocked handoffs, then record one structured review
  decision.
- Do not exit `issue_passive_followup` until `control-plane issue done`,
  `control-plane issue block`, or `control-plane issue comment` has succeeded.
- Do not exit `issue_review_closeout_missing` until `control-plane issue review`
  has succeeded.
- A reviewer does not take over implementation unless explicitly asked.
- A reviewer request for changes must use `control-plane issue review --decision
  request_changes`, not only a reject comment.
- If blocked, explicitly set the issue to `blocked` with a blocker comment before exit.
- Never cancel cross-team tasks. Reassign upward with explanation.
- Use `chainOfCommand` for escalation.
- Above 80% spend, focus on critical work only.
- Use `create-agent` for hiring or new-agent creation workflows.
- Git commits must use an explicit safe identity. control plane prepares isolated Codex homes and runtime worktrees with `user.useConfigOnly=true`; if `git commit` reports missing identity, configure repo-local `user.name` and `user.email` instead of bypassing the guard. Never accept `*@*.local` author or committer metadata.

## Comment Style (Required)

Use concise markdown with:

- a short status line
- bullets for what changed or what is blocked
- links to related issues, approvals, projects, agents, or documents when available

**Ticket references are links.** Never leave bare ticket ids like `PAP-224` in comments or descriptions when you can link them:

- `[PAP-224](/PAP/issues/PAP-224)`
- `[ZED-24](/ZED/issues/ZED-24)`

**Company-prefixed URLs are required.** Derive the prefix from the issue identifier and use it in all internal links:

- issues: `/<prefix>/issues/<issue-identifier>`
- issue comments: `/<prefix>/issues/<issue-identifier>#comment-<comment-id>`
- issue documents: `/<prefix>/issues/<issue-identifier>#document-<document-key>`
- agents: `/<prefix>/agents/<agent-url-key>`
- projects: `/<prefix>/projects/<project-url-key>`
- approvals: `/<prefix>/messenger/approvals/<approval-id>`
- runs: `/<prefix>/agents/<agent-url-key-or-id>/runs/<run-id>`

Example:

```md
## Update

Plan updated and ready for review.

- Plan: [PAP-142 plan](/PAP/issues/PAP-142#document-plan)
- Depends on: [PAP-224](/PAP/issues/PAP-224)
- Approval: [ca6ba09d](/PAP/messenger/approvals/ca6ba09d-b558-4a53-a552-e7ef87e54a1b)
```

## Discovery

When you are unsure which control plane commands are supported in this runtime, use:

```bash
control-plane agent capabilities --json
```

For the human-readable command catalog, read `references/cli-reference.md`.
For API debugging and compatibility investigations only, read `references/api-reference.md`.
