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
| BUG-21-011 | fixed | P1 | 否 | issue 创建后 `identifier` / `issueNumber` 永远 null，UI 显示「未编号」，链接如 `/{prefix}/issues/{identifier}` 无法构造 | Step 21 | `pytest tests/contract/test_step21_issue_identifier.py -q` 2 passed + live POST /api/orgs/{id}/issues 返回 identifier="950276-1" |
| BUG-21-012 | fixed | P1 | 否 | approval `decidedByUserId` 缺默认 `"board"`，与上游 `resolveApprovalSchema.decidedByUserId.default("board")` 不一致 | Step 21 | `pytest tests/contract/test_step21_approval_resolution.py -q` 6 passed |
| BUG-21-013 | fixed | P1 | 是 | approval 缺 `resolvableStatuses` 前置检查，已 `approved`/`rejected` 仍可改 status，破坏 approval gate 不变量 | Step 21 | `pytest tests/contract/test_step21_approval_resolution.py -q` 含 3 个覆盖 idempotent/同状态/异常状态拒绝 |
| BUG-21-014 | fixed | P1 | 否 | chat detail `latestReplyPreview` 永远为空，与 messenger threads preview 不一致；UI 列表预览失效 | Step 21 | `pytest tests/contract/test_step21_chat_latest_reply_preview.py -q` 4 passed |
| BUG-21-015 | fixed | P2 | 否 | 组织技能列表向 UI 暴露旧品牌 key 和展示文案 | Step 21 | `test_org_skill_list_seeds_bundled_skills` 期望已改为 `skills/<slug>` 与 `built-in` |
| BUG-21-016 | fixed | P2 | 否 | 组织技能 fileInventory 只返回 SKILL.md，UI 无法展示 references/scripts/templates | Step 21 | contract 测试已覆盖递归 inventory |
| BUG-21-017 | fixed | P2 | 否 | approval comments / approval-issue 关联 3 个端点 + `approval_comments` 表 + `addApprovalCommentSchema` validator 全部缺失，上游 `approvals.ts:306,645,657` 有 | Step 21 | `pytest tests/contract/test_step21_approval_comments.py -q` 5 passed |
| BUG-21-018 | fixed | P1 | 是 | chat sync message 只把当前 user body 作为 promptTemplate，不传 conversation 历史，assistant 无 multi-turn 记忆；与上游 `buildPrompt` 行为不一致 | Step 21 | `pytest tests/contract/test_step21_chat_history_prompt.py -q` 3 passed |
| BUG-21-019 | invalid | P2 | 否 | `GET /api/orgs/{orgId}/messenger/system/{threadKind}` 早前误报 404 | Step 21 | 重测 `failed-runs`/`budget-alerts`/`join-requests` 三个上游真实 kind 全部 200；之前用 `governance/onboarding/...` 等无效 kind 探测才出现 404，属于测试侧错误 |
| BUG-21-020 | fixed | P3 | 否 | codex runner `clear_inherited_blocking_proxy_env` 的 explicit_keys 只收集 config.env 的键，workspace `context.env` 显式设的代理会被误删 | Step 21 | 多代理审查发现；`pytest tests/contract/test_step14_runtime_adapters.py -q` 回归通过 |
| BUG-21-021 | fixed | P2 | 否 | chat 多轮 prompt envelope 的 contextLinks 缺 entity hydration 字段（label/identifier/status/description/priority），与上游 `buildPrompt` contextSummary 不一致 | Step 21 | `pytest tests/contract/test_step21_chat_history_prompt.py::test_prompt_context_links_include_hydrated_entity_fields -q` |

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
  3. 对比命中项：`RUDDER_*` env、`rudderWorkspace` context、`D:\coding\rudder` 上游证据路径、旧组织技能 key 和 `Bundled by Rudder` 展示文案。
- 预期行为：文档应区分“禁止在普通说明/命名中泄漏上游项目名”和“为上游兼容必须保留的外部契约字符串”。兼容字段不能被误改。
- 实际行为：当前规范表述过于绝对，和已实现的上游兼容契约存在冲突；直接批量替换会破坏 runtime/env、workspace context、skill key 或测试契约。
- 初步根因：项目定位清理后，规范没有把“外部兼容契约名”列为例外。
- 处理归属：Step 21 文档审查。需要修订规范或补充例外清单，再决定哪些文档描述可以改成“上游参考路径”而不影响证据可追溯。
- 修复记录：已更新 `CLAUDE.md`，把普通文档/命名禁用上游项目名与外部兼容契约字符串区分开，明确 `RUDDER_*`、`rudderWorkspace` 等兼容字符串不得因命名清理擅自改动。组织技能 key 已在 BUG-21-015 中改为项目内置 `skills/<slug>` 语义。
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

### BUG-21-011: issue 创建后 identifier / issueNumber 永远 null

