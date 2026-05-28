# Organization Skills Workflow

Use this reference when a board user, CEO, or manager asks you to discover, import, inspect, or enable organization skills.

This workflow is now **CLI-first** for the bundled `control-plane` skill.

For a skill that belongs only to the running agent, do not use organization import or scan commands. Use:

```bash
control-plane agent skills create "$CONTROL_PLANE_AGENT_ID" --name "<name>" --description "<description>" --enable --json
```

Agent-private skill creation writes under `AGENT_HOME/skills` and does not require organization skill mutation permission.

## Canonical Model

1. import or scan the skill into the organization library
2. inspect the imported skill if needed
3. enable the desired skills on the target agent

## Core CLI Surface

```bash
control-plane skill list --org-id "$CONTROL_PLANE_ORG_ID" --json
control-plane skill get "<skill-id>" --org-id "$CONTROL_PLANE_ORG_ID" --json
control-plane skill file "<skill-id>" --org-id "$CONTROL_PLANE_ORG_ID" --path SKILL.md --json
control-plane skill import --org-id "$CONTROL_PLANE_ORG_ID" --source "<source>" --json
control-plane skill scan-local --org-id "$CONTROL_PLANE_ORG_ID" --roots "<csv>" --json
control-plane skill scan-projects --org-id "$CONTROL_PLANE_ORG_ID" --project-ids "<csv>" --workspace-ids "<csv>" --json
control-plane agent skills enable "<agent-id>" "<selection-ref>" --json
control-plane agent skills sync "<agent-id>" --desired-skills "<csv>" --json
```

Defaults:

- `--org-id` can come from `CONTROL_PLANE_ORG_ID`
- mutating commands attach `CONTROL_PLANE_RUN_ID` automatically when present

## Source Types

Use these sources in priority order:

| Source format | Example | When to use |
| --- | --- | --- |
| `skills.sh` URL | `https://skills.sh/google-labs-code/stitch-skills/design-md` | Preferred when the user gives a managed registry URL |
| key-style source | `google-labs-code/stitch-skills/design-md` | Shorthand for the same managed skill |
| GitHub URL | `https://github.com/vercel-labs/agent-browser` | When the skill is on GitHub but not on `skills.sh` |
| local path | `/abs/path/to/skill-dir` | Local dev or testing only |

If the user gives a `skills.sh` URL, keep it as `skills.sh` or key-style. Do not rewrite it to a GitHub URL.

## Import Examples

Preferred managed import:

```bash
control-plane skill import \
  --org-id "$CONTROL_PLANE_ORG_ID" \
  --source "https://skills.sh/google-labs-code/stitch-skills/design-md" \
  --json
```

Equivalent key-style import:

```bash
control-plane skill import \
  --org-id "$CONTROL_PLANE_ORG_ID" \
  --source "google-labs-code/stitch-skills/design-md" \
  --json
```

GitHub import:

```bash
control-plane skill import \
  --org-id "$CONTROL_PLANE_ORG_ID" \
  --source "https://github.com/vercel-labs/agent-browser" \
  --json
```

Local skill scan:

```bash
control-plane skill scan-local \
  --org-id "$CONTROL_PLANE_ORG_ID" \
  --roots "/abs/path/to/.agents,/abs/path/to/other-skill-root" \
  --json
```

Shared workspace scan:

```bash
control-plane skill scan-projects \
  --org-id "$CONTROL_PLANE_ORG_ID" \
  --project-ids "<project-id-1>,<project-id-2>" \
  --json
```

Notes:

- control plane now uses one fixed org workspace root at `~/.control-plane/instances/<instance>/organizations/<org-id>/workspaces`.
- `scan-projects` should be treated as a compatibility command that scans the shared org workspace plus any legacy project workspace records that still exist.
- The org `Resources` catalog is the canonical place to register shared repos, docs, URLs, and connector objects for agents.
- Workspaces remains the disk-backed shared file surface for plans, notes, and skill packages.

## Inspect Imported Skills

List skills:

```bash
control-plane skill list --org-id "$CONTROL_PLANE_ORG_ID" --json
```

Read one skill:

```bash
control-plane skill get "<skill-id>" --org-id "$CONTROL_PLANE_ORG_ID" --json
```

Read `SKILL.md` or another file from the package:

```bash
control-plane skill file "<skill-id>" --org-id "$CONTROL_PLANE_ORG_ID" --path SKILL.md --json
control-plane skill file "<skill-id>" --org-id "$CONTROL_PLANE_ORG_ID" --path references/notes.md --json
```

## Enable Skills On An Existing Agent

`desiredSkills` accepts:

- exact organization skill key
- exact organization skill id
- exact slug when it is unique in the organization

```bash
control-plane agent skills enable \
  "<agent-id>" \
  "vercel-labs/agent-browser/agent-browser" \
  --json
```

For multiple skills:

```bash
control-plane agent skills enable \
  "<agent-id>" \
  "agent-browser" "design-md" \
  --json
```

`control-plane agent skills enable` is additive and preserves existing enabled
selections. Use `control-plane agent skills sync --desired-skills` only when replacing
the full optional enabled-skill set intentionally.

## Permission Model

- organization skill reads: any same-organization actor
- organization skill mutations: board, CEO, or an agent with effective `agents:create`
- agent skill enable/sync: same permission model as updating that agent

## Notes

- Built-in control-plane skills live in the organization library and are always loaded for agent runs.
- New organizations also seed optional community preset skills into the organization library. They stay organization-managed and default-off for agents.
- If a skill reference is missing or ambiguous, control plane returns `422`.
- Prefer linking back to the relevant issue, approval, and agent when commenting about skill changes.
- This document only covers library import/inspect/enable/sync.
- Hire and create flows now live on the CLI-first `create-agent` path.
