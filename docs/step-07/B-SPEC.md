# Step 7 Organization Management Design Spec

**Author:** implementation owner
**Date:** 2026-05-26
**Status:** Approved for implementation

## 1. Motivation

Step 6 stabilized organization read API (list + detail). Step 7 must turn organizations from a read-only resource into a manageable one by introducing the first write endpoint and the minimal audit trail behind it. Step 8 (issue management) and Step 9 (approval management) both assume Step 7's organization mutation surface is stable.

## 2. Contract Sources (priority order)

1. `docs/step-07/A-CONSTRAINTS.md` — frozen implementation contract (§3 range, §6.2 fields, §7.4 error codes, §8 layer hard constraints, §12 test assertions)
2. `upstream-reference/rudder/server/src/routes/orgs.ts` line 584-624 (`PATCH /:orgId`) — behavioral semantics reference
3. `upstream-reference/rudder/server/src/services/orgs.ts` `update()` — transaction boundary reference
4. `docs/DESIGN.md` §3.3 organization boundary, §7.2.7 actor context boundary, §8 layering
5. `docs/FEATURE.md` §7 Step 7 — acceptance demos

Implementation may consult source 2 and 3 to resolve semantic ambiguity in source 1, but must not derive new field names, action names, or error semantics independently of the frozen constraints.

## 3. Scope

### In Scope

- Add `PATCH /api/orgs/{orgId}` — first write endpoint for organizations
- Reuse `GET /api/orgs` and `GET /api/orgs/{orgId}` from Step 6 unchanged
- Emit one `activity_log` row per successful, non-empty update
- Honor the seven error codes listed in §7

### Out of Scope

- Organization create / delete / archive / suspend
- `workspace_config`, `pause_reason`, `paused_at` field edits
- Organization stats / dashboard / portability / branding sub-routes
- Aggregations under `/api/orgs/{orgId}/...` beyond issues + approvals listings already shipped in Step 6
- Actor injection middleware in production (production curl will return 503 — tracked as a known gap for a later step)

## 4. Architecture

Four strict layers per `A-CONSTRAINTS.md §8`:

```
HTTP
 │
 ▼
[route] server/routes/orgs.py
  - PATCH /api/orgs/{orgId}
  - inject require_board_access (503/403), get_owned_org_detail (404 then ownership)
  - call validate_update_organization (422)
  - extract actor identity, call service.update, return OrganizationDetail or 404
 │
 ▼
[dependency] server/dependencies/orgs.py + ownership.py
  - require_board_access: actor presence + actor.type == "board"
  - get_owned_org_detail: SELECT then assert_organization_owned (lookup-then-ownership)
  - assert_organization_owned: OwnershipDecision → 403 foreign/missing, 409 expired
 │
 ▼
[service] server/services/orgs.py
  - OrgService.update(org_id, payload, *, actor_type, actor_id)
  - map camelCase payload to snake_case columns via ORG_UPDATE_TO_COLUMN
  - if non-empty: update_organization → insert_activity_log atomically
  - empty payload: return current detail, no UPDATE, no activity
 │
 ▼
[query] packages/database/queries/organizations.py + activity_log.py
  - update_organization(session, org_id, fields) — UPDATE ... RETURNING
  - insert_activity_log(session, *, org_id, actor_type, ...) — INSERT + flush
 │
 ▼
[schema] packages/database/schema/ (Step 4, unchanged)
  - Organization (no onupdate; updated_at refreshed by query layer)
  - ActivityLog (entity_type/entity_id, action, details JSON)
```

### Key design decision: request-scoped transaction

The current `get_session` opens a session but no transaction. `get_owned_org_detail` runs a SELECT which autobegins the session's implicit transaction. If `OrgService.update` then opens its own `async with session.begin()` for the update + activity atomic pair, SQLAlchemy raises `InvalidRequestError: A transaction is already begun on this Session`.

Resolution: lift the transaction boundary to the dependency. `get_session` becomes:

```python
async with session_factory() as session:
    async with session.begin():
        yield session
```

