# Parent/Child Concurrent Execution Implementation Plan

## Objective

Allow a parent Run and its child Runs to execute concurrently while the parent
Issue permanently retains authority over its children. Run execution, Issue
workflow state, Adapter lifecycle, database transactions, and workspace access
must remain separate concerns.

This is a clean-development contract. Existing task data may be discarded and
the database rebuilt. New code does not preserve the old parent-yield protocol.

## Core contract

```text
parent Run creates the complete initial child set atomically
-> the transaction commits
-> child wakeups become dispatchable immediately
-> parent and child Runs may execute concurrently
-> comments are durable parent instructions
-> failed children retry on the same Issue before replacement
-> one parent continuation is created when the effective child set settles
-> the parent produces the final result
```

The parent does not need to yield, stop, or release its authority before child
Runs start. A parent Run may finish naturally when its current turn is complete;
later comments and child events can create a new parent Run.

## State contract

- Issue status remains `backlog`, `todo`, `in_progress`, `in_review`, `blocked`,
  `done`, or `cancelled`.
- No Issue execution-stage field is added.
- New Runs use only `queued`, `running`, `succeeded`, `failed`, `timed_out`, or
  `cancelled`.
- `waiting_for_children`, `yield_requested_at`, `deferred_parent_yield`, and the
  `yield-children` execution protocol are removed.
- The same Issue may have only one queued/running Run. A parent Run and Runs for
  different child Issues may overlap.

## Module boundaries

```text
Route / Scheduler
        -> Coordinator
        -> Domain Service / Policy
        -> Repository / Query
        -> Database
```

- `RunExecutionService` owns Adapter start, observation, lease renewal, graceful
  stop, and evidence collection.
- `RunFinalizationService` owns Run terminal CAS and idempotent terminal effects.
- `RunRecoveryService` owns expired leases, missing processes, and incomplete
  terminal effects.
- `ChildDispatchCoordinator` owns atomic initial child creation and after-commit
  wakeup materialization.
- `ParentCommandCoordinator` owns durable comment commands, wakeup coalescing,
  and parent control authorization.
- `ChildRecoveryCoordinator` owns retry-before-replacement and retirement.
- `ParentContinuationCoordinator` owns effective-child settlement and exactly-once
  parent continuation.
- `DatabaseWriteCoordinator` contains SQLite/PostgreSQL write coordination.
- `WorkspaceAccessManager` contains workspace-mode concurrency policy.
- Adapter-specific instruction delivery is hidden behind
  `AdapterInstructionChannel`; CLI Adapters initially use a coalesced follow-up
  Run rather than unsupported live prompt injection.

Routes validate and delegate. Database queries provide atomic primitives and do
not contain lifecycle branching. Parent/child workflow policy must not be added
to the `HeartbeatService` monolith.

## Encapsulation and inheritance rules

Inheritance is required at stable infrastructure extension points:

```text
AdapterInstructionChannel (ABC)
  -> DeferredInstructionChannel
  -> LiveInstructionChannel

WorkspaceAccessStrategy (ABC)
  -> SharedWorkspaceAccessStrategy
  -> WorktreeWorkspaceAccessStrategy
  -> IsolatedWorkspaceAccessStrategy

DatabaseWriteStrategy (ABC)
  -> SQLiteWriteStrategy
  -> PostgreSQLWriteStrategy
```

Coordinators receive these abstractions through construction and compose domain
services; they do not select providers with scattered `if sqlite` or
`if workspace_type` branches. `RunExecutionService`, `RunFinalizationService`,
and `RunRecoveryService` remain separate services because their ownership is
different; they share small value objects and protocols rather than inheriting
from one lifecycle god class. Every concrete strategy and coordinator must be
independently unit-testable.

## Delivery batches

### Batch 1: concurrent dispatch foundation

- Remove the forced parent-yield and deferred-child-dispatch protocol.
- Remove `waiting_for_children` from the new Run contract.
- Extract the three Run services without changing their ownership boundaries.
- Add `ChildDispatchCoordinator`.
- Atomically create the complete initial child set; dispatch wakeups only after
  commit, but never wait for the parent Run to finish.
- Reconcile missing child wakeups after a crash between child commit and wakeup
  materialization.

Acceptance: a running parent creates three children and all eligible child Runs
can start while the parent Run remains running. Repeating the initial creation
returns the persisted child set and never creates a partial or duplicate set.

### Batch 2: parent commands and child recovery

- Keep caller-supplied comment request IDs and the database uniqueness boundary.
- Add `ParentCommandCoordinator`; comments persist before wakeup creation.
- Coalesce instructions when the same Issue already has queued/running work.
- Let the parent stop, cancel, guide, retry, or replace its children without a
  workspace write lease for control-plane operations.
- Add `ChildRecoveryCoordinator`: retry the same child Issue first; replacement
  creates a new Issue, records its predecessor, and retires without deleting the
  old Issue.
- Add `ParentContinuationCoordinator` so concurrent final-child settlement
  creates one continuation for the current effective child set.

Acceptance: transport replay creates one comment and one wakeup; a parent can
control children while they run; retries reuse the child Issue; replacement has
a distinct Issue ID; and the parent continuation is exactly-once.

### Batch 3: closeout, UI, and full verification

- Complete `RunExecutionService`, `RunFinalizationService`, and
  `RunRecoveryService` separation.
- Ensure an authoritative Issue closeout is not overwritten by a later Adapter
  timeout; process loss before closeout remains a failed/timed-out Run.
- Remove remaining `waiting_for_children` API, shared-type, UI, and test paths.
- Keep shared-workspace writes exclusive; independent/worktree workspaces may
  write concurrently. Control-plane operations remain concurrent.
- Rebuild the development database and verify SQLite, PostgreSQL concurrency,
  restart recovery, and real Codex/OpenCode Runtime scenarios.

Acceptance: Issue, Run, Adapter, database, and workspace state converge after
success, timeout, cancellation, process loss, server restart, and concurrent
child completion. The UI shows only real queued/running executions as active.

## Recovery rules for newly created data

- A child transaction committed without wakeups is reconciled by child ID; the
  children are not recreated.
- A comment committed before an HTTP timeout is replayed by request ID.
- A lost Adapter causes the old Run to close as process-lost; a recovery attempt
  uses a new Run related to the same Issue.
- Concurrent Dispatcher/Recovery workers use claim CAS and execution leases.
- Concurrent final-child events use a database uniqueness boundary for one
  parent continuation.
- A parent cannot become `done` while effective children are active unless the
  remaining work is explicitly cancelled.
- Blocked children wake the parent for a decision; they cannot leave the parent
  in a permanent synthetic waiting Run.

## Validation and commits

Each batch receives focused unit/contract/workflow tests, one verification pass,
and one coherent commit. The final batch adds clean-database migration checks,
PostgreSQL concurrency coverage, and real Runtime E2E. Do not rerun an already
passing batch suite solely because a commit is about to be created. Do not push
without explicit user approval.
