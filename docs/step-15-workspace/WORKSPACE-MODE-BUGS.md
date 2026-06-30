# Workspace Mode Implementation Bugs

Status: resolved in working tree
Date: 2026-06-30
Source: `docs/step-15-workspace/WORKSPACE-MODES.md`

## Bugs

1. Project with no project workspace currently falls back to organization workspace for every mode. `isolated_workspace` should create an issue-scoped managed `local_fs` execution workspace, and `operator_branch` should fail preflight.
2. Project workspace with no `cwd` and no `repoUrl` currently falls back to organization workspace for every mode. `isolated_workspace` should create an issue-scoped managed `local_fs` execution workspace, and `operator_branch` should fail preflight.
3. Shared workspace issue artifacts are written under the project cwd. They should live under the organization artifacts root so task artifacts do not pollute the project working tree.
4. Explicit configured `cwd` paths that do not exist or are inaccessible can be created implicitly. They should fail preflight instead of silently creating or falling back.
5. Existing execution workspace reuse lacks validation before reuse. It should validate cwd, provider, Git worktree reality, branch, and source workspace metadata before continuing.
6. `operator_branch` does not fail early for no project workspace / no `cwd` + no `repoUrl`; it currently inherits shared fallback behavior.
7. Projectless organization workspace fallback has no write lease because it has no execution workspace id.
8. Shared organization fallback without a persisted execution workspace has unclear lease scope; projectless runs in particular can write the same org cwd concurrently.
9. `_organization_workspace_fallback()` returns `strategyType=organization_workspace`, but the shared strategy type constants do not include `organization_workspace`.

## Priority

Fix first:

- mode-specific preflight fallback for missing project workspace and missing cwd/repoUrl
- artifacts path separation from execution cwd
- organization fallback lease scope
- strategy type contract consistency

Then harden:

- explicit invalid cwd failure
- existing execution workspace validation

## Resolution Notes

Implemented in the working tree:

- Mode-specific preflight behavior for missing project workspace and missing cwd/repoUrl.
- `isolated_workspace` now keeps issue-scoped local_fs execution semantics when Git/project workspace source is unavailable.
- `operator_branch` now fails preflight when no Git-capable project workspace source exists.
- Shared issue artifacts are placed under organization issue artifacts instead of project cwd.
- Shared generated-file capture scans only the current issue artifacts directory, not the entire organization artifacts root.
- Explicit configured project workspace `cwd` must exist and be a directory.
- Existing Git worktree execution workspace records are validated before reuse.
- Organization fallback workspaces expose a `leaseKey` so projectless/org fallback runs can be serialized.
- `organization_workspace` is now part of the shared execution workspace strategy type contract.
