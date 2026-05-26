# Step 9 Approval Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Step 9 `approval management` so approvals can be created, resolved, revision-requested, resubmitted, redacted safely in API responses, and drive linked blocked-issue recovery while preserving Step 5 ownership semantics, Step 7 board/organization boundaries, and Step 8 issue workflow discipline.

**Architecture:** Implement bottom-up from shared contract and query helpers to service-layer approval workflow orchestration, then expose the behavior through `server/routes/approvals.py`, and finally lock it down with contract and workflow tests. Keep approval management isolated from chat/storage/plugin execution surfaces.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, pytest, shared typed dict validators in `packages/shared`, async DB queries in `packages/database/queries`, PowerShell on Windows.

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `packages/shared/types/approval.py` | Modify | Add any Step 9 payload / response gaps needed by create, resolve, revision request, resubmit, linked issues |
| `packages/shared/validators/approval.py` | Modify | Validate first-batch create / resolve / resubmit payloads; reject unsupported fields |
| `packages/database/queries/approvals.py` | Modify | Add create / resolve / filtered list helpers |
| `packages/database/queries/issues.py` | Reuse/Modify | Support linked blocked-issue recovery if needed |
| `packages/database/queries/activity_log.py` | Reuse | Continue centralized activity insert path |
| `server/services/approvals.py` | Modify | Add approval create / resolve / revision / resubmit workflow entrypoints |
| `server/routes/approvals.py` | Modify | Expose Step 9 endpoints |
| `tests/contract/test_step9_approval_management.py` | Create | Contract-level API tests for payloads, status, decision note, redaction, linked issue recovery |
| `tests/workflows/test_step9_approval_workflow.py` | Create or modify | Workflow/state-transition tests for approve/reject/revision/resubmit and issue recovery |

## Verification Commands

Run after every task:

```powershell
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
```

Run before closing the step:

```powershell
uv run pytest tests/contract/test_step9_approval_management.py -q
uv run pytest tests/workflows/test_step9_approval_workflow.py -q
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
```

---

### Task 1: Freeze shared approval contract gaps

**Files:**
- Modify: `packages/shared/types/approval.py`
- Modify: `packages/shared/validators/approval.py`
- Test: `tests/contract/test_step9_approval_management.py`

- [ ] **Step 1: Write failing contract tests for payload validation**

Add tests that assert:

- `POST /api/orgs/{orgId}/approvals` accepts only the Step 9 first-batch writable fields
- resolve/revision/resubmit payloads reject unsupported fields with `422`
- decision note payload types are enforced
- linked issue ids payload is validated as a string list

- [ ] **Step 2: Run only the new validation tests and confirm failure**

Run:

```powershell
uv run pytest tests/contract/test_step9_approval_management.py -k "invalid or unsupported" -q
```

Expected: fail because Step 9 validators and/or types do not yet reject unsupported fields or lack first-batch payload shapes.

- [ ] **Step 3: Implement the shared contract additions**

In `packages/shared/types/approval.py`, add or finalize the first-batch typed payloads needed for:

- `CreateApprovalPayload`
- `ResolveApprovalPayload`
- `RequestApprovalRevisionPayload`
- `ResubmitApprovalPayload`

In `packages/shared/validators/approval.py`, implement validators that:

- allow only the Step 9 first-batch writable fields
- reject unknown fields instead of silently dropping them
- enforce approval type and state-related payload expectations
- enforce `decisionNote` as the correct type

- [ ] **Step 4: Re-run contract tests**

Run:

```powershell
uv run pytest tests/contract/test_step9_approval_management.py -k "invalid or unsupported" -q
```

Expected: new validation tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/shared/types/approval.py packages/shared/validators/approval.py tests/contract/test_step9_approval_management.py
git commit -m "feat: freeze step 9 approval payload validators"
```

---

### Task 2: Add query-layer support for create, resolve, and linked issue recovery

**Files:**
- Modify: `packages/database/queries/approvals.py`
- Modify: `packages/database/queries/issues.py`
- Test: `tests/contract/test_step4_database.py`

- [ ] **Step 1: Write failing query tests**

Add tests covering:

- creating an approval row
- resolving an approval row and refreshing `updated_at` / `decided_at`
- listing approvals with status filter
- recovering a blocked linked issue to the correct target status

- [ ] **Step 2: Run the Step 4 DB tests and confirm failure**

Run:

```powershell
uv run pytest tests/contract/test_step4_database.py -k "approval" -q
```

Expected: fail because the new query helpers or linked-issue update behavior do not yet exist.

- [ ] **Step 3: Implement the query helpers**

In `packages/database/queries/approvals.py`, add helpers for:

- create approval
- update approval status / decision fields
- get approval detail including linked issues if needed

In `packages/database/queries/issues.py`, add or reuse helpers for:

- recovering blocked linked issues to `todo` / `in_progress`

Rules:

- keep all DB field names snake_case
- do not shape HTTP responses in the query layer
- linked issue recovery remains a query concern only after normalized workflow decisions are computed in service

- [ ] **Step 4: Re-run the DB query tests**

Run:

```powershell
uv run pytest tests/contract/test_step4_database.py -k "approval" -q
```

Expected: query tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/database/queries/approvals.py packages/database/queries/issues.py tests/contract/test_step4_database.py
git commit -m "feat: add step 9 approval query helpers"
```

---

### Task 3: Implement approval service create/resolve workflow

**Files:**
- Modify: `server/services/approvals.py`
- Test: `tests/workflows/test_step9_approval_workflow.py`

