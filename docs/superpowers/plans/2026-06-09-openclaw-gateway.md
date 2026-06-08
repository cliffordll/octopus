# OpenClaw Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `openclaw_gateway` runtime as a real WebSocket Gateway adapter with environment checks, execution, and UI/CLI compatibility.

**Architecture:** Add a focused `packages/runtimes/openclaw_gateway` adapter with protocol helpers, environment probe, and runner. Register it through the existing runtime registry so server APIs, CLI, and UI reuse the current runtime contract.

**Tech Stack:** Python 3.12, pytest, pytest-asyncio, `websockets`, existing Octopus runtime adapter protocol.

---

### Task 1: Protocol Helpers

**Files:**
- Create: `packages/runtimes/openclaw_gateway/__init__.py`
- Create: `packages/runtimes/openclaw_gateway/protocol.py`
- Test: `tests/contract/test_openclaw_gateway_runtime.py`

- [ ] **Step 1: Write failing tests**

Add tests for URL validation, auth resolution, header derivation, session key resolution, and agent payload construction.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_openclaw_gateway_runtime.py -q`

Expected: FAIL because `packages.runtimes.openclaw_gateway` does not exist.

- [ ] **Step 3: Implement minimal protocol helpers**

Implement pure functions only: `validate_gateway_url`, `resolve_auth`, `build_connect_payload`, `resolve_session_key`, and `build_agent_payload`.

- [ ] **Step 4: Run tests to verify green**

Run: `uv run pytest tests/contract/test_openclaw_gateway_runtime.py -q`

Expected: PASS for protocol helper tests.

- [ ] **Step 5: Commit**

Run: `git add packages/runtimes/openclaw_gateway tests/contract/test_openclaw_gateway_runtime.py pyproject.toml uv.lock && git commit -m "feat: add openclaw gateway protocol helpers"`

### Task 2: Environment Probe

**Files:**
- Create: `packages/runtimes/openclaw_gateway/environment.py`
- Modify: `tests/contract/test_openclaw_gateway_runtime.py`

- [ ] **Step 1: Write failing tests**

Add tests for missing URL, invalid protocol, auth present/missing, plaintext remote warning, and challenge-only probe using a mock probe coroutine.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_openclaw_gateway_runtime.py -q`

Expected: FAIL because `test_environment` is not implemented.

- [ ] **Step 3: Implement environment checks**

Implement deterministic config checks and injectable WebSocket probe behavior.

- [ ] **Step 4: Run tests to verify green**

Run: `uv run pytest tests/contract/test_openclaw_gateway_runtime.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add packages/runtimes/openclaw_gateway tests/contract/test_openclaw_gateway_runtime.py && git commit -m "feat: add openclaw gateway environment probe"`

### Task 3: Runner

**Files:**
- Create: `packages/runtimes/openclaw_gateway/runner.py`
- Modify: `tests/contract/test_openclaw_gateway_runtime.py`

- [ ] **Step 1: Write failing tests**

Add tests for successful execution against a mock WebSocket connector, event log forwarding, wait timeout, and runtime services normalization.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_openclaw_gateway_runtime.py -q`

Expected: FAIL because runner execution is not implemented.

- [ ] **Step 3: Implement runner**

Implement `connect.challenge -> req connect -> req agent -> req agent.wait`, event collection, timeout handling, and result normalization.

- [ ] **Step 4: Run tests to verify green**

Run: `uv run pytest tests/contract/test_openclaw_gateway_runtime.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add packages/runtimes/openclaw_gateway tests/contract/test_openclaw_gateway_runtime.py && git commit -m "feat: add openclaw gateway runner"`

### Task 4: Registry and Metadata

**Files:**
- Modify: `packages/runtimes/registry.py`
- Modify: `tests/contract/test_step14_runtime_adapters.py`
- Modify: `docs/guides/runtime-provider-model-design.md`

- [ ] **Step 1: Write failing tests**

Assert `get_runtime_adapter("openclaw_gateway")` returns a real adapter and metadata reports environment test support.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_step14_runtime_adapters.py tests/contract/test_openclaw_gateway_runtime.py -q`

Expected: FAIL while registry still returns `UnavailableRuntimeAdapter`.

- [ ] **Step 3: Register adapter and update docs**

Import `OpenClawGatewayRuntimeAdapter`, add it to `_ADAPTERS`, and update docs that previously called it unimplemented.

- [ ] **Step 4: Run tests to verify green**

Run: `uv run pytest tests/contract/test_step14_runtime_adapters.py tests/contract/test_openclaw_gateway_runtime.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

Run: `git add packages/runtimes/registry.py tests/contract/test_step14_runtime_adapters.py docs/guides/runtime-provider-model-design.md && git commit -m "feat: register openclaw gateway runtime"`

### Task 5: UI and CLI Compatibility

**Files:**
- Modify: `cli/commands/agent.py` or CLI tests only if current config JSON path already covers OpenClaw.
- Modify: `ui/src/utils/runtimeModels.ts` or UI tests only if current behavior conflicts with OpenClaw no-model defaults.

- [ ] **Step 1: Inspect current UI/CLI paths**

Confirm whether existing agent config JSON and runtime selection already cover OpenClaw.

- [ ] **Step 2: Add focused tests only for gaps**

Add or adjust tests for OpenClaw runtime selection/config if current coverage is missing.

- [ ] **Step 3: Run UI/CLI tests**

Run: `uv run pytest cli/tests/test_agent_commands.py -q` and `npm test -- runtime-models.test.ts`

- [ ] **Step 4: Commit if changes were needed**

Run: `git add cli ui && git commit -m "test: cover openclaw gateway ui cli paths"`

### Task 6: Final Verification

**Files:**
- All OpenClaw implementation files.

- [ ] **Step 1: Run Python verification**

Run: `uv run ruff format --check packages tests && uv run ruff check packages tests && uv run pytest tests/contract/test_openclaw_gateway_runtime.py tests/contract/test_step14_runtime_adapters.py -q`

- [ ] **Step 2: Run type verification**

Run: `uv run pyright packages/runtimes`

- [ ] **Step 3: Check git status and summarize commits**

Run: `git status --short --branch`