- 状态：fixed
- 严重级别：P1
- 是否阻塞最小闭环：否。issue 仍可创建和流转，只是缺少人类可读编号。但 UI 显示「未编号」、上游链接模板（`/{prefix}/issues/{identifier}`）无法构造、列表搜索和 ticket 引用全部失效。
- 影响范围：`server/services/issues.py create_issue`、`packages/database/queries/organizations.py`、`packages/database/schema/organizations.py` 的 `issue_prefix` / `issue_counter` 列、所有引用 identifier 的 UI 与外部消费方。
- 复现步骤：
  1. `POST /api/orgs` 建组织。
  2. `POST /api/orgs/{orgId}/issues { title }` 创建 issue。
  3. `GET /api/issues/{id}`，观察 `identifier` 与 `issueNumber`。
- 预期行为：与上游 `upstream-reference/rudder/server/src/services/issues.ts:797-804` 对齐：
  - `UPDATE organizations SET issue_counter = issue_counter + 1 WHERE id = :org_id RETURNING issue_counter, issue_prefix` 原子自增。
  - 新 issue 写入 `issue_number = counter` 和 `identifier = f"{prefix}-{counter}"`。
- 实际行为（修复前）：`server/services/issues.py:187` 直接 `create_issue(session, values)`，values 不含 issue_number/identifier；DB 列 nullable，全部留 null。
- 初步根因：Python create_issue service 缺少 port 上游的 atomic counter increment + identifier 拼装。
- 处理归属：Step 21。
- 修复记录：
  - `packages/database/queries/organizations.py` 新增 `increment_issue_counter(session, org_id) -> tuple[int, str] | None`，单 SQL `UPDATE ... RETURNING` 原子自增并返回 `(new_counter, prefix)`。
  - `server/services/issues.py create_issue` 在 `create_issue(...)` 前调用 helper，设置 `values["issue_number"]` 和 `values["identifier"] = f"{prefix}-{number}"`。
  - 同时把 `_apply_status_side_effects(values)` 也加进 create 路径，对齐上游 `services/issues.ts:820-828` 在 insert 前 inline 复制的 same 时间戳逻辑。
- 验证证据：
  - `pytest tests/contract/test_step21_issue_identifier.py -q` 2 passed（覆盖单 org 自增 PAP-1/PAP-2/PAP-3 与跨 org 隔离）；
  - 同套 issue 测试 `pytest tests/contract/test_step8_issue_management.py tests/contract/test_step21_issue_cancelled_at.py tests/contract/test_step21_issue_status_timestamps.py -q` 14 passed 回归无破坏；
  - Live `POST /api/orgs/{orgId}/issues` 返回 `identifier="950276-1"`、`issueNumber=1`，第二次返回 `950276-2`、`issueNumber=2`；
  - ruff / pyright 全绿。
- 已知边界：当前 org 创建时的 `issue_prefix` 是 octopus 自己生成（取 org_id 首 6 位）；上游默认是固定 `"PAP"`。两边都是 issue prefix 来源问题，但不影响 identifier 拼装语义，作为独立调查项处理，不在本 bug 范围。

### BUG-21-012: approval `decidedByUserId` 缺默认值 `"board"`

- 状态：fixed
- 严重级别：P1
- 是否阻塞最小闭环：否。但 board actor approve/reject/request-revision 必须显式传字段；与上游契约不一致。
- 影响范围：`packages/shared/validators/approval.py`、`POST /api/approvals/{id}/{approve,reject,request-revision}` 三个端点；持久化的 `approvals.decided_by_user_id` 列。
- 复现步骤：`POST /api/approvals/{id}/approve` 传 `{}`，观察响应 `decidedByUserId`。
- 预期行为：与上游 `resolveApprovalSchema.decidedByUserId.default("board")`、`requestApprovalRevisionSchema.decidedByUserId.default("board")` 对齐（`upstream-reference/rudder/packages/shared/src/validators/approval.ts:15,23`），返回值含 `decidedByUserId="board"`。
- 实际行为（修复前）：`validate_resolve_approval`、`validate_request_approval_revision` 仅做类型校验，不 setdefault；响应 `decidedByUserId=null`。
- 初步根因：Octopus validator 没 port 上游 zod default。
- 处理归属：Step 21。
- 修复记录：`validate_resolve_approval` 在 type check 通过后构造 `dict(payload)` 并 `setdefault("decidedByUserId", "board")`，cast 后返回；`validate_request_approval_revision` 改为使用 `validate_resolve_approval` 返回值（之前丢弃返回）。
- 验证证据：`pytest tests/contract/test_step21_approval_resolution.py -q` 6 passed；`pytest tests/contract/test_step3_shared_contract.py -q` 36 passed（更新了 `test_validate_resolve_approval_empty_ok` 以反映新行为）；ruff / pyright 全绿。

### BUG-21-013: approval 缺 resolvable 状态前置检查

