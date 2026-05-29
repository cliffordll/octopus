# Step 21 Bug Ledger

本文件是 Step 21 的唯一 Bug 清单。所有最小闭环审查、调试和代码复查发现的问题必须先记录到这里，再决定修复或排期。

## 状态说明

- `open`：已确认存在，尚未处理。
- `in_progress`：正在修复或验证。
- `fixed`：已修复并有验证证据。
- `deferred`：不阻塞最小闭环，已排入后续 Step。
- `invalid`：复查后确认不是 Bug，必须记录原因。

## 严重级别

- `P0`：阻断最小闭环，必须在 Step 21 修复或说明外部阻塞。
- `P1`：影响核心调试/执行路径，优先在 Step 21 修复。
- `P2`：不阻断闭环，但会影响后续功能开发或兼容性。
- `P3`：文档、提示、可维护性或低风险问题。

## Bug 清单

| ID | 状态 | 级别 | 阻塞闭环 | 标题 | 归属 | 验证证据 |
| --- | --- | --- | --- | --- | --- | --- |
| BUG-21-001 | open | P1 | 待确认 | 智能体说明文件右侧内容显示为空需确认 server 读取语义 | Step 21 | 待复现 |
| BUG-21-002 | fixed | P1 | 是 | Python instructions bundle 缺少上游 reconcile/export 行为，可能把 legacy/default 内容落为空文件 | Step 21 | `pytest ...::test_agent_instructions_file_read_reconciles_legacy_prompt_template -q` |
| BUG-21-003 | open | P2 | 否 | 本地测试环境中 instructions bundle DELETE 文件出现 Windows PermissionError | Step 21 | `pytest tests/contract/test_step17_agent_instructions.py -q` |
| BUG-21-004 | fixed | P3 | 否 | 文档规范与上游兼容命名存在冲突，需要明确允许保留的外部契约名称 | Step 21 | `CLAUDE.md` 已补充兼容契约例外 |
| BUG-21-005 | open | P2 | 否 | agents route 和核心 service 文件偏大，需按职责拆分审查 | Step 21/25 | 文件规模与职责扫描 |
| BUG-21-006 | open | P3 | 否 | 部分 Step TASK 状态与实际开发进度不一致 | Step 21 | Step TASK 状态扫描 |
| BUG-21-007 | fixed | P1 | 否 | `/api/health` 端点未注册，README 验证步骤无法执行 | Step 21 | `pytest tests/contract/test_step21_health.py -q` |
| BUG-21-008 | fixed | P1 | 否 | issue 响应缺 `cancelledAt` 字段，与上游 schema 列 `cancelled_at` 与 type 字段 `cancelledAt` 不一致 | Step 21 | `pytest tests/contract/test_step21_issue_cancelled_at.py -q` |
| BUG-21-009 | fixed | P1 | 是 | issue 状态翻转不自动写 `started_at` / `completed_at` / `cancelled_at`（上游 `applyStatusSideEffects` 行为缺失） | Step 21 | `pytest tests/contract/test_step21_issue_status_timestamps.py -q` |
| BUG-21-010 | fixed | P1 | 是 | Windows 上 CLI-based runtime（codex_local / opencode_local / claude_local / process）`asyncio.create_subprocess_exec` 抛 `FileNotFoundError`，chat sync 直接 500 | Step 21 | `pytest tests/contract/test_step14_runtime_adapters.py -q` 23 passed + opencode/big-pickle 端到端 chat assistant reply OK |

## 记录模板

复制下面模板并分配下一个 `BUG-21-NNN` 编号：

- 状态：
- 严重级别：
- 是否阻塞最小闭环：
- 影响范围：
- 复现步骤：
- 预期行为：
- 实际行为：
- 初步根因：
- 处理归属：
- 修复记录：
- 验证证据：

### BUG-21-001: 智能体说明文件右侧内容显示为空需确认 server 读取语义

