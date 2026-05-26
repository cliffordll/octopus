# Step 8 Issue Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Step 8 `issue management` so issues can be created, updated, commented on, reopened, transitioned through the first-batch status workflow, and queried with first-batch associations and filters, while preserving Step 5 ownership semantics and Step 7 transaction / activity-log discipline.

**Architecture:** Implement bottom-up from shared contract and query helpers to service-layer workflow orchestration, then expose the behavior through `server/routes/issues.py`, and finally lock it down with contract and workflow tests. Keep issue management isolated from Step 9 approvals and Step 10/11 project-runtime execution surfaces.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, pytest, shared typed dict validators in `packages/shared`, async DB queries in `packages/database/queries`, PowerShell on Windows.

---

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `packages/shared/types/issue.py` | Modify | Add any Step 8 payload / response gaps needed by create, update, comment, review decision, filtering |
| `packages/shared/validators/issue.py` | Modify | Validate first-batch create / update / review decision payloads; reject unsupported fields |
| `packages/database/queries/issues.py` | Modify | Add create / update / filtered list / association read helpers |
| `packages/database/queries/issue_comments.py` | Modify | Add comment list / insert helpers |
| `packages/database/queries/activity_log.py` | Reuse | Continue centralized activity insert path |
| `server/services/issues.py` | Modify | Add issue create / update / comment / review workflow entrypoints |
| `server/routes/issues.py` | Modify | Expose Step 8 endpoints and query params |
| `tests/contract/test_step8_issue_management.py` | Create | Contract-level API tests for payloads, status, comments, filtering, associations |
| `tests/workflows/test_step8_issue_workflow.py` | Create or modify | Workflow/state-transition tests for review decision, reopen, activity timing |
| `docs/step-08/IMPLEMENTATION-NOTES.md` | Optional | implementation notes if needed |

## Verification Commands

Run after every task:

```powershell
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
```

Run before closing the step:

```powershell
uv run pytest tests/contract/test_step8_issue_management.py -q
uv run pytest tests/workflows/test_step8_issue_workflow.py -q
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
```

---

### Task 1: Freeze shared issue contract gaps

**Files:**
- Modify: `packages/shared/types/issue.py`
- Modify: `packages/shared/validators/issue.py`
- Test: `tests/contract/test_step8_issue_management.py`

- [ ] **Step 1: Write failing contract tests for payload validation**

Add tests that assert:

- `POST /api/issues` accepts only the Step 8 first-batch writable fields
- `PATCH /api/issues/{issueId}` rejects unsupported fields with `422`
- review decision payload rejects unsupported `decision` values
- comment payload requires the minimum text/body field

Representative assertions:

```python
assert response.status_code == 422
assert "unsupported" in response.json()["detail"]
```

- [ ] **Step 2: Run only the new validation tests and confirm failure**

Run:

```powershell
uv run pytest tests/contract/test_step8_issue_management.py -k "invalid or unsupported" -q
```

Expected: fail because Step 8 validators and/or types do not yet exist or do not reject unsupported fields.

- [ ] **Step 3: Implement the shared contract additions**

In `packages/shared/types/issue.py`, add or finalize the first-batch typed payloads needed for:

- `CreateIssuePayload`
- `UpdateIssuePayload`
- `CreateIssueCommentPayload`
- `RecordIssueReviewDecisionPayload`

In `packages/shared/validators/issue.py`, implement validators that:

- allow only the Step 8 first-batch writable fields
- reject unknown fields instead of silently dropping them
- enforce the Step 8 status whitelist
- enforce the Step 8 review decision whitelist
- enforce reopen as an explicit boolean flag if present

- [ ] **Step 4: Re-run contract tests**

Run:

```powershell
uv run pytest tests/contract/test_step8_issue_management.py -k "invalid or unsupported" -q
```