- 状态：fixed
- 严重级别：P1
- 是否阻塞最小闭环：是。破坏 approval 状态机不变量（上游 AGENTS.md §5「Approval gates for governed actions」）；已 approved/rejected 仍可被改 status，治理记录失真。
- 影响范围：`server/services/approvals.py::_resolve_approval`、`server/routes/approvals.py` 三个 resolve 路由；activity log 含错误的二次决策。
- 复现步骤：
  1. 创建 approval（status=pending）。
  2. `POST /approvals/{id}/approve {}` → status=approved。
  3. 再次 `POST /approvals/{id}/approve {}` 或 `POST /approvals/{id}/reject {}`。
- 预期行为：与上游 `services/approvals.ts:15,45-52` 对齐：
  - 同 target status：返回当前 row（idempotent，200，无副作用）。
  - 不同 terminal status（已 approved 后 reject 等）：抛 unprocessable，返回 422。
  - 只有 `pending` / `revision_requested` 才能转 approved/rejected/revision_requested。
- 实际行为（修复前）：service 直接 update row.status，无前置检查；任何状态下重复调用都成功。
- 初步根因：Python 实现 `_resolve_approval` 跳过了上游 `canResolveStatuses` 校验。
- 处理归属：Step 21。
- 修复记录：
  - `server/services/approvals.py` 新增 `_RESOLVABLE_APPROVAL_STATUSES = frozenset({"pending", "revision_requested"})`。
  - `_resolve_approval` 在 update 前检查 `current.status`：同 target → 直接返回 `_to_detail(current)`（idempotent 路径）；其他 → `raise ValueError("Only pending or revision requested approvals can be ...")`。
  - `server/routes/approvals.py` 三个 resolve route 把 service 调用包进 try/except ValueError → 422，保留 detail。
- 验证证据：`pytest tests/contract/test_step21_approval_resolution.py -q` 6 passed（覆盖 idempotent / 异常状态拒绝 / 从 revision_requested 决策）；`pytest tests/contract/test_step9_approval_management.py tests/workflows/test_step9_approval_workflow.py -q` 回归 32 passed；ruff / pyright 全绿。

### BUG-21-014: chat detail `latestReplyPreview` 永远为空

- 状态：fixed
- 严重级别：P1
- 是否阻塞最小闭环：否。但 UI chat 列表 / 详情显示「最新回复」永远空；与 messenger threads preview 不一致。
- 影响范围：`server/services/chats.py::_to_conversation`、`packages/database/queries/chats.py`、所有 chat detail/list 端点。
- 复现步骤：
  1. 创建 chat。
  2. 写入 assistant message（real chat sync flow 或直接 DB seed）。
  3. `GET /api/chats/{id}` 观察 `latestReplyPreview`。
- 预期行为：与上游 `services/chats.ts:280` + `listLatestReplyPreviews` 一致：取最新非-user role 且 trim 后非空的 message body，截断到 140 字符。
- 实际行为（修复前）：`_to_conversation` 硬编码 `"latestReplyPreview": None`，无论是否有 assistant 回复。
- 初步根因：octopus 实现遗漏了 latestReplyPreview hydrate 逻辑。
- 处理归属：Step 21。
- 修复记录：
  - `packages/database/queries/chats.py` 新增 `get_latest_incoming_message_preview(session, conversation_id) -> str | None`，对齐上游 `incomingMessagePreviewSql` filter：`role != 'user'`、`superseded_at IS NULL`，按 `created_at desc` 取首条；返回 trim 后值。
  - `server/services/chats.py::_to_conversation` 调用此 helper，截到 140 字符。
- 验证证据：`pytest tests/contract/test_step21_chat_latest_reply_preview.py -q` 4 passed（覆盖最新 assistant body / 忽略 user role / 140 截断 / 无 incoming message 时 null）；chat 套件 `pytest tests/contract/test_step11_chat_loop.py tests/contract/test_step16_chat_routes.py -q` 回归 8 passed；ruff / pyright 全绿。

### BUG-21-017: approval comments + approval-issue 关联端点/表全部缺失

- 状态：fixed
- 严重级别：P2
- 是否阻塞最小闭环：否。但 approval 协作中评论沟通 + approval-与-issue 关联查询完全用不了，UI 审批协作流程无法跑通。
- 影响范围：`approval_comments` 表、validator、3 个 HTTP 路由（`GET /api/approvals/{id}/issues`、`GET /api/approvals/{id}/comments`、`POST /api/approvals/{id}/comments`）、service 层、shared type 与 api_paths。
- 复现步骤：
  1. `GET /api/approvals/{id}/issues` → 404 (修复前 router 未注册)
  2. `GET /api/approvals/{id}/comments` → 404
  3. `POST /api/approvals/{id}/comments {body:"hi"}` → 404