- 状态：open
- 严重级别：P1
- 是否阻塞最小闭环：待确认。若默认 instructions 文件无法读取真实内容，会影响 agent 调试与说明文件编辑闭环。
- 影响范围：Agent instructions bundle UI、server `instructions-bundle` 文件读取接口、默认 instructions 初始化/materialization 行为。
- 复现步骤：
  1. 打开某个 agent 的 instructions bundle 页面。
  2. 左侧文件列表可见文件 metadata，例如 `path/size/editable/isEntryFile`。
  3. 点击文件后观察右侧编辑区内容。
  4. 对 `SOUL.md`、`TOOLS.md`、`MEMORY.md`、`AGENTS.md` 或新建文件分别确认读取结果。
- 预期行为：文件列表接口只返回 metadata；右侧内容必须由 `GET /instructions-bundle/file?path=xxx` 返回的 `content` 决定。已有默认文件如果 server 已初始化正文，应返回真实内容；新建文件允许返回空字符串。
- 实际行为：右侧显示空内容时，UI 只是展示 server 文件读取接口返回结果；若接口返回 `{ "content": "" }`，UI 不会自行填默认内容，也不会再从 `agentRuntimeConfig.promptTemplate` 兜底伪造内容。
- 初步根因：
  - `GET /instructions-bundle` 只返回 metadata，本身不包含正文，这是预期行为。
  - 对应 `GET /instructions-bundle/file?path=xxx` 可能实际返回空字符串。
  - 点击 `+` 新建文件时只输入文件名并创建 `{ "path": "...", "content": "" }`，新文件为空是预期行为。
  - 某些默认文件在 mock/test 或真实初始化中可能本来就是空内容。
  - 如果 `SOUL.md`、`TOOLS.md`、`MEMORY.md` 等默认文件也为空，需要确认 server 默认 instructions 写入/materialization 是否缺失。
  - 代码审查已发现 BUG-21-002：Python 实现缺少上游 `reconcileBundle/exportFiles` 语义，且入口文件缺失时会写空文件。
- 处理归属：Step 21 先复现并确认 server 响应；若是默认 instructions 初始化缺口，按阻塞程度在 Step 21 修复或排入 Step 17/14 相关 instructions/materialization 后续。
- 修复记录：待处理。
- 验证证据：待补充具体请求、响应和涉及文件路径。

### BUG-21-002: Python instructions bundle 缺少上游 reconcile/export 行为，可能把 legacy/default 内容落为空文件

- 状态：fixed
- 严重级别：P1
- 是否阻塞最小闭环：是。agent instructions 是最小闭环中 agent 行为配置和调试的重要入口；默认文件被空内容覆盖会导致 UI 显示空、runtime 读取空说明、调试误判为 UI 问题。
- 影响范围：`GET /api/agents/{id}/instructions-bundle`、`GET /api/agents/{id}/instructions-bundle/file`、`PATCH /api/agents/{id}/instructions-bundle`、legacy `promptTemplate` 迁移、managed instructions 初始化。
- 复现步骤：
  1. 创建或准备一个 local runtime agent，存在 legacy `agentRuntimeConfig.promptTemplate`，但没有 `instructionsRootPath` 或 managed bundle 文件。
  2. 调用 `GET /api/agents/{id}/instructions-bundle` 或 `GET /api/agents/{id}/instructions-bundle/file?path=SOUL.md`。
  3. 或调用 `PATCH /api/agents/{id}/instructions-bundle`，让 server 创建 managed bundle entry 文件。
  4. 观察 `SOUL.md` 是否由 legacy/default 内容填充，还是被创建为空文件。
- 预期行为：对齐上游。读取 bundle/file 前先 reconcile bundle；需要 writable managed bundle 时，从 legacy `instructionsFilePath`/`promptTemplate` 或现有 bundle export 内容填充 entry 文件；`PATCH instructions-bundle` 在 root 为空或 entry 缺失时应写入导出的默认/legacy 内容，而不是直接写空文件。
- 实际行为：
  - Python `AgentInstructionsService.get_bundle` 仅返回 `_bundle(row)`，未执行 reconcile 或持久化修正。
  - Python `AgentInstructionsService.read_file` 仅调用 `_read_file(row, relative_path)`，未执行 reconcile。
  - Python `update_bundle` 在 entry 文件不存在时执行 `entry_path.write_text("", encoding="utf-8")`，会创建空入口文件。
