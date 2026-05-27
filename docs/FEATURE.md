# Octopus 整体开发计划

## 1. 文档职责

本文档定义 Octopus 的整体开发路线、步骤职责、依赖顺序和验收边界。

- `CLAUDE.md`：项目定位、长期原则与开发纪律
- `docs/DESIGN.md`：整体架构、服务端能力边界与关键技术决策
- `docs/FEATURE.md`：整体开发计划与 Step 划分
- `docs/step-NN-<scope>/TASK.md`：对应步骤的任务入口；已完成步骤在其中保留详细实施记录，待开发步骤可在执行时按需拆分附属任务文档
- `step-<number>-<scope>`：对应 Step 的开发分支命名格式，例如 Project 管理使用 `step-10-projects`，UI/CLI 子任务使用 `step-<number>-ui-cli`

若步骤文档与本文件冲突，以本文件为准；若本文件与设计文档冲突，先修正本文件；若设计结论偏离项目定位，先修正设计文档或 `CLAUDE.md`。

## 2. 开发目标

Octopus 是上游参考实现控制面 `server` 的 Python 兼容替代实现。开发主线必须：

- 保持已选择服务端能力的数据库模型、API 契约、状态值和关键副作用语义
- 保留上游已有的 run、runtime、workspace、恢复和运行记录能力
- 在真实认证能力接入前，使用结构兼容的开发 actor 与模拟数据调试链路
- 裁剪与当前 server 兼容目标无关的外围模块
- 不引入没有上游证据的新业务对象、新前置条件或新执行模型

## 3. 执行原则

### 3.1 上游证据

每项功能开发前，对照上游 schema、route、shared type、service 和测试。无法确认契约的能力不得凭空实现。

### 3.2 契约优先

Python 实现可以调整内部结构，但不得无证据改变 API 路径、payload、数据库字段、枚举、状态流转和副作用时机。

### 3.3 调试数据

开发阶段允许提供 mock、seed 或 fixture，但只能替换数据来源，不得改变上游兼容的数据形态或流程关系。真实接入应能替换数据来源而无需重构模型。

### 3.4 步骤边界

每个步骤只承担一个主要交付对象。Step 1-9 已完成，其 `TASK.md` 记录实际实现和验收证据；Step 10 以后在开发启动时可按复杂度拆分规格、计划或执行记录。已有实现不会因步骤重排撤销。

进入某一步骤开发时，分支名使用 `step-<number>-<scope>`；同一步骤需要独立拆分的交付分支继续使用简短职责后缀，例如 `step-<number>-ui-cli`。分支命名只表达 Step 与交付范围，不重复加入 `feat/` 或 `contracts-` 前缀。

## 4. 步骤目录映射

| Step | 主要功能 | 目录 |
| --- | --- | --- |
| 1 | 项目边界与仓库基线 | `docs/step-01-base/` |
| 2 | Server 骨架与配置 | `docs/step-02-server/` |
| 3 | Shared Contract | `docs/step-03-contract/` |
| 4 | Database 与 Migration | `docs/step-04-db/` |
| 5 | 开发 Actor、Scope 与 Seed | `docs/step-05-scope/` |
| 6 | Organization 管理 | `docs/step-06-orgs/` |
| 7 | Issue 基础管理 | `docs/step-07-issues/` |
| 8 | Comment 与 Review 流程 | `docs/step-08-review/` |
| 9 | Approval 管理 | `docs/step-09-approvals/` |
| 10 | Project 管理 | `docs/step-10-projects/` |
| 11 | Agent 执行子系统与交互闭环 | `docs/step-11-agents/` |
| 12 | Goal 管理 | `docs/step-12-goals/` |
| 13 | Run 调度与恢复 | `docs/step-13-runs/` |
| 14 | 其他 Runtime Adapter 扩展 | `docs/step-14-runtime/` |
| 15 | Workspace 与执行产物 | `docs/step-15-workspace/` |
| 16 | Cost、Budget 与 Activity | `docs/step-16-governance/` |
| 17 | Chat / Messenger 扩展 | `docs/step-17-chat/` |
| 18 | Attachment / Storage | `docs/step-18-storage/` |
| 19 | Auth / Actor / Access | `docs/step-19-access/` |
| 20 | Recovery / Observability / Compatibility | `docs/step-20-hardening/` |

主依赖链为：