- 预期行为：与上游 `upstream-reference/rudder/server/src/routes/approvals.ts:306,645,657` 三个路由 + `services/approvals.ts:241-278` (`listComments`/`addComment`) + `services/issue-approvals.ts:115-144` (`listIssuesForApproval`) + `packages/db/src/schema/approval_comments.ts` 表对齐。
- 实际行为（修复前）：路由未注册 → 404；service 无对应方法；DB 无 `approval_comments` 表；validator 无 `validate_add_approval_comment`。
- 处理归属：Step 21。
- 修复记录：
  - `packages/database/schema/approval_comments.py` 新表 `ApprovalComment`（id PK、org_id/approval_id/author_agent_id FK、author_user_id text、body text、created_at/updated_at），与上游 3 个 index 对齐。
  - `packages/database/migrations/versions/20260529_000014_approval_comments.py` Alembic 迁移。
  - `packages/database/schema/__init__.py` 导出 `ApprovalComment`。
  - `packages/database/queries/approvals.py` 新增 `list_approval_comments` / `create_approval_comment` / `list_issues_for_approval`（后者通过 `IssueApproval` join `Issue`，按 link 创建时间排序，对齐上游）。
  - `packages/shared/types/approval.py` 新增 `ApprovalComment` / `AddApprovalCommentPayload` TypedDict。
  - `packages/shared/validators/approval.py` 新增 `validate_add_approval_comment`（body 非空），对齐上游 `addApprovalCommentSchema = z.object({ body: z.string().min(1) })`。
  - `packages/shared/api_paths/approvals.py` 新增 `APPROVAL_ISSUES_PATH` 和 `APPROVAL_COMMENTS_PATH`。
  - `server/services/approvals.py` 新增 `list_issues_for_approval` / `list_comments` / `add_comment`；后者根据 actor_type 设 author_agent_id 或 author_user_id 并写 `approval.comment_added` activity，与上游一致。
  - `server/routes/approvals.py` 注册 3 个新路由；comments POST 走 actor identity，issues GET 走 organization scope（继承 `_get_approval_detail` 的 `assert_organization_access`）。
- 验证证据：
  - `pytest tests/contract/test_step21_approval_comments.py -q` 5 passed（空 list / 创建+列出 / 空 body 422 / linked issues / approval missing 404）；
  - `pytest tests/contract/ -q` 全套 287 passed 回归；
  - ruff / pyright 全绿。
- 已知边界：上游 `services/approvals.ts:254` 在 list/create 时通过 `instanceSettings.censorUsernameInLogs` 做 username redaction；Octopus 当前没 instance_settings 子系统，所以暂不复制 redaction 行为。需要时另起 hotfix。

### BUG-21-018: chat sync message 不传 conversation 历史，assistant 无 multi-turn 记忆

- 状态：fixed
- 严重级别：P1
- 是否阻塞最小闭环：是。chat 多轮对话不能保持上下文 → assistant 第二轮起完全失忆，最小闭环演示「对话」体验断裂。
- 影响范围：`server/services/chats.py::add_message_and_reply`、`promptTemplate` 协议、所有 chat-capable runtime adapter 行为可观察性。
- 复现步骤：
  1. 创建 chat + opencode_local 真 agent (`agentRuntimeConfig.model="opencode/big-pickle"`)。
  2. POST 第一条消息 "Reply only OK"，assistant 回 "OK"。
  3. POST 第二条 "What did I ask before?"，观察 assistant 是否记得 turn 1。
- 预期行为：与上游 `upstream-reference/rudder/server/src/services/chat-assistant.helpers.ts:154-208 buildPrompt` 对齐——adapter 收到的 `promptTemplate` 是 JSON envelope，包含 `conversation` 元信息、`contextLinks`、`recentMessages`（最近 12 条非 superseded message，包含当前 user message）。
- 实际行为（修复前）：`server/services/chats.py:660` 把 promptTemplate 直接设为 `payload["body"]`，adapter 看到的就是当前 user 一段文本——assistant 回 "No previous user message — this is the start of the conversation"。
- 初步根因：Python chat service 未 port 上游 buildPrompt 的 JSON envelope 构造逻辑。
- 处理归属：Step 21。
- 修复记录：
  - `server/services/chats.py` 新增 `_build_assistant_prompt(conversation, latest_user_message)` 私有 helper，构造与上游一致的 JSON envelope：`{conversation: {id,title,status,summary,planMode,issueCreationMode,preferredAgentId,routedAgentId,primaryIssueId}, contextLinks: [{entityType,entityId,metadata}], recentMessages: [{id,role,kind,status,body,structuredPayload}]}`，取 `list_messages` 后过滤 `superseded_at IS NULL`、`slice(-12)`，保底把刚 flush 的当前 user message 放尾部。
  - `add_message_and_reply` 在 adapter.execute 前调用此 helper，promptTemplate 改为 `json.dumps(envelope, ensure_ascii=False, indent=2)`，与上游 `JSON.stringify(..., null, 2)` 行为一致。