- 初步根因：
  - 上游 route 在 `GET /agents/:id/instructions-bundle` 和 `GET /agents/:id/instructions-bundle/file` 前调用 `instructions.reconcileBundle(existing)` 并持久化结果。证据：`D:\coding\rudder\server\src\routes\agents.management-routes.ts:637`、`:704`。
  - 上游 `reconcileBundle` 会在 managed/no-root/legacy prompt 情况下调用 `ensureWritableBundle`，后者读取 legacy instructions 并写入 entry 文件。证据：`D:\coding\rudder\server\src\services\agent-instructions.ts:490`、`:550`、`:578`。
  - 上游 `updateBundle` 会先 `exportFiles(agent)`，root 为空或 entry 缺失时写入 exported files。证据：`D:\coding\rudder\server\src\services\agent-instructions.ts:620`-`:628`。
  - Python 对应代码缺少这些分支，证据：`server/services/agent_instructions.py:159`-`:163`、`:195`-`:198`、`:230`-`:236`。
- 处理归属：Step 21。应先加 contract/workflow 复现测试，再按上游 reconcile/export 语义修复。
- 修复记录：已补齐 Python `AgentInstructionsService` 的最小 reconcile/export 行为：读取 bundle/file 前对 managed legacy promptTemplate 进行 materialization；`PATCH instructions-bundle` 在 root 为空或 entry 缺失时复用导出内容，而不是直接写空文件。
- 验证证据：新增测试 `test_agent_instructions_file_read_reconciles_legacy_prompt_template`，先失败为 `404 != 200`，修复后 `.venv\Scripts\pytest.exe tests\contract\test_step17_agent_instructions.py::test_agent_instructions_file_read_reconciles_legacy_prompt_template -q` 通过。

### BUG-21-003: 本地测试环境中 instructions bundle DELETE 文件出现 Windows PermissionError

- 状态：open
- 严重级别：P2
- 是否阻塞最小闭环：否。影响自动化验证和 instructions 文件删除路径，但不阻塞组织、agent、说明读取和执行调试闭环。
- 影响范围：`DELETE /api/agents/{id}/instructions-bundle/file`、`tests/contract/test_step17_agent_instructions.py::test_agent_instructions_bundle_read_write_delete_and_activity`。
- 复现步骤：
  1. 运行 `.venv\Scripts\pytest.exe tests\contract\test_step17_agent_instructions.py -q`。
  2. 测试先创建 `notes/PLAYBOOK.md`。
  3. 调用 DELETE instructions file 接口。
- 预期行为：server 删除 bundle 内非 entry 文件并返回更新后的 bundle。
- 实际行为：当前 Windows 本地环境抛出 `PermissionError: [WinError 5] 拒绝访问`，位置为 `server/services/agent_instructions.py` 中 `target.unlink()`。
- 初步根因：待查。当前环境已多次出现 `.pytest_cache`、`pytest-tmp`、运行时生成文件删除权限异常；需要区分是本地权限/杀软/文件句柄问题，还是 server 删除逻辑缺少 Windows 兼容处理。
- 处理归属：Step 21 继续调查；若确认是 server 行为缺陷则修复，若确认是本地环境权限限制则记录验证替代路径。
- 修复记录：待处理。
- 验证证据：`.venv\Scripts\pytest.exe tests\contract\test_step17_agent_instructions.py -q` 中 1 个 DELETE 权限失败；新增 legacy reconcile 测试已单独通过。

### BUG-21-004: 文档规范与上游兼容命名存在冲突，需要明确允许保留的外部契约名称

- 状态：fixed
- 严重级别：P3
- 是否阻塞最小闭环：否。
- 影响范围：`CLAUDE.md` 命名规范、步骤文档中的上游证据路径、runtime env/context、organization skill bundled source key/label。
- 复现步骤：
  1. 阅读 `CLAUDE.md` 中“项目内禁止出现上游项目名”的规范。
  2. 执行全局搜索 `rg "rudder|RUDDER|Rudder"`。
  3. 对比命中项：`RUDDER_*` env、`rudderWorkspace` context、`rudder/<slug>` skill key、`D:\coding\rudder` 上游证据路径、`Bundled by Rudder` 展示文案。