`base -> server -> contract -> db -> scope -> orgs -> issues -> review -> approvals -> projects -> agent-execution-and-conversation -> goals -> run-hardening -> runtime-expansion -> workspace -> governance -> chat-expansion -> storage -> access -> hardening`

## 5. Step 计划

### Step 1: 项目边界与仓库基线

目录：`docs/step-01-base/`

- 目标：确立 Python server 兼容重写的边界，清理无关工程负担。
- 交付：仓库结构、依赖基线、基础检查命令和文档职责。
- 验收：项目可安装、可检查、可测试，后续代码落点明确。

### Step 2: Server 骨架与配置

目录：`docs/step-02-server/`

- 目标：建立应用启动、配置加载、错误响应和基础依赖注入边界。
- 交付：`uv run server` 命令入口、独立的 FastAPI 应用工厂、健康检查和配置模型。
- 验收：服务可以稳定启动并输出契约化响应。

### Step 3: Shared Contract

目录：`docs/step-03-contract/`

- 目标：集中定义 API path、请求响应模型、枚举、validator 和共享常量。
- 交付：服务端可以直接消费的兼容契约层。
- 验收：契约测试验证字段形态、枚举和错误结构。

### Step 4: Database 与 Migration

目录：`docs/step-04-db/`

- 目标：映射上游业务表，并提供可重复执行的 schema migration 流程。
- 交付：数据库 schema、queries、Alembic 配置和 baseline migration。
- 验收：空库升级成功，模型与已纳入范围的上游字段一致。

### Step 5: 开发 Actor、Scope 与 Seed

目录：`docs/step-05-scope/`

- 目标：提供统一的 organization scope 与开发期 actor/seed，使功能可调试且不偏离契约。
- 已实现：`OCTOPUS_LOCAL_TRUSTED=1` 的本地 board actor middleware、统一 actor/access dependency、organization-scoped 访问控制、兼容 actor fixture 及跨组织拒绝测试。
- 已实现：issue/comment/review activity 使用统一 actor；approval 与 issue 建立关联前校验同一 organization。
- 验收：开发 actor 只从统一边界注入，数据结构可被真实接入无缝替换，需要 scope 的资源操作不得跨 organization 访问。

### Step 6: Organization 管理

目录：`docs/step-06-orgs/`

- 目标：实现 organization 的创建、读取、更新和状态管理。
- 交付：organization routes、service、queries 及 contract/workflow tests。
- 验收：能够先创建 organization，再以其作为后续业务请求作用域。

### Step 7: Issue 基础管理

目录：`docs/step-07-issues/`

- 目标：实现 issue 的列表、详情、创建、编辑、筛选和基础关联字段。
- 交付：issue 核心 CRUD 与查询语义。
- 验收：issue 在指定 organization 内可被稳定创建和维护；评论及 review 流程不混入本步骤。

### Step 8: Comment 与 Review 流程

目录：`docs/step-08-review/`

- 目标：补充 issue comment、review 动作和对应状态流转副作用。
- 交付：comment API、review workflow 和 activity 行为。
- 验收：流程动作遵守上游状态语义，重复或越权动作得到正确拒绝。

### Step 9: Approval 管理

目录：`docs/step-09-approvals/`

- 目标：实现 approval 创建、读取与决策流程。
- 交付：approval routes、service、持久化和工作流测试。
- 验收：approval 与 organization/issue 关系、决策状态及副作用保持兼容。

### Step 10: Project 管理

目录：`docs/step-10-projects/`

- 目标：实现 project 的基础管理和 organization 作用域行为。
- 交付：project contract、持久化与 API。
- 验收：project 可独立维护并供后续 goal 关联。

### Step 11: Agent 执行子系统与交互闭环

目录：`docs/step-11-agents/`

- 目标：实现可被创建、配置、实际触发并通过消息交互的首个 agent 服务端闭环，同时为 Goal 的 `ownerAgentId` 提供合法依赖对象。
- 已完成交付：agent contract、持久化与管理 API、配置变更边界、wakeup/heartbeat run 基线、统一 runtime adapter contract，以及 `process` 与 `codex_local` 可执行路径。
- 已完成交付：仅覆盖 agent 执行触发和响应保存的 conversation/message 最小链路；经上游核对，chat assistant invocation 不持久化为 heartbeat run。
- 验收：agent 可在 organization scope 内由消息触发 `codex_local` 实际执行并查询持久化回复；独立 wakeup/heartbeat run 结果保持可查询；Goal 可安全引用已存在 agent。

