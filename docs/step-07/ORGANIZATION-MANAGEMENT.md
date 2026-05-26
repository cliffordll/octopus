# Step 7 Organization Management Execution Record

## 1. Scope and Authoritative Input

Scope covered: `PATCH /api/orgs/{orgId}` with payload validation, board access guard, organization ownership guard, atomic activity log emission. List and detail endpoints reused unchanged from Step 6.

Authoritative inputs consulted:
- `docs/step-07/A-CONSTRAINTS.md` §3 (range), §6.2 (frozen field set), §7 (access + write semantics + error codes), §12 (test assertions)
- `docs/step-07/B-SPEC.md` (design spec derived from A-CONSTRAINTS)
- `docs/step-07/B-PLAN.md` (implementation plan derived from B-SPEC)
- `docs/DESIGN.md` §3.3, §7.2.7, §8 (architecture principles)
- `upstream-reference/rudder/server/src/routes/orgs.ts` line 584-624 (PATCH `/:orgId` behavioral reference)
- `upstream-reference/rudder/server/src/services/orgs.ts` `update()` method (transaction boundary reference)

## 2. Route Surface

| Method | Path | Step | Purpose |
|---|---|---|---|
| GET | `/api/orgs` | 6 | Board-scoped list, returns `OrganizationSummary[]` |
| GET | `/api/orgs/{orgId}` | 6 | Lookup-then-ownership, returns `OrganizationDetail` |
| PATCH | `/api/orgs/{orgId}` | 7 | Board+ownership-guarded update of 6 whitelisted fields, returns `OrganizationDetail` |

## 3. Layer Wiring Map

| Layer | File | Responsibility added in Step 7 |
|---|---|---|
| route | `server/routes/orgs.py` | PATCH handler + `_extract_actor_identity` helper; `require_board_access` unchanged from Step 6 |
| dependency | `server/dependencies/orgs.py` | `get_owned_org_detail` unchanged from Step 6 |
| dependency | `server/dependencies/ownership.py` | `assert_organization_owned` unchanged from Step 5 |
| dependency | `server/dependencies/database.py` | `get_session` wraps `async with session.begin()` — refactor |
| service | `server/services/orgs.py` | `ORG_UPDATE_TO_COLUMN` map + `OrgService.update` method |
| query | `packages/database/queries/organizations.py` | `update_organization` helper |
| query | `packages/database/queries/activity_log.py` | `insert_activity_log` helper — new file |
| schema | `packages/database/schema/` | unchanged |

## 4. Error Code Matrix

| Order | Layer | Condition | Status | Detail substring |
|---|---|---|---|---|
| 1 | `require_board_access` | actor missing | 503 | `Actor context` |
| 2 | `require_board_access` | actor.type ≠ board | 403 | `Board access required` |
| 3 | `get_owned_org_detail` SELECT | org not found | 404 | `Organization not found` |
| 4 | `assert_organization_owned` | no ownership row | 403 | `no ownership record` |
| 5 | `assert_organization_owned` | ownership owned by another pod | 403 | `another pod` |
| 6 | `assert_organization_owned` | lease expired | 409 | `expired` |
| 7 | `validate_update_organization` | payload invalid | 422 | validator `ValueError` string |

Precedence is enforced by FastAPI dependency resolution order — `require_board_access` is declared first in the route signature, then `get_owned_org_detail`, then body validation runs after both dependencies resolve.

## 5. Activity Log Semantics

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
| `details` | `dict(payload)` — raw camelCase |
| `created_at` | server default `now()` |

Atomicity: row inserted inside the same request-scoped transaction as the UPDATE. If anything between INSERT and commit raises, both UPDATE and activity row roll back.

Empty payload special case: no UPDATE, no activity row, returns current detail. Rationale — a no-op PATCH should not pollute the audit trail.

## 6. Transaction Restructure Note

`get_session` was lifted to request-scoped transaction (`async with session.begin()`). The previous version opened the session but no transaction, leaving sqlalchemy to autobegin on the first SELECT. The collision happened when `get_owned_org_detail`'s SELECT autobegan, and then `service.update` tried to open its own `async with session.begin()` for the update + activity pair — sqlalchemy raised `InvalidRequestError: A transaction is already begun on this Session`. With the dependency-level transaction, the entire request runs in one explicit tx and the service no longer needs to open a nested one.

Test fixtures using `async_transaction(session)` directly are unaffected because they create sessions via `session_factory()`, not via `get_session`.

