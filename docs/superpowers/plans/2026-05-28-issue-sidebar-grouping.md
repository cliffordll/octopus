# Issue Sidebar Grouping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Group the task secondary navigation into task shortcuts, recently viewed tasks, and project-expanded task lists.

**Architecture:** `IssuesWorkspace` remains the owner of the secondary task navigation. It loads issues and projects, groups tasks by `projectId`, and reads locally stored recent issue visits. `IssuesPage` uses query params for status navigation, and `IssuePage` records viewed issues in local storage after detail data loads.

**Tech Stack:** React, React Router, TanStack Query, TypeScript, Vitest, Testing Library, CSS.

---

### Task 1: Navigation Behavior Tests

**Files:**
- Modify: `ui/src/test/issues-page.test.tsx`
- Modify: `ui/src/test/issue-page.test.tsx`

- [ ] Add a test that expects task navigation sections named `任务`, `最近查看`, and `项目`.
- [ ] In that test, mock `/api/orgs/org-1/projects` and `/api/orgs/org-1/issues`, then assert project tasks render under their project with status badges.
- [ ] Assert clicking `草稿任务` fetches `/api/orgs/org-1/issues?status=backlog`.
- [ ] Add a detail-page assertion that opening an issue writes the issue to local storage.
- [ ] Run `npm test -- --run src/test/issues-page.test.tsx src/test/issue-page.test.tsx` and confirm the new assertions fail before implementation.

### Task 2: Frontend Implementation

**Files:**
- Modify: `ui/src/components/ContextWorkspace.tsx`
- Modify: `ui/src/pages/IssuesPage.tsx`
- Modify: `ui/src/pages/IssuePage.tsx`
- Modify: `ui/src/styles.css`

- [ ] Update `IssuesWorkspace` to load projects, render grouped nav sections, show task shortcuts with consistent link styling, recent issue links, and project issue links without secondary-menu empty-state text.
- [ ] Update `IssuesPage` to derive status from `useSearchParams` so the `草稿任务` link drives the existing list query.
- [ ] Update `IssuePage` to store recent issue visits in `localStorage`.
- [ ] Add scoped CSS for context navigation sections, disabled entries, and nested project issue links.
- [ ] Re-run targeted tests and confirm they pass.

### Task 3: Verification

**Files:**
- Review all changed `ui/` and `docs/superpowers/` files.

- [ ] Run `npm test`.
- [ ] Run `npm run typecheck`.
- [ ] Run `npm run build`.
- [ ] Run `git diff --check`.
- [ ] Run `git diff --name-only -- server packages` and confirm there are no server or packages changes.