- 验证证据：
  - 新增 `tests/contract/test_step21_chat_history_prompt.py` 3 个测试：首轮只含当前 user / 第二轮含 turn 1 user+assistant+turn 2 user / 15 轮后只保留最近 12 条且 latest 必在末尾。
  - `pytest tests/contract/test_step21_chat_history_prompt.py tests/contract/test_step11_chat_loop.py tests/contract/test_step16_chat_assistant_routes.py tests/contract/test_step21_chat_latest_reply_preview.py -q` 14 passed。
  - `test_step11_chat_loop.py:198` 旧断言 `captured["prompt"] == b"raw body"` 同步更新为 JSON envelope 断言，注释引用上游 file:line。
  - `pytest tests/contract/ -q` 全套 290 passed。
  - ruff / pyright 全绿。
- 已知边界：上游 buildPrompt 还把 message attachments 拼进 envelope；当前 Octopus chat attachments 仍归 Step 18，未引入 attachment hydration，本修复留位 `attachments` 字段为空（adapter 收到 envelope 时若没有 attachments key 仍可降级；上游 buildPrompt 同样会输出空数组）。下一步若引入 chat attachments 再补 attachments hydration。

### BUG-21-019: messenger system thread 404 误报

- 状态：invalid
- 严重级别：P2
- 是否阻塞最小闭环：否。
- 影响范围：`GET /api/orgs/{orgId}/messenger/system/{threadKind}` 路由。
- 复现步骤（误报）：先前 probe 使用 `governance`/`onboarding`/`workspace`/`run`/`automation`/`default`/`system` 等 kind 名称全部 404。
- 预期行为：仅 `failed-runs` / `budget-alerts` / `join-requests` 三个 kind 合法，与上游 `packages/shared/src/constants.ts:200 MESSENGER_SYSTEM_THREAD_KINDS` 完全对齐；Octopus `packages/shared/constants/messenger.py:18` 已声明相同集合，service 也实现完整。
- 实际行为：重测 `failed-runs` / `budget-alerts` / `join-requests` 都返回 200，body 含 `summary`+`messages` 结构。先前结论是测试侧用错 kind。
- 处理归属：无需修复，本条仅作记录避免再被误读。
- 修复记录：无。
- 验证证据：live `GET /api/orgs/{id}/messenger/system/failed-runs` 等三个端点 200。

### BUG-21-020: codex runner blocking-proxy 清理误删 workspace 显式代理

- 状态：fixed
- 严重级别：P3
- 是否阻塞最小闭环：否。仅在 workspace `context.env` 显式注入了 sandbox blackhole 代理（`127.0.0.1:9` 系列）时才触发，实践概率极低；但逻辑不严谨，应修正。
- 影响范围：`packages/runtimes/codex_local/runner.py` 的 env 组装。
- 复现步骤：
  1. heartbeat 流程通过 workspace context 的 `env` payload 注入 `HTTP_PROXY=http://127.0.0.1:9`（即 `context.env`）。
  2. codex runner 执行时该值会被 `clear_inherited_blocking_proxy_env` 当成「继承自 os.environ 的非显式值」删除。
- 预期行为：与 helper docstring「Explicit agent runtime env always wins and is left untouched」一致——`config.env` 和 `context.env` 显式注入的代理都视为 explicit，不删。
- 实际行为（修复前）：`explicit_env_keys` 只从 `config.get("env")` 收集键，`context.env` 的键未纳入；导致 workspace 显式代理被误删。
- 初步根因：多代理审查（Explore agent）发现。`runner.py:49-51` 合并 `context.env` 后未把其键加入 `explicit_env_keys`。
- 处理归属：Step 21。
- 修复记录：`if context.env:` 分支内增加 `explicit_env_keys.update(context.env)`，再 `env.update`，最后才 `clear_inherited_blocking_proxy_env`。
- 验证证据：`pytest tests/contract/test_step14_runtime_adapters.py -q` 回归通过；ruff / pyright 全绿。
- 说明：仅 codex_local runner 使用 proxy 清理逻辑，其它 runner（opencode/claude/process）不涉及，无需同步。

### BUG-21-021: chat 多轮 prompt 的 contextLinks 缺 entity hydration 字段

- 状态：fixed
- 严重级别：P2
- 是否阻塞最小闭环：否。multi-turn 主功能（BUG-21-018）正常；但 runtime 收到的 context link 缺少所引用 issue/project/agent 的描述/状态/优先级，agent 无法据此推理。
- 影响范围：`server/services/chats.py::_build_assistant_prompt`、所有带 contextLinks 的 chat 对话发给 runtime 的 prompt envelope。
- 复现步骤：
  1. 创建带 contextLinks（如 issue）的 chat。
  2. 发消息触发 adapter，检查 promptTemplate JSON 里 contextLinks 字段。
