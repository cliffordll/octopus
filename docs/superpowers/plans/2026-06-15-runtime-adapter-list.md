# Runtime Adapter List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose server-registered runtime adapters and make agent runtime selectors consume that list.

**Architecture:** The runtime registry is the single source of truth. A new organization-scoped route serializes registered adapters with metadata, while the React API client and agent forms query it through React Query.

**Tech Stack:** FastAPI, Python runtime registry, React, TanStack Query, Vitest, pytest.

---

### Task 1: Server runtime list

**Files:**
- Modify: `packages/runtimes/registry.py`
- Modify: `packages/runtimes/__init__.py`
- Modify: `packages/shared/api_paths/agents.py`
- Modify: `server/routes/agents.py`
- Test: `tests/contract/test_step14_runtime_adapters.py`

- [ ] Add a failing contract test for `GET /api/orgs/{orgId}/adapters`.
- [ ] Run the focused pytest test and confirm the route is missing.
- [ ] Export a registry-backed `list_runtime_adapters()` function.
- [ ] Add the organization-scoped route and response serialization.
- [ ] Run Step 14 runtime adapter contract tests.

### Task 2: UI runtime list client

**Files:**
- Modify: `ui/src/api/types.ts`
- Modify: `ui/src/api/agents.ts`
- Test: `ui/src/test/api.test.ts`

- [ ] Add a failing API client test for `/api/orgs/org-1/adapters`.
- [ ] Add the `RuntimeAdapterListItem` type and `agentsApi.adapters`.
- [ ] Run the API client test.

### Task 3: Dynamic agent forms

**Files:**
- Modify: `ui/src/pages/NewAgentPage.tsx`
- Modify: `ui/src/pages/AgentPage.tsx`
- Test: `ui/src/test/agents-page.test.tsx`
- Test: `ui/src/test/agent-page.test.tsx`

- [ ] Add failing tests proving server-returned runtime options are rendered.
- [ ] Replace hard-coded creation options with the adapters query.
- [ ] Replace hard-coded configuration options with the same query.
- [ ] Display query errors and disable mutations until adapters load.
- [ ] Run the focused page tests.

### Task 4: Verification

- [ ] Run Step 14 contract tests.
- [ ] Run focused UI tests.
- [ ] Run UI typecheck.
- [ ] Run Ruff and Pyright on changed Python files.
- [ ] Run `git diff --check`.
