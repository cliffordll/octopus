# CLI Upstream-Supported Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Align the Python CLI with upstream Rudder command concepts wherever this repository already exposes matching server APIs.

**Architecture:** Preserve the existing argparse command modules and `ApiClient`; add only parser aliases and thin route handlers backed by existing endpoints. Keep commands without server support out of scope and document local-only extensions separately.

**Tech Stack:** Python 3.12, argparse, httpx, pytest

---

### Task 1: Add Upstream-Style Issue Comment Entry Point

**Files:**
- Modify: `cli/commands/issue.py`
- Test: `cli/tests/test_issue_commands.py`

- [ ] **Step 1: Write the failing command test**

Add a test invoking:

```python
main(["issue", "comment", "issue-1", "--body", "Reviewed"], client=client)
```

and assert it posts `{"body":"Reviewed"}` to `/api/issues/issue-1/comments`.

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run pytest cli/tests/test_issue_commands.py -q`

Expected: `argparse` rejects `comment` because only `comment-add` exists.

- [ ] **Step 3: Implement the parser alias**

Register `comment` as the public command and `comment-add` as an alias, both using the existing `add_comment()` handler.

- [ ] **Step 4: Run the test to verify success**

Run: `uv run pytest cli/tests/test_issue_commands.py -q`

Expected: PASS.

### Task 2: Expose Supported Agent Read Operations

**Files:**
- Modify: `cli/commands/agent.py`
- Test: `cli/tests/test_agent_commands.py`

- [ ] **Step 1: Write failing endpoint tests**

Invoke each new command through `main()` and assert GET requests for:

```text
/api/agents/agent-1/configuration
/api/agents/agent-1/config-revisions
/api/agents/agent-1/config-revisions/rev-1
/api/agents/agent-1/runtime-state
/api/agents/agent-1/task-sessions
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `uv run pytest cli/tests/test_agent_commands.py -q`

Expected: `argparse` rejects the missing agent subcommands.

- [ ] **Step 3: Implement route handlers and parsers**

Add handlers that call `client.request("GET", path)` and parsers named `configuration`, `config-revisions`, `config-revision`, `runtime-state`, and `task-sessions`.

- [ ] **Step 4: Run the tests to verify success**

Run: `uv run pytest cli/tests/test_agent_commands.py -q`

Expected: PASS.

### Task 3: Add Heartbeat Run Alias

**Files:**
- Modify: `cli/commands/heartbeat.py`
- Test: `cli/tests/test_agent_commands.py`

- [ ] **Step 1: Write the failing test**

Invoke:

```python
main(["heartbeat", "run", "--agent-id", "agent-1"], client=client)
```

and assert a POST request with `{}` to `/api/agents/agent-1/heartbeat/invoke`.

- [ ] **Step 2: Run the test to verify failure**

Run: `uv run pytest cli/tests/test_agent_commands.py -q`

Expected: `argparse` rejects `run`.

- [ ] **Step 3: Implement the alias**

Add a `run` subparser with required `--agent-id` and a handler posting to the existing invoke endpoint.

- [ ] **Step 4: Run the test to verify success**

Run: `uv run pytest cli/tests/test_agent_commands.py -q`

Expected: PASS.

### Task 4: Update CLI Documentation And Verify

**Files:**
- Modify: `cli/README.md`

- [ ] **Step 1: Document the supported aligned command surface**

Document `org`, issue actions including `comment`, approval actions, supported agent reads, `heartbeat run`, and existing local `project`/`chat` extensions.

- [ ] **Step 2: Run full verification**

Run:

```powershell
uv run pytest cli/tests -q
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run pyright .
git diff --name-only
```

Expected: checks pass and no source change occurs below `server/` or `packages/`.