### Step 12: Goal 管理

目录：`docs/step-12-goals/`

- 目标：实现 goal 的创建、查询、更新、层级与 project/organization/owner agent 关联。
- 交付：goal contract、持久化、服务逻辑、project goal 聚合关系与工作流测试。
- 验收：goal 的关联关系、层级约束、状态字段和当前已具备依赖的删除阻塞行为与上游一致；治理和独立 automation 依赖随对应步骤补齐。

### Step 13: Run 调度与恢复

目录：`docs/step-13-runs/`

- 目标：在 Step 11 可运行基线上补齐上游 server 的调度、并发保护、取消与恢复语义。
- 交付：周期/队列触发、run claim 与幂等处理、取消/失败恢复及增强运行记录查询。
- 验收：重复触发、竞争领取、中断恢复和取消流程符合上游行为，且不改变 Step 11 已建立的 run contract。

### Step 14: 其他 Runtime Adapter 扩展

目录：`docs/step-14-runtime/`

- 目标：在 Step 11 已提供 `process` 与 `codex_local` 执行路径的基础上，扩展其余经确认需要支持的 runtime 种类和兼容能力。
- 交付：除 `codex_local` 以外的新增 adapter 实现、session/environment/usage 深化及不同 runtime 的错误归一化。
- 验收：新增 runtime 复用既有 run contract 与业务 API，adapter 差异不泄漏到控制面服务。

### Step 15: Workspace 与执行产物

目录：`docs/step-15-workspace/`

- 目标：在 Step 11 最小执行上下文基础上，实现完整 workspace 建立、复用、清理和产物记录能力。
- 交付：workspace 生命周期与产物引用。
- 验收：执行上下文和产物可追踪，失败处理不留下不一致业务状态。

### Step 16: Cost、Budget 与 Activity

目录：`docs/step-16-governance/`

- 目标：在 Step 11 运行基线产生的必要记录基础上，实现完整成本、预算限制及关键活动治理闭环。
- 交付：cost 记录、budget 校验、activity 扩展和查询。
- 验收：run 消耗可归集，预算限制与 activity 副作用可测试。

### Step 17: Chat / Messenger 扩展

目录：`docs/step-17-chat/`

- 目标：在 Step 11F 已建立 agent 对话触发基线后，补齐上游范围内剩余会话、消息和与业务对象的联动能力。
- 交付：不属于 agent 执行最小链路的 conversation/message contract、API、service 与副作用。
- 验收：完整纳入范围的消息链路保持 organization scope 和兼容 payload，且不改变 Step 11F 已建立的调用闭环。

### Step 18: Attachment / Storage

目录：`docs/step-18-storage/`

- 目标：实现 attachment 元数据、对象存储边界与业务引用。
- 交付：storage abstraction、attachment API 和关联验证。
- 验收：上传/读取/关联行为可测试，存储实现不改变外部契约。

### Step 19: Auth / Actor / Access

目录：`docs/step-19-access/`

- 目标：按上游证据接入真实认证、actor 和授权行为，替代开发 actor 数据源。
- 交付：身份上下文、访问检查和迁移策略。
- 验收：真实 actor 与开发 actor 复用同一结构边界，业务 API 无需重构。

### Step 20: Recovery / Observability / Compatibility

目录：`docs/step-20-hardening/`

- 目标：补齐失败恢复、可观测性与全链路兼容验收。
- 交付：恢复策略、日志/指标边界、完整 contract/workflow 回归。
- 验收：主要 server 场景可恢复、可定位，并通过兼容测试集。

## 6. 可选扩展

organization resources、skills、plugins、automation、calendar、secrets 等能力不预占主线步骤。只有在确认属于当前 server 兼容范围并取得上游契约证据后，才单独规划并插入依赖链。

## 7. 验收与更新规则

- 每个步骤开始前，在对应目录维护 `TASK.md` 中的任务范围、契约依据和验收标准；复杂步骤可同时拆分规格与执行计划。
- 每个步骤完成时，确保 `TASK.md` 汇总实现范围、关键文件、验证证据和未纳入事项，附属过程文档只在仍有独立参考价值时保留。
- 步骤拆分或调整时，先更新本文件与目录映射，再迁移步骤文档。
- 只有用户明确要求提交后，才提交已验证的实现与文档。
