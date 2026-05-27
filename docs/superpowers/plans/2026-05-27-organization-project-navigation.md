# Organization Project Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group organization secondary navigation and add configuration, resources, and tasks tabs to project detail using existing APIs.

**Architecture:** `OrgNavigation` owns organization-level and project-level sidebar groups and fetches the current project's sibling list. `ProjectPage` keeps its existing mutations but selects one of three routed tab panels, with the tasks panel querying issues by `projectId`.

**Tech Stack:** React, React Router, TanStack Query, TypeScript, Vitest, Testing Library, CSS.

---

### Task 1: Grouped Organization Sidebar

**Files:**
- Modify: `ui/src/test/projects-page.test.tsx`
- Modify: `ui/src/pages/OrganizationPage.tsx`
- Modify: `ui/src/styles.css`

- [ ] Add failing assertions requiring `组织` and `项目` section headings plus dynamic project detail links.
- [ ] Run `npm test -- --run src/test/projects-page.test.tsx` and confirm failure because the existing sidebar has a flat `项目` entry.
- [ ] Query `projectsApi.list(orgId)` in `OrgNavigation`, render organization links in one section and returned projects in another, with an empty-state fallback.
- [ ] Re-run the targeted test and confirm pass.

### Task 1A: Organization Sidebar Visual Hierarchy

**Files:**
- Modify: `ui/src/test/projects-page.test.tsx`
- Modify: `ui/src/pages/OrganizationPage.tsx`
- Modify: `ui/src/styles.css`

- [ ] Add failing assertions requiring the organization links and `全部项目` to use `local-nav-primary`, while returned project links use `local-nav-project`.
- [ ] Run `npm test -- --run src/test/projects-page.test.tsx` and confirm failure because links do not yet expose primary/secondary styling roles.
- [ ] Assign the styling roles in `OrgNavigation` and style project links with indentation, reduced emphasis, a separated project-list container, and retained active-state contrast.
- [ ] Re-run the targeted test and confirm pass.

### Task 2: Project Detail Tabs And Task Panel

**Files:**
- Modify: `ui/src/test/project-page.test.tsx`
- Modify: `ui/src/pages/ProjectPage.tsx`
- Modify: `ui/src/app/App.tsx`
- Modify: `ui/src/styles.css`

- [ ] Add failing assertions for routed `配置`/`资源`/`任务` tabs and for `GET /api/orgs/org-1/issues?projectId=project-1` on the tasks tab.
- [ ] Run `npm test -- --run src/test/project-page.test.tsx` and confirm failure because tabs and task filtering are absent.
- [ ] Register the optional project detail tab route, render each existing project function under its matching tab, and query/render issue links for `任务`.
- [ ] Re-run project tests and confirm pass.

### Task 3: Verification

**Files:**
- Review all modified `ui/` and `docs/superpowers/` files.

- [ ] Run `npm test`, `npm run typecheck`, and `npm run build` from `ui/`.
- [ ] Run `git diff --check` and `git diff --name-only -- server packages` to prove formatting is acceptable and server code is untouched.
