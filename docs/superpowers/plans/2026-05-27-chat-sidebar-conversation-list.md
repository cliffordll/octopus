# Chat Sidebar Conversation List Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the messages secondary sidebar to a complete conversation list without filters.

**Architecture:** `ChatsWorkspace` continues loading conversations and agents for display labels, but no longer stores sidebar filter state or renders filter controls. Composer-level agent selection remains owned by the chat pages.

**Tech Stack:** React, TanStack Query, TypeScript, Vitest, Testing Library, CSS.

---

### Task 1: Conversation-Only Sidebar

**Files:**
- Modify: `ui/src/test/chats-page.test.tsx`
- Modify: `ui/src/components/ContextWorkspace.tsx`
- Modify: `ui/src/styles.css`

- [ ] Change the sidebar test to require all returned conversations at once, require the absence of `搜索对话`/sidebar `状态`/sidebar `智能体`, and require `暂无对话` for empty data.
- [ ] Run `npm test -- --run src/test/chats-page.test.tsx` and confirm failure because filtering controls still render and empty state uses matching-language text.
- [ ] Remove sidebar filter state and controls, render the full conversation array, update the empty message, and remove now-unused filter styles.
- [ ] Re-run the targeted test and confirm pass.

### Task 2: Verification

**Files:**
- Review modified `ui/` and `docs/superpowers/` files.

- [ ] Run `npm test`, `npm run typecheck`, and `npm run build` from `ui/`.
- [ ] Run `git diff --check` and `git diff --name-only -- server packages` to confirm clean formatting and no server changes.
