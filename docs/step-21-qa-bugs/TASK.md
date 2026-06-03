# Step 21: Closed-loop QA / Bug Triage

状态：开发中

## 目标

Step 20 已经让最小闭环具备基础调试可见性。本步骤暂停新业务模块开发，集中做代码审查、真实调试、Bug 记录和阻塞问题修复，确保后续 Cost、Governance、Access、Hardening 不建立在未收口的最小闭环问题上。

## 审查范围

最小闭环必须覆盖：

- Organization 创建与读取。
- Agent 创建、配置、skills snapshot/sync/enable、instructions 路径与文件读取。
- Chat 或 Issue 触发 agent 执行。
- 任务详情页需要的 issue -> runs 查询、run -> issue 上下文、执行输出 events/log
  必须对齐上游，保证 UI 可稳定展示任务执行过程。
- Issue 分配触发执行后，需补齐上游式 `POST /api/issues/{issueId}/checkout`
  与 `GET /api/issues/{issueId}/heartbeat-context`，保证真实执行前具备原子领取和紧凑任务上下文。
- Heartbeat run 创建、执行、事件、日志、失败摘要。
- Workspace context、workspace operation、work product 或 attachment/storage 引用。
- Step 20 observability 路径：run log、workspace operation log、run-intelligence list/detail/events/log。

## 任务

### Bug 清单要求

本步骤必须维护 `docs/step-21-qa-bugs/BUGS.md` 作为唯一 Bug Ledger。发现问题时先登记，再决定本步骤修复或排期到后续步骤；不得只在对话中口头记录。

Bug 记录字段必须包含：编号、状态、严重级别、是否阻塞最小闭环、标题、影响范围、复现步骤、预期行为、实际行为、初步根因、处理归属、修复记录、验证证据。

状态值：

- `open`：已确认存在，尚未处理。
- `in_progress`：正在修复或验证。
- `fixed`：已修复并有验证证据。
- `deferred`：不阻塞最小闭环，已排入后续 Step。
- `invalid`：复查后确认不是 Bug，必须记录原因。

严重级别：

- `P0`：阻断最小闭环，必须在 Step 21 修复或说明外部阻塞。
- `P1`：影响核心调试/执行路径，优先在 Step 21 修复。
- `P2`：不阻断闭环，但会影响后续功能开发或兼容性。
- `P3`：文档、提示、可维护性或低风险问题。

### 21A: 文档与调试路径基线

作用：把最小闭环的调试入口写清楚，避免后续排查依赖口头记忆。

范围：

- 汇总从组织到 run 可见性的端到端操作步骤。
- 明确 server 启动、开发 actor、数据库迁移和必要环境变量。
- 记录每个环节的核心 API、预期响应和失败时下一步排查入口。

### 21B: 架构、目录与契约审查

作用：对照 `CLAUDE.md`、`docs/DESIGN.md`、`docs/FEATURE.md` 和上游 `D:\coding\rudder`，查出偏离项目定位的实现。

范围：

- 审查目录是否内聚，避免 runtime、routes、services、shared contract 混放职责。
- 审查 API path、payload、状态值、错误形态是否有无证据自创。
- 审查新增代码是否绕过 organization scope、actor/access、migration 或 shared contract。
- 审查 Step 1-20 已实现能力是否存在重复入口、临时兼容逻辑或应迁移到后续步骤的半成品。

### 21C: 最小闭环手工/脚本化验证

作用：用真实 server 行为验证“创建问题并执行任务”闭环，而不只依赖单点 contract tests。

范围：

- 运行或整理最小闭环 demo，覆盖 organization、agent、skill/instructions、chat/issue、run、workspace、observability。
- 每个失败必须记录复现步骤、请求、响应、日志入口和影响范围。
- 只修复阻塞闭环或导致数据结构偏离上游的问题。

### 21D: Bug Ledger 与后续排期

作用：把发现的问题结构化，防止 Bug 混入后续功能步骤或被遗忘。

范围：

- 建立 Bug 记录文档，字段包含：编号、标题、影响、复现步骤、根因、状态、归属 Step、是否阻塞最小闭环。
- 阻塞最小闭环的问题在本步骤修复。
- 非阻塞但确定存在的问题排入 Step 22-26 或新增后续步骤，不在本步骤无限扩张。

## 边界

- 不开发 Cost Summary、Activity Query、Budget、Auth、Plugin 等新业务模块。
- 不重写 UI/CLI；必要时只记录 server 端缺口或调试接口问题。
- 不凭本地偏好改变上游契约；发现契约不清时先记录上游证据缺口。
- 不把 production hardening、session resume、完整兼容矩阵提前到本步骤；这些仍归 Step 25。

## 验收

- 最小闭环调试路径可被复现，并能定位失败发生在哪一层。
- 已发现 Bug 均有记录、状态和归属步骤。
- 阻塞最小闭环的问题已修复或明确说明不能修复的外部原因。
- 文档更新后，Step 22 Cost/Activity 可以在更稳定的闭环基础上继续开发。

## 验证命令

每次修复代码后至少运行：

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pyright .
```

根据实际修改范围补充对应 contract/workflow tests。若环境权限导致 `uv run` 不可用，可使用 `.venv\Scripts\...` 等价命令并在提交说明中记录差异。
