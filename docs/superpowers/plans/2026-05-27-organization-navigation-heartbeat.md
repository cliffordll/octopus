# Organization Navigation And Heartbeat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add organization secondary navigation and an organization-level heartbeat view while moving organization management into the avatar menu.

**Architecture:** Keep `AppShell` responsible for primary navigation and organization switching. Reuse `OrgWorkspace` as the secondary navigation wrapper for organization structure, projects, and heartbeat, while adding focused pages for structure and heartbeat backed by existing agent and heartbeat endpoints.

**Tech Stack:** React 19, React Router, TanStack Query, TypeScript, Vitest, Testing Library, CSS.

---

## File Structure

- Modify `ui/src/components/AppShell.tsx`: primary organization route and avatar management links.
- Modify `ui/src/pages/OrganizationPage.tsx`: reusable organization navigation, settings view, and new structure view.
- Create `ui/src/pages/HeartbeatRunsPage.tsx`: organization-scoped heartbeat list/detail/events surface.
- Modify `ui/src/app/App.tsx`: structure, settings, and heartbeat routes plus organization root redirect.
- Modify `ui/src/api/heartbeat.ts` and `ui/src/api/types.ts`: detail/events client contract needed by the new view.
- Modify `ui/src/styles.css`: organization structure and heartbeat presentation.
- Modify/add `ui/src/test/*.test.tsx`: navigation, structure, projects secondary menu, heartbeat view, and API client behavior.

### Task 1: Primary And Secondary Navigation

**Files:**
- Modify: `ui/src/test/agents-page.test.tsx`
- Modify: `ui/src/test/projects-page.test.tsx`
- Modify: `ui/src/components/AppShell.tsx`
- Modify: `ui/src/pages/OrganizationPage.tsx`
- Modify: `ui/src/app/App.tsx`

- [ ] **Step 1: Write failing navigation assertions**

Update the agent navigation test to require the organization primary link and
avatar menu entries:

```tsx
expect(primaryNavigation.getByRole("link", { name: "组织" })).toHaveAttribute(
  "href",
  "/orgs/org-1/structure",
);
expect(primaryNavigation.queryByRole("link", { name: "管理组织" })).not.toBeInTheDocument();
await userEvent.click(screen.getByRole("button", { name: "切换组织" }));
const organizationMenu = within(screen.getByRole("navigation", { name: "组织切换菜单" }));
expect(organizationMenu.getByRole("link", { name: "组织设置" })).toHaveAttribute(
  "href",
  "/orgs/org-1/settings",
);
expect(organizationMenu.getByRole("link", { name: "管理组织" })).toHaveAttribute(
  "href",
  "/organizations",
);
```

Update the projects test to require the organization secondary navigation:

```tsx
const organizationNavigation = screen.getByRole("navigation", { name: "组织导航" });
expect(within(organizationNavigation).getByRole("link", { name: "组织架构" })).toHaveAttribute(
  "href",
  "/orgs/org-1/structure",
);
expect(within(organizationNavigation).getByRole("link", { name: "项目" })).toBeInTheDocument();
expect(within(organizationNavigation).getByRole("link", { name: "心跳" })).toHaveAttribute(
  "href",
  "/orgs/org-1/heartbeat-runs",
);
expect(within(organizationNavigation).queryByRole("link", { name: "审批" })).not.toBeInTheDocument();
expect(within(organizationNavigation).queryByRole("link", { name: "设置" })).not.toBeInTheDocument();
```

- [ ] **Step 2: Run tests and verify the navigation assertions fail**

Run: `npm test -- src/test/agents-page.test.tsx src/test/projects-page.test.tsx`

Expected: FAIL because `组织` still routes to `/organizations`, avatar lacks
`组织设置`, and secondary navigation still shows approval/settings instead of
structure/heartbeat.

- [ ] **Step 3: Implement navigation and routes**

Change `AppShell` primary navigation so:

```tsx
<NavLink to={`/orgs/${selectedOrganizationId}/structure`}>
  <span aria-hidden="true" className="nav-icon">O</span>
  <span>组织</span>
</NavLink>
```

Add avatar menu links:

```tsx
{selectedOrganizationId && (
  <NavLink onClick={() => setOrganizationMenuOpen(false)} to={`/orgs/${selectedOrganizationId}/settings`}>
    组织设置
  </NavLink>
)}
<NavLink onClick={() => setOrganizationMenuOpen(false)} to="/organizations">
  管理组织
</NavLink>
```

Change `OrgNavigation` links to:

```tsx
<NavLink to={`/orgs/${orgId}/structure`}>组织架构</NavLink>
<NavLink to={`/orgs/${orgId}/projects`}>项目</NavLink>
<NavLink to={`/orgs/${orgId}/heartbeat-runs`}>心跳</NavLink>
```

Route `/orgs/:orgId/settings` to the existing organization form and route
`/orgs/:orgId` to a redirect component returning
`<Navigate replace to={`/orgs/${orgId}/structure`} />`.

- [ ] **Step 4: Run targeted tests and verify green**

Run: `npm test -- src/test/agents-page.test.tsx src/test/projects-page.test.tsx`

Expected: PASS.

### Task 2: Organization Structure View

**Files:**
- Create: `ui/src/test/organization-structure-page.test.tsx`
- Modify: `ui/src/pages/OrganizationPage.tsx`
- Modify: `ui/src/api/types.ts`
- Modify: `ui/src/styles.css`

- [ ] **Step 1: Write failing structure tests**

Create tests rendering `/orgs/org-1/structure`, returning a manager and a
worker with `reportsTo`, and assert:

```tsx
expect(await screen.findByRole("heading", { name: "组织架构" })).toBeInTheDocument();
expect(screen.getByText("Builder")).toBeInTheDocument();
expect(screen.getByText("向 Founder 汇报")).toBeInTheDocument();
```

Add an empty-state case asserting:

```tsx
expect(await screen.findByText("暂无智能体。创建首个智能体以建立组织架构。")).toBeInTheDocument();
expect(screen.getByRole("link", { name: "新建智能体" })).toHaveAttribute(
  "href",
  "/orgs/org-empty/agents/new",
);
```

- [ ] **Step 2: Run the structure tests and verify they fail**

Run: `npm test -- src/test/organization-structure-page.test.tsx`

Expected: FAIL because the structure route and view do not yet exist.

- [ ] **Step 3: Implement structure page**

Expand the UI `Agent` interface to include:

```ts
reportsTo?: string | null;
```

Add `OrganizationStructurePage` inside `OrganizationPage.tsx`; fetch
`agentsApi.list(orgId)`, build a name map, and render each agent as:

```tsx
<article className="organization-member" key={agent.id}>
  <div>
    <strong>{agent.name}</strong>
    <span>{agent.title ?? agent.role}</span>
  </div>
  <p>{agent.reportsTo ? `向 ${agentNameById.get(agent.reportsTo) ?? "未知智能体"} 汇报` : "直属组织"}</p>
  <Badge>{agent.status}</Badge>
</article>
```

Wrap it in `OrgWorkspace`, render empty state and `/agents/new` action, and
add minimal layout styles for `.organization-structure` and
`.organization-member`.

- [ ] **Step 4: Run the structure tests and verify green**

Run: `npm test -- src/test/organization-structure-page.test.tsx`

Expected: PASS.

### Task 3: Heartbeat API Client And Organization Heartbeat Page

**Files:**
- Modify: `ui/src/test/api.test.ts`
- Create: `ui/src/test/heartbeat-runs-page.test.tsx`
- Modify: `ui/src/api/types.ts`
- Modify: `ui/src/api/heartbeat.ts`
- Create: `ui/src/pages/HeartbeatRunsPage.tsx`
- Modify: `ui/src/app/App.tsx`
- Modify: `ui/src/styles.css`

- [ ] **Step 1: Write failing API and page tests**

Extend the API test to call:

```ts
await heartbeatApi.get("run-1");
await heartbeatApi.listEvents("run-1");
expect(fetchMock).toHaveBeenNthCalledWith(
  5,
  "/api/heartbeat-runs/run-1",
  expect.objectContaining({ method: "GET" }),
);
expect(fetchMock).toHaveBeenNthCalledWith(
  6,
  "/api/heartbeat-runs/run-1/events",
  expect.objectContaining({ method: "GET" }),
);
```