- 预期行为：与上游 `chat-assistant.helpers.ts:158-166` contextSummary 一致——每个 link 含 `entityType`、`entityId`、`label`、`identifier`、`status`、`description`、`priority`。
- 实际行为（修复前）：BUG-21-018 写的 `_build_assistant_prompt` 只放了 `entityType`、`entityId`、`metadata`，丢弃了 `_hydrate_context_links` 已经查出的 entity 子字段。
- 初步根因：多代理审查发现。`_build_assistant_prompt` 的 contextLinks 列表推导式只取了 3 个字段。
- 处理归属：Step 21。
- 修复记录：新增模块级 `_context_link_summary(link)` helper，从 hydrated link 的 `entity` 字段提取 label/identifier/status/description/priority；`_build_assistant_prompt` 改为调用此 helper。`metadata` 字段移除（上游 contextSummary 不含 metadata，改为对齐 entity 字段）。
- 验证证据：新增 `tests/contract/test_step21_chat_history_prompt.py::test_prompt_context_links_include_hydrated_entity_fields`（seed 一个 issue 作 contextLink，断言 envelope 含全部 hydration 字段）；`pytest tests/contract/ -q` 全套 299 passed；ruff / pyright 全绿。

### BUG-21-022: 缺少上游 issue checkout 和 heartbeat-context 路由，任务执行缺少原子领取与紧凑上下文

- 状态：open
- 严重级别：P1
- 是否阻塞最小闭环：是。当前已能通过 assigned issue 自动 queued wakeup/run，但 runtime 只能依赖 payload 中的 `issueId`；缺少 checkout 会导致真实任务执行前没有上游式原子领取/执行锁，缺少 heartbeat-context 会导致 agent 无法稳定读取紧凑任务上下文。
- 影响范围：`server/routes/issues.py`、`server/services/issues.py`、`server/services/heartbeat.py`、`server/skills/bundled/control-plane` 的 `issue checkout` / `issue context` 工作流、UI 的任务执行对齐。
- 复现步骤：
  1. 创建分配给 agent 的 issue，观察 server 可以生成 `assignment` wakeup/run。
  2. 请求 `POST /api/issues/{issueId}/checkout`。
  3. 请求 `GET /api/issues/{issueId}/heartbeat-context`。
- 预期行为：与上游 `D:\coding\rudder\server\src\routes\issues.mutations.ts:613` 和 `D:\coding\rudder\server\src\routes\issues.ts:551` 对齐；`checkout` 应按 `agentId`、`expectedStatuses`、当前 actor/run id 原子领取 issue，并写入 `checkoutRunId/executionRunId`；`heartbeat-context` 应返回 issue、评论、文档、唤醒评论等紧凑上下文，供 heartbeat runtime 执行前读取。
- 必须补齐：
  - `POST /api/issues/{issueId}/checkout`。
  - `GET /api/issues/{issueId}/heartbeat-context`。
  - checkout 成功后按上游语义可把 issue 切到 `in_progress`，并用 `checkoutRunId/executionRunId` 防止多个 run/agent 同时处理同一任务。
  - actor 为 agent 时只能 checkout 自己；board/user 代 checkout 时按上游判断是否需要额外 wake assignee。
- 实际行为：当前 Python server 没有这两个路由；onboarding 和 bundled control-plane skill 已要求 checkout/context，但 API 不存在，UI 暂时只能调用已支持的 wakeup。
- 初步根因：Step 11/13/15 已实现 wakeup/run/workspace 基线，但未迁移上游 issue lifecycle 的 checkout/context 子路由；`checkout_run_id` 字段已存在，说明 schema 留位但 service/route 缺实现。
- 处理归属：Step 21。优先补齐 server contract，不改 UI/CLI；UI 可在接口存在后对接。
- 修复记录：待处理。
- 验证证据：`rg "checkout|heartbeat-context" server packages docs tests` 显示仅 docs/skills/schema 留痕，无 Python route/service/test；上游对应路由存在于 `D:\coding\rudder`。

### BUG-21-023: 任务详情页缺少 issue -> runs 查询和稳定 run/issue 关联

- 状态：open
- 严重级别：P1
- 是否阻塞最小闭环：是。任务可以触发 run，但 UI 无法稳定从 issue 找到相关 run，任务详情页无法展示“这个任务的执行过程”。
- 影响范围：`server/routes/issues.py`、`server/services/heartbeat.py`、`packages/database/schema/heartbeat.py`、`packages/database/queries/heartbeat.py`、UI 任务详情页。
- 复现步骤：
  1. 创建 assigned issue 并触发 heartbeat run。
  2. 尝试按 issueId 查询该 issue 关联过的 heartbeat runs。
  3. 读取 `GET /api/heartbeat-runs/{runId}`，检查 response 是否直接带 issue 摘要字段。
