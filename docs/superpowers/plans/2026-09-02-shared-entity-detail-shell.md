# Shared Entity Detail Shell Implementation Plan

**Goal:** Make agent detail and organization project detail use one page skeleton, one primary content scroll owner, and the same spacing and scrollbar rules.

**Architecture:** Add small compositional React primitives for the entity-detail shell and viewport. Keep entity headers, tabs, data queries, forms, file browsers, lists, and split panes in their existing pages. The shared shell constrains the page to the available viewport; the shared viewport owns ordinary tab scrolling, while specialized file-browser and split-pane tabs may keep their existing internal scroll regions.

**Tech Stack:** React, TypeScript, CSS, Vitest, Testing Library.

---

### Task 1: Shared Detail Skeleton

**Files:**
- Add: `ui/src/components/EntityDetailShell.tsx`
- Modify: `ui/src/styles.css`

- [x] Add compositional shell, header, and viewport primitives without entity-specific behavior.
- [x] Define fixed header/tab regions, a single flexible viewport, and a restrained shared scrollbar.
- [x] Preserve the existing 24px page edge and 12px primary card inset conventions.

### Task 2: Agent Detail Migration

**Files:**
- Modify: `ui/src/pages/AgentPage.tsx`
- Modify: `ui/src/test/agent-page.test.tsx` only if structure assertions need updating.

- [x] Wrap the existing agent header, notices, tabs, and active panel in the shared skeleton.
- [x] Keep file browser, configuration/history split, skills detail, and runs split behavior intact.
- [x] Keep dialogs outside the scrolling viewport.

### Task 3: Project Detail Migration

**Files:**
- Modify: `ui/src/pages/ProjectPage.tsx`
- Modify: `ui/src/test/project-page.test.tsx` only if structure assertions need updating.

- [x] Wrap the existing project header, pause notice, tabs, and active panel in the shared skeleton.
- [x] Move configuration, workspace, resources, issues, and budget under the shared viewport.
- [x] Preserve the workspace explorer's internal sizing and scrolling.

### Task 4: Verification

- [x] Run targeted agent and project detail tests.
- [x] Run `git diff --check`.
- [x] Inspect the final diff for accidental changes to the user's existing uncommitted work.
