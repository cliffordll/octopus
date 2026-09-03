# Unified Tertiary Page Shell Implementation Plan

**Goal:** Give conversation, agent, issue, and organization-area tertiary pages one title architecture and one shared page-frame vocabulary while preserving specialized business content layouts.

**Architecture:** Generalize the existing entity-detail shell into `TertiaryPageShell`, `TertiaryPageHeader`, and `TertiaryPageViewport`. Standard pages reuse the header primitive; entity detail pages also reuse the shell and viewport. Content remains composed from existing stack, browser, collection, split, board, and conversation layouts.

**Tech Stack:** React, TypeScript, CSS, Vitest, Testing Library.

---

### Task 1: Generalize The Shared Primitives

- [x] Replace entity-specific primitive names with tertiary-page names.
- [x] Preserve flexible header content slots and optional tabs/notices.
- [x] Keep the shared viewport and responsive scroll behavior.

### Task 2: Migrate Primary Tertiary Headers

- [x] Migrate conversation list/detail headers.
- [x] Migrate agent list/create/detail headers.
- [x] Migrate issue list/detail headers.
- [x] Migrate organization section, project, goal, heartbeat, resource, workspace, skill, member, and cost headers.

### Task 3: Preserve Content Layout Variants

- [x] Keep agent and project tab content under the shared viewport.
- [x] Keep file browsers, canvases, lists, boards, conversations, and split panes specialized.
- [x] Avoid introducing nested primary vertical scrolling.

### Task 4: Verification

- [x] Run grouped page tests for conversation, agent, issue, project, and organization surfaces.
- [x] Run TypeScript checking and distinguish pre-existing failures from regressions.
- [x] Run `git diff --check` and inspect the final scope.