- 预期行为：文档应区分“禁止在普通说明/命名中泄漏上游项目名”和“为上游兼容必须保留的外部契约字符串”。兼容字段不能被误改。
- 实际行为：当前规范表述过于绝对，和已实现的上游兼容契约存在冲突；直接批量替换会破坏 runtime/env、workspace context、skill key 或测试契约。
- 初步根因：项目定位清理后，规范没有把“外部兼容契约名”列为例外。
- 处理归属：Step 21 文档审查。需要修订规范或补充例外清单，再决定哪些文档描述可以改成“上游参考路径”而不影响证据可追溯。
- 修复记录：已更新 `CLAUDE.md`，把普通文档/命名禁用上游项目名与外部兼容契约字符串区分开，明确 `RUDDER_*`、`rudderWorkspace`、`rudder/<slug>` 等兼容字符串不得因命名清理擅自改动。
- 验证证据：全局 `rg "rudder|RUDDER|Rudder"` 命中项经分类，runtime env/context、organization skills key/provider、步骤文档上游证据路径和测试 fixture 属于兼容证据或待单独审查项。

### BUG-21-007: `/api/health` 端点未注册，README 验证步骤无法执行

- 状态：fixed
- 严重级别：P1
- 是否阻塞最小闭环：否。但 README 启动验证步骤无法执行，外层反向代理 / 容器编排 health probe 无入口。
- 影响范围：`server/routes/__init__.py`、`ui/README.md` 启动指南、外层 health 探针、上游 AGENTS.md §4 标准入口。
- 复现步骤：
  1. 启动 `uv run server`。
  2. `curl http://127.0.0.1:8000/api/health`。
- 预期行为：200，返回 `{"status": "ok"}` 或上游 health 响应的子集。
- 实际行为（修复前）：404 Not Found，无任何 health 路由被注册。
- 初步根因：上游 `upstream-reference/rudder/server/src/bootstrap/register-api-routes.ts:40` 用 `api.use("/health", healthRoutes(...))` 注册；Octopus `server/routes/__init__.py` 缺等价注册。
- 处理归属：Step 21。
- 修复记录：新增 `packages/shared/api_paths/health.py` 常量、`server/routes/health.py` 路由、在 `server/routes/__init__.py` 注册。Octopus 范围内最小兼容响应 `{"status": "ok"}`；上游完整字段（version / instanceId / localEnv / runtimeOwnerKind / deploymentMode 等）在 Octopus 尚无对应概念，留到对应 step 实施时再扩展。
- 验证证据：`uv run pytest tests/contract/test_step21_health.py -q` 2 passed；四步验证 `ruff check / ruff format --check / pyright` 全绿。

### BUG-21-008: issue 响应缺 `cancelledAt` 字段

- 状态：fixed
- 严重级别：P1
- 是否阻塞最小闭环：否。但 UI / 外部消费方读取 cancelled issue 时无法拿到取消时间；与上游响应 schema 不一致。
- 影响范围：`packages/shared/types/issue.py`、`server/services/issues.py`、所有消费 `GET /api/issues/{id}` 的客户端。
- 复现步骤：
  1. 准备一个 `status=cancelled` 的 issue（DB schema 已有 `cancelled_at` 列）。
  2. `curl http://127.0.0.1:8000/api/issues/{id}`。
- 预期行为：响应字段包含 `cancelledAt: string | null`，与上游 `packages/shared/src/types/issue.ts:141` 一致。
- 实际行为（修复前）：响应字段列表只有 `startedAt`、`completedAt`，**无 `cancelledAt`**；UI 显示「未取消」也无法据此判断。
- 初步根因：DB schema `packages/database/schema/issues.py:143` 列已存在；type 与 service 序列化遗漏。`packages/shared/types/issue.py:36-37` 只声明 `startedAt`/`completedAt`；`server/services/issues.py:414-415` 序列化漏字段。
- 处理归属：Step 21。
- 修复记录：`IssueDetail.cancelledAt` 加入 type；`_to_detail` 增加 `cancelledAt=row.cancelled_at.isoformat() if row.cancelled_at else None`。`IssueListItem` 是列表精简形态，按上游 `IssueDetail` 单独保留 timestamps，列表不带，不在本次修改范围。
- 验证证据：`uv run pytest tests/contract/test_step21_issue_cancelled_at.py tests/contract/test_step8_issue_management.py -q` 12 passed；ruff / pyright 全绿。