- 预期行为：与上游 issue/run 可见性对齐，server 提供 issue -> runs 查询；run 与 issue 有稳定关联，不能只依赖一次性临时 payload。至少支持：
  - `GET /api/issues/{issueId}/heartbeat-runs` 或上游等价 `GET /api/issues/{id}/runs`。
  - 返回 `runId/status/agentId/createdAt/startedAt/finishedAt/error/summary`。
  - `GET /api/heartbeat-runs/{runId}` 返回 `issueId`、`issueIdentifier`、`issueTitle`、`projectId`、`goalId`，供 UI 不再二次猜测。
  - run 创建时将 issue 关联持久化；可选方案为新增 `heartbeat_runs.issue_id`，或保持上游式 `context_snapshot.issueId` 但必须有 query/helper 封装，避免 UI 直接依赖 JSON 内部结构。
- 实际行为：当前 wakeup payload/contextSnapshot 已可携带 `issueId`，`run_intelligence` 也能按 `context_snapshot.issueId` 过滤；但没有 issue-scoped runs API，也没有在 heartbeat run response 顶层返回 issue 摘要。
- 初步根因：Step 11/13 建立 run 基线时只提供 org/agent scoped run 查询；Step 20 observability 提供 run 详情、events、log、workspace operations，但未补 issue-scoped run 聚合。
- 处理归属：Step 21。优先按上游以 `context_snapshot.issueId` 建立 server 查询封装；是否新增物理 `issue_id` 字段需结合 migration 成本和上游证据决定。
- 修复记录：待处理。
- 验证证据：`rg "issues/:id/runs|issues/{issueId}/heartbeat-runs|live-runs" server packages tests` 当前无 Python route；上游存在 `server/src/routes/activity.ts:80`、`server/src/routes/agents.management-routes.ts:1390` 等 issue-scoped run 查询。

### BUG-21-024: run 输出可读性不足，任务详情页缺少稳定过程输出契约

- 状态：open
- 严重级别：P1
- 是否阻塞最小闭环：是。UI 任务详情页需要展示任务执行过程，但 server 目前只具备基础 run/events/log API，尚未明确执行期间持续可读、关键事件完整性和增量 log 稳定性验收。
- 影响范围：`server/services/heartbeat.py`、`server/services/logs.py`、`server/routes/agents.py`、`server/routes/workspace_operations.py`、`tests/contract/test_step20_observability.py`、任务详情页输出展示。
- 复现步骤：
  1. 创建 assigned issue 并触发 run。
  2. 在 run 执行期间持续读取 `GET /api/heartbeat-runs/{runId}`、`/events`、`/log`、`/workspace-operations`。
  3. 检查是否能看到 queued、started、stdout/stderr、workspace/tool 操作、completed/failed/cancelled/timed_out 和 error message。
  4. 使用 `GET /api/heartbeat-runs/{runId}/log?offset=...&limitBytes=...` 增量读取，检查 `content/nextOffset/eof`。
- 预期行为：对齐上游三层输出模型：DB 结构化 events、local_file NDJSON run log、实时/轮询可读输出。至少支持：
  - `GET /api/heartbeat-runs/{runId}` 在执行期间持续可读。
  - `GET /api/heartbeat-runs/{runId}/events?afterSeq=...&limit=...` 在执行期间持续可读。
  - `GET /api/heartbeat-runs/{runId}/log?offset=...&limitBytes=...` 返回 `content`、`nextOffset`、`eof`，并可增量读取。
  - `GET /api/heartbeat-runs/{runId}/workspace-operations` 在执行期间持续可读。
  - events 至少覆盖 `queued`、`started`、runtime stdout/stderr 摘要、tool/workspace operation、`completed/failed/cancelled/timed_out`、error message。
- 实际行为：当前已有 run 详情、events、log、workspace-operations 基础接口；`HeartbeatService._execute_run` 会写 `lifecycle` 和 stdout/stderr log event，但缺少明确 queued event、完整状态事件矩阵和执行期间持续可读 contract；log 增量语义需补测试确认。
- 初步根因：Step 20 主要补 observability 路径，未按任务详情页场景建立端到端输出契约。
- 处理归属：Step 21。优先补 contract tests 和最小 server 行为；WebSocket/live event 可后置，当前 UI 可先用轮询 `/events` 和 `/log`。
- 修复记录：待处理。
- 验证证据：`test_step20_observability.py` 已覆盖单点 log/workspace operation 读取，但没有 issue-scoped run 输出过程和执行期间持续读取场景。

### BUG-21-025: 缺少按 issueId 执行任务的服务端专用入口和幂等语义

- 状态：open
- 严重级别：P2
- 是否阻塞最小闭环：否。assigned issue 自动 wakeup 已能触发 run，但 UI 仍需要自己组合“创建/分配/唤醒”；专用 execute 接口可以降低 UI 耦合。
- 影响范围：`server/routes/issues.py`、`server/services/issues.py`、`server/services/heartbeat.py`、UI 任务详情页执行按钮。
- 复现步骤：
  1. 已有一个分配给 agent 的 issue。
  2. UI 想触发该 issue 执行，只能自行决定是否 PATCH issue、再调用 agent wakeup。
  3. 连续点击执行按钮时，server 没有 issue-scoped 幂等响应。