Expected: new validation tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/shared/types/issue.py packages/shared/validators/issue.py tests/contract/test_step8_issue_management.py
git commit -m "feat: freeze step 8 issue payload validators"
```

---

### Task 2: Add query-layer support for write paths, comments, filters, and associations

**Files:**
- Modify: `packages/database/queries/issues.py`
- Modify: `packages/database/queries/issue_comments.py`
- Test: `tests/contract/test_step4_database.py`

- [ ] **Step 1: Write failing query tests**

Add tests covering:

- creating an issue row
- updating an issue row and refreshing `updated_at`
- listing issues with `status` filter
- listing issues with `project_id` / `goal_id` / `agent_id` / `origin` filters
- inserting an issue comment
- listing comments ordered consistently

Representative shape:

```python
rows = await list_org_issues(session, org_id="org-1", filters={"status": "todo"})
assert [row.id for row in rows] == ["issue-1"]
```

- [ ] **Step 2: Run the Step 4 DB tests and confirm failure**

Run:

```powershell
uv run pytest tests/contract/test_step4_database.py -k "issue or comment" -q
```

Expected: fail because the new query helpers or filter behavior do not yet exist.

- [ ] **Step 3: Implement the query helpers**

In `packages/database/queries/issues.py`, add helpers for:

- create issue
- update issue
- list issues with first-batch filters
- get issue detail with first-batch association fields

In `packages/database/queries/issue_comments.py`, add helpers for:

- insert comment
- list comments for one issue ordered by creation time

Rules:

- keep all DB field names snake_case
- do not shape HTTP responses in the query layer
- keep filter parsing in route/service, query only consumes normalized filter values

- [ ] **Step 4: Re-run the DB query tests**

Run:

```powershell
uv run pytest tests/contract/test_step4_database.py -k "issue or comment" -q
```

Expected: query tests pass.

- [ ] **Step 5: Commit**

```powershell
git add packages/database/queries/issues.py packages/database/queries/issue_comments.py tests/contract/test_step4_database.py
git commit -m "feat: add step 8 issue query helpers"
```

---

### Task 3: Implement issue service create/update/comment workflow

**Files:**
- Modify: `server/services/issues.py`
- Test: `tests/workflows/test_step8_issue_workflow.py`

- [ ] **Step 1: Write failing workflow tests**

Add workflow tests that assert:

- create issue emits `issue.created`
- patching mutable fields emits `issue.updated`
- adding a comment emits `issue.comment_added`
- empty/no-op update does not emit a misleading activity record
- unsupported fields never reach the service because validators reject them

Representative assertions:

```python
assert activity.action == "issue.created"
assert created.status == "todo"
```

- [ ] **Step 2: Run the workflow tests and confirm failure**

Run:

```powershell
uv run pytest tests/workflows/test_step8_issue_workflow.py -k "create or update or comment" -q
```

Expected: fail because service entrypoints do not yet orchestrate the new behavior.

- [ ] **Step 3: Implement service entrypoints**

In `server/services/issues.py`, add methods equivalent to:

```python
async def create_issue(...)
async def update_issue(...)
async def add_comment(...)
```

Service responsibilities:

- map camelCase payloads to DB columns
- call centralized query helpers
- emit `activity_log` via `insert_activity_log`
- return shared-contract-shaped issue/detail objects
- keep create/update/comment inside the request-scoped Step 7 transaction boundary

- [ ] **Step 4: Re-run the workflow tests**

Run:

```powershell
uv run pytest tests/workflows/test_step8_issue_workflow.py -k "create or update or comment" -q
```

Expected: create/update/comment workflow tests pass.

- [ ] **Step 5: Commit**

```powershell
git add server/services/issues.py tests/workflows/test_step8_issue_workflow.py
git commit -m "feat: add step 8 issue write workflows"
```

---

### Task 4: Implement status transitions, review decisions, and reopen semantics

**Files:**
- Modify: `server/services/issues.py`
- Test: `tests/workflows/test_step8_issue_workflow.py`

- [ ] **Step 1: Write failing workflow tests for state transitions**

Add tests for:

- `todo -> in_progress`
- `in_progress -> in_review`
- `in_review + approve -> done`
- `in_review + request_changes -> in_progress`
- `blocked + blocked -> blocked`
- `needs_followup` records the decision without directly changing status
- closed issue `reopen=true` and no explicit status returns to `todo`
- review decision outside `in_review` / `blocked` is rejected

- [ ] **Step 2: Run only the transition tests and confirm failure**

Run:

```powershell
uv run pytest tests/workflows/test_step8_issue_workflow.py -k "review or reopen or transition" -q
```

Expected: fail because the state machine and decision mapping are not yet implemented.

- [ ] **Step 3: Implement the state machine**

Add a centralized transition helper in `server/services/issues.py` or a nearby workflow helper that:

- enforces the Step 8 status whitelist
- enforces allowed review-decision preconditions
- applies the fixed decision-to-status mapping
- applies reopen semantics before final persistence
- emits `issue.review_decision_recorded` and `issue.human_intervention_required` at the correct points

- [ ] **Step 4: Re-run the transition tests**

Run:

```powershell
uv run pytest tests/workflows/test_step8_issue_workflow.py -k "review or reopen or transition" -q
```

Expected: transition and review-decision tests pass.

- [ ] **Step 5: Commit**

```powershell
git add server/services/issues.py tests/workflows/test_step8_issue_workflow.py
git commit -m "feat: add step 8 issue status workflow"
```

---

### Task 5: Expose the Step 8 HTTP surface

**Files:**
- Modify: `server/routes/issues.py`
- Test: `tests/contract/test_step8_issue_management.py`

- [ ] **Step 1: Write failing contract tests for routes**

Add end-to-end contract tests covering:

- `GET /api/issues` with first-batch filters
- `POST /api/issues`
- `PATCH /api/issues/{issueId}`
- comment list/create endpoints
- review decision endpoint or sub-action route
- organization ownership and actor-context rejection branches

- [ ] **Step 2: Run the Step 8 contract file and confirm failure**

Run:

```powershell
uv run pytest tests/contract/test_step8_issue_management.py -q
```

Expected: fail because the new routes or query parameter wiring do not yet exist.

- [ ] **Step 3: Implement the route layer**

In `server/routes/issues.py`, wire:

- existing Step 6 list/detail reads
- new create/update/comment/review endpoints
- filter query params normalized before reaching the query layer
- shared validators
- ownership / board / actor dependencies as required by the specific action

Rules:

- route layer does not write activity rows directly
- route layer does not open sessions directly
- route layer does not silently ignore unsupported payload fields

- [ ] **Step 4: Re-run Step 8 contract tests**

Run:

```powershell
uv run pytest tests/contract/test_step8_issue_management.py -q
```

Expected: route contract tests pass.

- [ ] **Step 5: Commit**

```powershell
git add server/routes/issues.py tests/contract/test_step8_issue_management.py
git commit -m "feat: add step 8 issue management routes"
```

---

### Task 6: Lock down associations, demos, and regression coverage

**Files:**
- Modify: `tests/contract/test_step8_issue_management.py`
- Modify: `tests/workflows/test_step8_issue_workflow.py`
- Optional: `docs/step-08/IMPLEMENTATION-NOTES.md`

- [ ] **Step 1: Extend tests for association reads and regression cases**

Add final assertions for:

- issue detail returns `project / goal / agent / origin` with stable null behavior
- filtered list behavior remains consistent when association fields are absent
- activity names match the Step 8 frozen list exactly
- no Step 8 behavior regresses Step 6 issue list/detail reads

- [ ] **Step 2: Run full Step 8 and regression verification**

Run:

```powershell
uv run pytest tests/contract/test_step8_issue_management.py -q
uv run pytest tests/workflows/test_step8_issue_workflow.py -q
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
```

Expected: all Step 8 tests and existing contract/workflow suites pass.

- [ ] **Step 3: Document any execution notes if needed**

If implementation needs to capture step-specific caveats, add a short note file in `docs/step-08/IMPLEMENTATION-NOTES.md` describing:

- final route shapes
- final filter parameter names
- any intentionally deferred association/detail expansions

- [ ] **Step 4: Commit**

```powershell
git add tests/contract/test_step8_issue_management.py tests/workflows/test_step8_issue_workflow.py docs/step-08/IMPLEMENTATION-NOTES.md
git commit -m "test: finalize step 8 issue management coverage"
```