Effects:
- The entire request runs inside one explicit transaction
- `service.update` no longer opens a nested transaction
- UPDATE + activity_log INSERT commit atomically with the same commit point
- Existing Step 1-6 routes are unaffected (they only read; reads work identically inside an outer `session.begin()`)
- Test fixtures using `async_transaction(session)` directly remain unaffected (they create sessions via `session_factory()`, not via `get_session`)

## 5. Components

### 5.1 `packages/database/queries/organizations.py` — add `update_organization`

Signature: `async def update_organization(session, organization_id, fields) -> Organization | None`

Behavior:
- Empty `fields` → degrade to `get_organization_by_id` (caller-friendly no-op)
- Non-empty `fields` → set `updated_at = datetime.now(UTC)`, execute `UPDATE ... RETURNING` returning the row
- Row not found → return None

### 5.2 `packages/database/queries/activity_log.py` — new file, `insert_activity_log`

Signature: `async def insert_activity_log(session, *, org_id, actor_type, actor_id, action, entity_type, entity_id, agent_id=None, run_id=None, details=None) -> ActivityLog`

Behavior:
- Keyword-only arguments mirror upstream `logActivity` shape
- Copy `details` defensively (`dict(details)`)
- `session.add(row)` + `await session.flush()` to populate `id` and `created_at`

### 5.3 `server/dependencies/database.py` — refactor `get_session`

Wrap in `async with session.begin()` (see §4 key design decision).

### 5.4 `server/services/orgs.py` — add `OrgService.update`

Signature: `async def update(self, org_id, payload, *, actor_type, actor_id) -> OrganizationDetail | None`

Behavior:
- Translate `payload` (camelCase) → `column_updates` (snake_case) via module-level `ORG_UPDATE_TO_COLUMN` dict containing only the six A §6.2 frozen fields
- Unknown payload keys are silently dropped (validator already rejected bad shapes)
- Empty effective `column_updates` → return current detail, no UPDATE, no activity
- Non-empty → call `update_organization`; if None return None; else call `insert_activity_log` with fixed `action="organization.updated"`, `entity_type="organization"`, `details=dict(payload)`
- Convert ORM row to `OrganizationDetail` via existing `_to_detail` helper

### 5.5 `server/routes/orgs.py` — add `PATCH` route + `_extract_actor_identity`

Route signature: `@router.patch(ORG_DETAIL_PATH)`

Dependency injection order:
1. `Depends(require_board_access)` — 503 or 403 first (no DB)
2. `Depends(get_owned_org_detail)` — 404 then ownership (one SELECT + one ownership check)
3. Body validation (validator → 422)
4. `service.update(...)` (200 or 404)

`_extract_actor_identity(request)` helper: read `request.state.actor`, return `(actor_type, actor_id)` tuple. Supports both Mapping and object actor shapes. Falls back to `("system", "board")` only if no actor (which cannot happen here because `require_board_access` would have raised 503 first).

## 6. Data Flow — Successful PATCH

```
client → PATCH /api/orgs/{orgId} with JSON body and x-test-actor-type: board
  │
  ▼
test middleware sets request.state.actor = {"type": "board", "id": "test-actor"}
  │
  ▼
require_board_access: actor.type == "board" → pass
  │
  ▼
get_session opens session and `async with session.begin()` (transaction open)
  │
  ▼
get_owned_org_detail: SELECT Organization (autobegin into outer tx)
  → OrganizationDetail returned
  → assert_organization_owned: SELECT OrganizationOwnership → OWNED → pass
  │
  ▼
route body: validate_update_organization(body) → UpdateOrganizationPayload
  │
  ▼
_extract_actor_identity(request) → ("board", "test-actor")
  │
  ▼
service.update(org_id, payload, actor_type="board", actor_id="test-actor")
  → map camelCase to snake_case → column_updates
  → update_organization: UPDATE ... RETURNING (same tx)
  → insert_activity_log: INSERT activity_log row (same tx)
  → return OrganizationDetail
  │
  ▼
get_session's `async with session.begin()` exits → COMMIT
  │
  ▼
200 OrganizationDetail JSON
```

## 7. Error Code Matrix