- [ ] **Step 1: Write failing workflow tests**

Add workflow tests that assert:

- create approval emits `approval.created`
- approve emits `approval.approved`
- reject emits `approval.rejected`
- request revision emits `approval.revision_requested`
- resubmit emits `approval.resubmitted`
- detail payload continues to use redacted values

- [ ] **Step 2: Run the workflow tests and confirm failure**

Run:

```powershell
uv run pytest tests/workflows/test_step9_approval_workflow.py -k "create or approve or reject or revision or resubmit" -q
```

Expected: fail because approval service entrypoints do not yet orchestrate the new behavior.

- [ ] **Step 3: Implement service entrypoints**

In `server/services/approvals.py`, add methods equivalent to:

```python
async def create_approval(...)
async def approve_approval(...)
async def reject_approval(...)
async def request_revision(...)
async def resubmit_approval(...)
```

Service responsibilities:

- map camelCase payloads to DB columns
- call centralized query helpers
- emit `activity_log` via `insert_activity_log`
- keep approval resolution and any linked issue recovery inside the request-scoped transaction boundary
- preserve payload redaction at read/output time

- [ ] **Step 4: Re-run the workflow tests**

Run:

```powershell
uv run pytest tests/workflows/test_step9_approval_workflow.py -k "create or approve or reject or revision or resubmit" -q
```

Expected: workflow tests pass.

- [ ] **Step 5: Commit**

```powershell
git add server/services/approvals.py tests/workflows/test_step9_approval_workflow.py
git commit -m "feat: add step 9 approval workflows"
```

---

### Task 4: Implement blocked-issue recovery and approval side effects

**Files:**
- Modify: `server/services/approvals.py`
- Test: `tests/workflows/test_step9_approval_workflow.py`

- [ ] **Step 1: Write failing workflow tests for linked issue recovery**

Add tests for:

- approve on linked blocked issue with assignee recovers to `in_progress`
- approve on linked blocked issue without assignee recovers to `todo`
- wakeup-related activity action names are preserved where Step 9 chooses to record them

- [ ] **Step 2: Run only the recovery tests and confirm failure**

Run:

```powershell
uv run pytest tests/workflows/test_step9_approval_workflow.py -k "linked or recovery or wakeup" -q
```

Expected: fail because the linked issue recovery workflow is not yet implemented.

- [ ] **Step 3: Implement the recovery workflow**

Add centralized helpers in `server/services/approvals.py` or a nearby workflow helper that:

- determines whether an approval has linked blocked issues
- restores the correct target issue status based on assignee presence
- records the required activity names without inventing new ones

- [ ] **Step 4: Re-run the recovery tests**

Run:

```powershell
uv run pytest tests/workflows/test_step9_approval_workflow.py -k "linked or recovery or wakeup" -q
```

Expected: recovery and side-effect tests pass.

- [ ] **Step 5: Commit**

```powershell
git add server/services/approvals.py tests/workflows/test_step9_approval_workflow.py
git commit -m "feat: add step 9 linked issue recovery"
```

---

### Task 5: Expose the Step 9 HTTP surface

**Files:**
- Modify: `server/routes/approvals.py`
- Test: `tests/contract/test_step9_approval_management.py`

- [ ] **Step 1: Write failing contract tests for routes**

Add end-to-end contract tests covering:

- `POST /api/orgs/{orgId}/approvals`
- `POST /api/approvals/{id}/approve`
- `POST /api/approvals/{id}/reject`
- request revision / resubmit route(s)
- ownership rejection, missing board identity, invalid payload branches

- [ ] **Step 2: Run the Step 9 contract file and confirm failure**

Run:

```powershell
uv run pytest tests/contract/test_step9_approval_management.py -q
```

Expected: fail because the new routes or workflow route wiring do not yet exist.

- [ ] **Step 3: Implement the route layer**

In `server/routes/approvals.py`, wire:

- existing Step 6 list/detail reads
- new create/approve/reject/revision/resubmit endpoints
- shared validators
- ownership / board / actor dependencies as required by the specific action

Rules:

- route layer does not write activity rows directly
- route layer does not open sessions directly
- route layer does not silently ignore unsupported payload fields

- [ ] **Step 4: Re-run Step 9 contract tests**

Run:

```powershell
uv run pytest tests/contract/test_step9_approval_management.py -q
```

Expected: route contract tests pass.

- [ ] **Step 5: Commit**

```powershell
git add server/routes/approvals.py tests/contract/test_step9_approval_management.py
git commit -m "feat: add step 9 approval routes"
```

---

### Task 6: Lock down regressions and final coverage

**Files:**
- Modify: `tests/contract/test_step9_approval_management.py`
- Modify: `tests/workflows/test_step9_approval_workflow.py`

- [ ] **Step 1: Extend tests for final regression cases**

Add final assertions for:

- approval detail redaction remains intact after create/resolve
- linked blocked issue recovery does not regress Step 8 status semantics
- activity names match the Step 9 frozen list exactly
- no Step 9 behavior regresses Step 6 approval list/detail reads

- [ ] **Step 2: Run full Step 9 and regression verification**

Run:

```powershell
uv run pytest tests/contract/test_step9_approval_management.py -q
uv run pytest tests/workflows/test_step9_approval_workflow.py -q
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
```

Expected: all Step 9 tests and existing contract/workflow suites pass.

- [ ] **Step 3: Commit**

```powershell
git add tests/contract/test_step9_approval_management.py tests/workflows/test_step9_approval_workflow.py
git commit -m "test: finalize step 9 approval coverage"
```