### BUG-21-009: issue 状态翻转不自动写时间戳

- 状态：fixed
- 严重级别：P1
- 是否阻塞最小闭环：是。issue 时间戳是闭环可见性与下游 governance（cost/budget/activity）归集所需的关键 evidence。
- 影响范围：`server/services/issues.py`、`GET/PATCH /api/issues/{id}`、依赖 `startedAt` / `completedAt` / `cancelledAt` 字段的 UI 与报表。
- 复现步骤：
  1. PATCH 一个 issue 到 `status=in_progress`，观察 `startedAt` 字段。
  2. PATCH 到 `status=done`，观察 `completedAt` 字段。
  3. PATCH 到 `status=cancelled`，观察 `cancelledAt` 字段。
- 预期行为：与上游 `upstream-reference/rudder/server/src/services/issues.helpers.ts:64-80` `applyStatusSideEffects` 对齐：
  - 转 `in_progress` 且 patch 没显式 startedAt → 写当前时间到 `started_at`。
  - 转 `done` → 写当前时间到 `completed_at`（无论旧值）。
  - 转 `cancelled` → 写当前时间到 `cancelled_at`（无论旧值）。
- 实际行为（修复前）：`server/services/issues.py:228` 直接 `await update_issue(session, issue_id, values)`，`values` 只含用户传入的字段，三个时间戳永远不会被自动写入；live 测试 PATCH 状态多次后字段全为 null。
- 初步根因：Python 实现没有 port 上游 `applyStatusSideEffects` helper。
- 处理归属：Step 21。
- 修复记录：在 `server/services/issues.py` 新增 `_apply_status_side_effects(values)` helper，行为对齐上游；在 `update_issue` 调用 `update_issue(session, ...)` 之前调用此 helper，使 review_decision / reopen 等路径导致的状态翻转同样命中。
- 验证证据：新增 `tests/contract/test_step21_issue_status_timestamps.py` 4 个测试覆盖 in_progress / done / cancelled 三种翻转与 status 未变更不打点；`uv run pytest tests/contract/test_step21_issue_status_timestamps.py tests/contract/test_step8_issue_management.py tests/contract/test_step21_issue_cancelled_at.py -q` 14 passed；ruff / pyright 全绿。

### BUG-21-010: Windows 下所有 CLI-based runtime 无法启动子进程

- 状态：fixed
- 严重级别：P1
- 是否阻塞最小闭环：是。codex_local / opencode_local / claude_local 三个真实 LLM adapter 全部不可用，chat sync 直接 500，闭环断裂。
- 影响范围：`packages/runtimes/codex_local/runner.py`、`packages/runtimes/opencode_local/runner.py`、`packages/runtimes/claude_local/runner.py`、`packages/runtimes/process/runner.py`、所有依赖 chat / heartbeat 执行的端到端流程。
- 复现步骤：
  1. 在 Windows 上 `uv run server`。
  2. 创建 codex_local 或 opencode_local agent + chat。
  3. `POST /api/chats/{id}/messages { body: "..." }`。