| Order | Layer | Condition | Status | Detail substring |
|---|---|---|---|---|
| 1 | `require_board_access` | actor missing | 503 | `Actor context` |
| 2 | `require_board_access` | actor.type ≠ "board" | 403 | `Board access required` |
| 3 | `get_owned_org_detail` SELECT | org not found | 404 | `Organization not found` |
| 4 | `assert_organization_owned` | no ownership row | 403 | `no ownership record` |
| 5 | `assert_organization_owned` | ownership owned by another pod | 403 | `another pod` |
| 6 | `assert_organization_owned` | lease expired | 409 | `expired` |
| 7 | `validate_update_organization` | payload invalid | 422 | validator's `ValueError` string |

Precedence is enforced by FastAPI dependency resolution order — `require_board_access` is declared first in the route signature, then `get_owned_org_detail`, then body validation runs after both dependencies resolve.

## 8. Activity Log Semantics

Fixed for Step 7 first batch (per A §7.3):

| Field | Value |
|---|---|
| `org_id` | path `{orgId}` |
| `action` | `"organization.updated"` |
| `entity_type` | `"organization"` |
| `entity_id` | path `{orgId}` |
| `actor_type` | from `_extract_actor_identity(request)` |
| `actor_id` | from `_extract_actor_identity(request)` |
| `agent_id` | None |
| `run_id` | None |
| `details` | `dict(payload)` — raw camelCase as submitted |
| `created_at` | server default `now()` |

Atomicity: row is inserted inside the same request-scoped transaction as the UPDATE. If anything between INSERT and commit raises, both the UPDATE and the activity row roll back.

Empty payload special case: no UPDATE, no activity row. Rationale — a no-op PATCH should not pollute the audit trail.

## 9. Frozen Field Whitelist

`ORG_UPDATE_TO_COLUMN` in `server/services/orgs.py` maps exactly the six A §6.2 frozen update fields:

| Payload key (camelCase) | Column (snake_case) |
|---|---|
| `name` | `name` |
| `description` | `description` |
| `budgetMonthlyCents` | `budget_monthly_cents` |
| `defaultChatIssueCreationMode` | `default_chat_issue_creation_mode` |
| `brandColor` | `brand_color` |
| `requireBoardApprovalForNewAgents` | `require_board_approval_for_new_agents` |

Adding a field in a later step is a one-line change here (and a one-line change to the validator). `workspace_config`, `pause_reason`, `paused_at`, `status`, `urlKey`, `issuePrefix`, `issueCounter`, `spentMonthlyCents` are not in this whitelist for Step 7.

## 10. Test Strategy

### 10.1 Location

`tests/contract/test_step7_org_management.py` — new file in same style as `test_step6_read_api.py`.

### 10.2 Infrastructure

- In-memory SQLite via `aiosqlite` + `StaticPool` so the single connection is shared across requests
- `Base.metadata.create_all` invoked in the `engine` fixture so the schema exists without lifespan
- `async_sessionmaker(expire_on_commit=False)` so loaded rows survive across the request commit
- Test-only middleware `_inject_test_actor` reads `x-test-actor-type` header and writes `request.state.actor` — required because production has no actor injection middleware

### 10.3 Assertions (17 total)

13 required by A §12 (one is transitive — row 13 below — so 12 test functions cover all 13 assertions):

| # | Assertion | Test name |
|---|---|---|
| 1 | org list board success | `test_org_list_board_success` |
| 2 | org list missing actor 503 | `test_org_list_missing_actor_returns_503` |
| 3 | org list non-board 403 | `test_org_list_non_board_returns_403` |
| 4 | org detail owned 200 | `test_org_detail_owned_returns_200` |
| 5 | org detail missing 404 | `test_org_detail_missing_returns_404` |
| 6 | org update owned+board 200 | `test_org_update_owned_board_returns_200` |
| 7 | org update can change config | `test_org_update_changes_config_fields` |
| 8 | org update foreign 403 | `test_org_update_foreign_returns_403` |
| 9 | org update expired 409 | `test_org_update_expired_returns_409` |
| 10 | org update non-board 403 | `test_org_update_non_board_returns_403` |
| 11 | org update invalid 422 | `test_org_update_invalid_payload_returns_422` |
| 12 | org update writes activity | `test_org_update_writes_activity_record` |
| 13 | response uses shared camelCase | covered transitively by tests 4, 6, 7 |