Create a heartbeat page test that returns organization agents, runs, selected
run detail, and events, then asserts:

```tsx
renderApp("/orgs/org-1/heartbeat-runs");
expect(await screen.findByRole("heading", { name: "心跳" })).toBeInTheDocument();
expect(screen.getByText("Builder")).toBeInTheDocument();
await userEvent.selectOptions(screen.getByLabelText("智能体筛选"), "agent-1");
expect(fetchMock).toHaveBeenCalledWith(
  "/api/orgs/org-1/heartbeat-runs?agentId=agent-1",
  expect.objectContaining({ method: "GET" }),
);
await userEvent.click(screen.getByRole("button", { name: /run-1/ }));
expect(await screen.findByText("heartbeat.started")).toBeInTheDocument();
expect(screen.getByText("Started")).toBeInTheDocument();
```

- [ ] **Step 2: Run tests and verify failure**

Run: `npm test -- src/test/api.test.ts src/test/heartbeat-runs-page.test.tsx`

Expected: FAIL because heartbeat detail/events client methods and heartbeat
route/view are missing.

- [ ] **Step 3: Implement API types and client**

Add:

```ts
export interface HeartbeatRunEvent {
  id: number;
  runId: string;
  agentId: string;
  seq: number;
  eventType: string;
  message: string | null;
  createdAt: string;
}
```

Add API methods:

```ts
get: (runId: string): Promise<HeartbeatRun> =>
  request<HeartbeatRun>(`/api/heartbeat-runs/${encodeURIComponent(runId)}`, { method: "GET" }),
listEvents: (runId: string): Promise<HeartbeatRunEvent[]> =>
  request<HeartbeatRunEvent[]>(`/api/heartbeat-runs/${encodeURIComponent(runId)}/events`, { method: "GET" }),
```

- [ ] **Step 4: Implement heartbeat page**

Create `HeartbeatRunsPage` with:

```tsx
const runs = useQuery({
  queryKey: ["heartbeat-runs", orgId, agentId],
  queryFn: () => heartbeatApi.list(orgId, agentId || undefined),
});
const detail = useQuery({
  queryKey: ["heartbeat-run", selectedRunId],
  queryFn: () => heartbeatApi.get(selectedRunId),
  enabled: Boolean(selectedRunId),
});
const events = useQuery({
  queryKey: ["heartbeat-run-events", selectedRunId],
  queryFn: () => heartbeatApi.listEvents(selectedRunId),
  enabled: Boolean(selectedRunId),
});
```

Render it in `OrgWorkspace`, including an agent filter, selectable run rows,
detail status/error information, and event messages. Register
`/orgs/:orgId/heartbeat-runs` in `App.tsx` and add focused CSS for the
master/detail grid and event list.

- [ ] **Step 5: Run targeted tests and verify green**

Run: `npm test -- src/test/api.test.ts src/test/heartbeat-runs-page.test.tsx`

Expected: PASS.

### Task 4: Regression And Delivery Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-05-27-organization-navigation-heartbeat-design.md`
- Create: `docs/superpowers/plans/2026-05-27-organization-navigation-heartbeat.md`

- [ ] **Step 1: Run complete UI verification**

Run:

```powershell
cd ui
npm test
npm run typecheck
npm run build
```

Expected: all UI test files pass, TypeScript returns no errors, and Vite
produces a successful production build.

- [ ] **Step 2: Run repository verification**

Run:

```powershell
$env:UV_CACHE_DIR='D:\tmp\octopus-uv-cache-verify'; uv run ruff check .
$env:UV_CACHE_DIR='D:\tmp\octopus-uv-cache-verify'; uv run ruff format --check .
$env:UV_CACHE_DIR='D:\tmp\octopus-uv-cache-verify'; uv run pytest
$env:UV_CACHE_DIR='D:\tmp\octopus-uv-cache-verify'; uv run pyright .
```

Expected: lint and formatting report no failures, all Python tests pass, and
pyright reports zero errors.

- [ ] **Step 3: Report implemented scope without committing**

Summarize changed navigation hierarchy, new structure and heartbeat views,
tests, and verification results. Do not run `git commit`; this repository
requires a later explicit user submission instruction.