- 预期行为：subprocess 启动成功；adapter 调用 LLM 并返回 assistant reply（或 4xx/5xx with detail 如认证失败）。
- 实际行为（修复前）：500 Internal Server Error。`asyncio.create_subprocess_exec("codex", ...)` 在 Windows 上抛 `FileNotFoundError [WinError 2]`，因为 `_winapi.CreateProcess` 不会自动追加 PATHEXT 解析 `codex.CMD` / `codex.ps1` 等 wrapper；route 只 catch `ChatAvailabilityError / ValueError / RuntimeError`，`FileNotFoundError` 透出导致 500。
- 初步根因：`test-environment` helper (`packages/runtimes/environment.py:100`) 正确使用 `shutil.which` 解析路径；但 4 个 runner 直接把命令名传给 subprocess。Linux / macOS 上无后缀可执行能直接 launch，Windows 上 CMD 包装失败。
- 处理归属：Step 21。
- 修复记录：
  - `packages/runtimes/environment.py` 新增 `resolve_runtime_executable(command) -> str` helper：best-effort 用 `shutil.which` 解析；找不到时返回原值，让 subprocess 走原有错误路径（保留 monkeypatch 测试兼容）。
  - 4 个 runner（codex_local / opencode_local / claude_local / process）在 `create_subprocess_exec` 前用该 helper 解析路径。
- 验证证据：
  - `uv run pytest tests/contract/test_step14_runtime_adapters.py -q` 23 passed
  - Live：opencode_local agent + `agentRuntimeConfig.model="opencode/big-pickle"`，`POST /api/chats/{id}/messages` 真实返回 assistant reply "OK"
  - ruff / pyright 全绿

### BUG-21-005: agents route 和核心 service 文件偏大，需按职责拆分审查

- 状态：open
- 严重级别：P2
- 是否阻塞最小闭环：否。但继续叠加功能会增加回归风险。
- 影响范围：`server/routes/agents.py`、`server/services/heartbeat.py`、`server/services/chats.py`、`server/services/agents.py`、`server/services/workspaces.py`、`server/services/agent_instructions.py`。
- 复现步骤：
  1. 按文件大小扫描 `server/routes`、`server/services`、`packages/runtimes`。
  2. 检查 `server/routes/agents.py` 是否同时承载 agent CRUD、instructions、runtime metadata、skills、heartbeat/run routes。
  3. 检查核心 service 是否混合调度、恢复、执行、转换、workspace 处理等多类职责。
- 预期行为：route 层只做路由、参数、validator、context 和响应；service 层按领域内聚，跨领域能力通过清晰接口协作。
- 实际行为：部分文件已明显偏大，尤其 `server/routes/agents.py` 和 `server/services/heartbeat.py`；当前尚未确认所有职责都混杂，但需要在 Step 21/25 做拆分审查，避免后续继续堆叠。
- 初步根因：Step 11-20 连续补齐 agent/runtime/run/workspace/observability，多个相关能力都落在既有文件中。
- 处理归属：Step 21 先审查并拆分低风险路由；涉及恢复/兼容矩阵的深层 service 拆分可排入 Step 25 hardening。
- 修复记录：本轮已修复一处明确封装问题：`RunIntelligenceService` 不再调用 `HeartbeatService._to_run/_to_event` 私有方法，改为公共转换函数。
- 验证证据：文件规模扫描显示 `server/services/heartbeat.py`、`server/services/chats.py`、`server/services/agents.py`、`server/services/workspaces.py`、`server/routes/agents.py` 均为当前最大文件之一。

### BUG-21-006: 部分 Step TASK 状态与实际开发进度不一致

- 状态：open
- 严重级别：P3
- 是否阻塞最小闭环：否。
- 影响范围：`docs/step-*/TASK.md` 的状态字段、开发进度判断、后续排期。
- 复现步骤：
  1. 扫描所有 `docs/step-*/TASK.md` 的标题和 `状态`。
  2. 对比 `docs/FEATURE.md` 和当前已实现代码/测试。
- 预期行为：已完成并合入的步骤应在 `TASK.md` 中标记为已完成或保留准确的阶段性状态；待开发步骤不应已有大量代码实现却仍无说明。
- 实际行为：Step 20 已完成并合入，但 `docs/step-20-observability/TASK.md` 仍标为“开发中”；Step 16/17 等历史步骤状态也需要结合实现范围复核。
- 初步根因：步骤连续开发和重排后，部分 `TASK.md` 状态未同步更新。
- 处理归属：Step 21 文档审查。
- 修复记录：已将 Step 20 状态修正为“已完成”；其余步骤待逐项对照实现范围后再修。
- 验证证据：Step TASK 状态扫描输出显示 Step 20 为“开发中”，本轮已修正。