## 7. Test Coverage Mapping

A-CONSTRAINTS §12 13 required assertions (one is transitive — row 13 — so 12 test functions cover all 13 assertions):

| # | Assertion | Test |
|---|---|---|
| 1 | organization list board request success | `test_org_list_board_success` |
| 2 | organization list missing actor returns 503 | `test_org_list_missing_actor_returns_503` |
| 3 | organization list non-board rejected with 403 | `test_org_list_non_board_returns_403` |
| 4 | organization detail owned request success | `test_org_detail_owned_returns_200` |
| 5 | organization detail missing resource returns 404 | `test_org_detail_missing_returns_404` |
| 6 | organization update owned + board success | `test_org_update_owned_board_returns_200` |
| 7 | organization update can change config fields | `test_org_update_changes_config_fields` |
| 8 | organization update foreign ownership rejected | `test_org_update_foreign_returns_403` |
| 9 | organization update expired ownership rejected | `test_org_update_expired_returns_409` |
| 10 | organization update non-board rejected | `test_org_update_non_board_returns_403` |
| 11 | organization update invalid payload returns 422 | `test_org_update_invalid_payload_returns_422` |
| 12 | organization update writes minimal activity record | `test_org_update_writes_activity_record` |
| 13 | response field names use shared camelCase | covered transitively by tests 4, 6, 7 |

5 supplementary tests:

| Test | Defends |
|---|---|
| `test_org_update_partial_does_not_touch_other_fields` | A §7.2 update 只改变 payload 中显式提供的字段 |
| `test_org_update_missing_actor_returns_503` | A §7.4 503 for PATCH path |
| `test_org_update_missing_org_returns_404` | A §7.4 404 for PATCH path |
| `test_org_update_missing_ownership_returns_403` | A §7.4 missing ownership distinct from foreign |
| `test_org_update_empty_payload_no_activity` | A §7.3 no-op must not write audit |

Total tests added in Step 7: 21 (3 query-level for `update_organization` + 1 query-level for `insert_activity_log` + 17 contract integration). Combined with Step 1-6 baseline (74): **95 passed**.

## 8. Upstream Cross-Check

Preserved from `rudder/server/src/routes/orgs.ts` PATCH `/:orgId`:
- HTTP method + path
- Body validation precedes service call
- Service returns null → 404 with `Organization not found`
- Activity log written with `action: "organization.updated"`, `entity_type: "organization"`, `entity_id: orgId`, `details: body`
- Actor identity from request context, not body

Deviations and why:

| Upstream | Octopus | Reason |
|---|---|---|
| `updateOrganizationSchema` for board, `updateOrganizationBrandingSchema` for agent CEO | `validate_update_organization` for board only | Step 7 first batch is board-only; agent branding deferred |
| `assertCompanyAccess` based on `req.actor.orgIds` membership | `assert_organization_owned` based on `OrganizationOwnership.pod_id` | Octopus uses pod-level ownership per DESIGN.md §6.3 |
| In-route `assertBoard` after access check | Standalone `require_board_access` dependency runs before ownership | FastAPI dependency injection wants non-DB checks first |
| Activity logged after service call returns | Activity logged inside service, same tx as UPDATE | Atomic audit — upstream uses separate await, Octopus uses single tx |
| `logoAssetId` handling, branding, `workspaceConfig` | Not in Step 7 scope | Per A §3 §6.2 |

## 9. Known Gaps

- Production app has no actor injection middleware. Real curl against the production server returns 503 on every org endpoint. Tracked for resolution in a later step (DESIGN.md §6.5 and §7.2.6 describe what is required).
- `tests/workflows/` end-to-end harness still not created in this project.
- Org create / delete / archive sub-routes intentionally deferred per A §3.

## 10. Verification Record

Four-step verification after Task 6 (final implementation step):

```
.venv\Scripts\ruff.exe check . --fix       → All checks passed!
.venv\Scripts\ruff.exe format .            → 66 files left unchanged
.venv\Scripts\python.exe -m pytest -q      → 95 passed
.venv\Scripts\python.exe -m pyright --pythonpath .venv\Scripts\python.exe → 0 errors
```

One informational warning surfaced by pytest: `DeprecationWarning: 'HTTP_422_UNPROCESSABLE_ENTITY' is deprecated. Use 'HTTP_422_UNPROCESSABLE_CONTENT' instead`. The numeric status code (422) is unchanged; the constant was kept for symmetry with Step 6 routes.