- 预期行为：提供上游兼容边界之外的 server 组合入口，或确认使用上游 checkout+wakeup 组合。建议接口：
  - `POST /api/issues/{issueId}/execute`。
  - 校验 issue 存在、组织访问、assignee 可执行。
  - 可选执行 checkout/状态切换。
  - 创建 wakeup/run 并返回 run。
  - 连续点击执行时返回已有 queued/running run、返回 409，或支持 `idempotencyKey`。
- 实际行为：当前没有 issue-scoped execute 入口；只有 agent-scoped wakeup。
- 初步根因：早期 run 能力围绕 agent wakeup 建立，缺少 UI 任务详情页的 issue-centric 操作封装。
- 处理归属：Step 21 或 Step 25。若严格上游对齐，先实现 checkout/context/issue runs；`execute` 可作为 Octopus server 组合 API 后置。
- 修复记录：待处理。
- 验证证据：`rg "issues/.*/execute|execute_issue|issue execute" server packages tests` 当前无对应实现。

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

### BUG-21-015: 组织技能列表向 UI 暴露旧品牌 key 和展示文案

- 状态：fixed
- 严重级别：P2
- 是否阻塞最小闭环：否。但会让组织技能页继续显示旧品牌，违背项目定位和命名清理要求。
- 影响范围：`GET /api/orgs/{orgId}/skills`、组织技能列表 UI、agent desired skills 的内置技能 key。
- 复现步骤：
  1. 创建组织或使用已有组织。
  2. 请求 `GET /api/orgs/{orgId}/skills`。
  3. 查看返回的内置技能 `key`、`sourceBadge`、`sourceLabel`、`editableReason`。
- 预期行为：开发阶段不保留旧数据库兼容，内置组织技能 key 使用 `skills/<slug>`；UI 展示字段使用 `built-in` / `Built-in skill`，不向用户暴露旧品牌。
- 实际行为：server seed 内置技能时返回 `rudder/<slug>`、`sourceBadge: rudder`、`sourceLabel: Bundled by Rudder`、`editableReason: Bundled by Rudder`。
- 初步根因：Step 17 实现时把上游 bundled skill source 名称直接固化到 Python server 的组织技能业务 key 和展示字段中。
- 处理归属：Step 21。
- 修复记录：已将内置组织技能 key 统一为 `skills/<slug>`；`control-plane`、`create-agent`、`create-plugin` 使用项目语义 slug；展示字段统一为 `built-in` / `Built-in skill`；旧 `rudder/*` key 仅在 seed 时作为开发期迁移查找兼容，不再作为新返回值。
- 验证证据：`tests/contract/test_step17_organization_skills.py::test_org_skill_list_seeds_bundled_skills` 已更新期望；当前本机 pytest 执行被 Windows 目录权限 `WinError 5` 阻断，需在权限恢复后复跑。

### BUG-21-016: 组织技能 fileInventory 只返回 SKILL.md，UI 无法展示 references/scripts/templates

- 状态：fixed
- 严重级别：P2
- 是否阻塞最小闭环：否。但会导致组织技能详情页只能看到 `SKILL.md`，无法浏览 community skill 或内置 skill 的参考资料、脚本和模板。
- 影响范围：`GET /api/orgs/{orgId}/skills`、`GET /api/orgs/{orgId}/skills/{skillId}`、组织技能详情 UI 文件列表。
- 复现步骤：
  1. 准备一个包含 `SKILL.md`、`README.md`、`reference/*.md`、`scripts/*.py`、`templates/*.md` 的组织技能目录。
  2. 请求 `GET /api/orgs/{orgId}/skills`。
  3. 查看返回的 `fileInventory`。
- 预期行为：`fileInventory` 应递归列出允许展示的技能文件，并按 `skill/readme/reference/script/template/markdown/other` 标注类型。
- 实际行为：server seed 和 create 逻辑只写入 `[{ "path": "SKILL.md", "kind": "skill" }]`，导致 UI 不知道还有其他文件。
- 初步根因：组织技能实现只把 `SKILL.md` 作为固定清单写入数据库，没有按技能根目录递归扫描文件。
- 处理归属：Step 21。
- 修复记录：已新增 `_scan_skill_inventory()`，内置技能 seed、组织技能创建、文件更新和响应序列化都复用该扫描逻辑；隐藏文件、缓存目录和 Python bytecode 会被排除。
- 验证证据：contract 测试已新增 `reference/methodology.md`、`scripts/sync.py`、`templates/note.md` 的 fileInventory 断言；当前本机 pytest 执行仍被 Windows 目录权限 `WinError 5` 阻断，需在权限恢复后复跑。