5 supplementary defending behaviors A §7.3/§7.4 imply but does not list as a row:

| Test | Defends |
|---|---|
| `test_org_update_partial_does_not_touch_other_fields` | A §7.2 "update 只改变 payload 中显式提供的字段" |
| `test_org_update_missing_actor_returns_503` | A §7.4 503 specifically for PATCH path |
| `test_org_update_missing_org_returns_404` | A §7.4 404 specifically for PATCH path |
| `test_org_update_missing_ownership_returns_403` | A §7.4 missing ownership separate from foreign |
| `test_org_update_empty_payload_no_activity` | A §7.3 no-op must not write audit |

### 10.4 Expected outcome

Total: 91 passed (74 from Step 6 baseline + 17 new). pyright: 0 errors. ruff: clean. format: no changes.

## 11. Verification Procedure

After every commit during implementation:

```powershell
.venv\Scripts\ruff.exe check . --fix
.venv\Scripts\ruff.exe format .
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pyright --pythonpath .venv\Scripts\python.exe
```

All four must be green. The `--pythonpath` flag on pyright is required so imports resolve against the venv site-packages instead of the global Python.

Manual smoke after the final commit:

```powershell
.venv\Scripts\python.exe -m uvicorn server.app:app --port 8000
```

Then curl the production HTTP surface. Expected: 503 on all three org endpoints because production has no actor injection middleware. Recorded as a known gap in §3 Out of Scope.

## 12. Upstream Cross-Check

What is preserved from `rudder/server/src/routes/orgs.ts` line 584-624 `PATCH /:orgId`:

- HTTP method + path: `PATCH /api/orgs/{orgId}`
- Body validation precedes service call
- Service returns null → 404 with `Organization not found`
- Activity log row written after successful service call with `action: "organization.updated"`, `entity_type: "organization"`, `entity_id: orgId`, `details: body`
- Actor identity derived from request context, not body

What differs and why:

| Upstream | Octopus | Reason |
|---|---|---|
| `updateOrganizationSchema` (Zod) for board, `updateOrganizationBrandingSchema` for agent CEO | `validate_update_organization` for board only | Step 7 first batch is board-only; agent CEO branding sub-route deferred |
| `assertCompanyAccess(req, orgId)` based on `req.actor.orgIds` membership | `assert_organization_owned(orgId)` based on `OrganizationOwnership.pod_id` | Octopus uses pod-level ownership, not user-level company membership (per DESIGN.md §6.3) |
| In-route `assertBoard(req)` after access check | Standalone `require_board_access` dependency, runs before ownership check | FastAPI dependency injection wants non-DB checks first |
| Activity logged after service call returns | Activity logged inside service, same tx as UPDATE | Atomic audit — upstream uses separate await; Octopus uses single tx |
| `logoAssetId` handling, branding fields, `workspaceConfig` | Not in Step 7 scope | Per A §3 §6.2 |

## 13. Acceptance Criteria

Implementation is complete when all of the following hold:

1. Six commits land on `feat/server-phase-7-rebuild` in the order specified by the implementation plan
2. Four-step verification green after each commit
3. 91 pytest passed including all 17 Step 7 assertions
4. pyright 0 errors
5. Manual curl smoke recorded showing 503 in production (known gap)
6. `docs/step-07/ORGANIZATION-MANAGEMENT.md` execution record written covering layer wiring, error matrix, activity semantics, test mapping table, upstream cross-check, transaction restructure note, known gaps, verification record

## 14. Deferred to Later Steps

Items intentionally left out and tracked for later:

- Actor injection middleware in production (Step 14 governance candidate; gap recorded in execution record)
- Agent CEO branding sub-route (`PATCH /api/orgs/{orgId}/branding`)
- Organization create / delete / archive sub-routes
- Logo asset handling
- Workspace config edits
- Organization secrets store (relevant when Step 9 hire-agent approval is implemented)
- `tests/workflows/` end-to-end harness (whole project still unfilled)
