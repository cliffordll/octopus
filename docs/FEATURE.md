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
| 16 | Chat / Messenger 扩展 | `docs/step-16-chat/` |
| 17 | Organization Resources、Organization Skills 与 Agent Instructions | `docs/step-17-org-resources-skills/` |
| 18 | Chat Attachments 与基础运行可见性 | `docs/step-18-chat-refs/` |
| 19 | Basic Observability / Debug Visibility | `docs/step-19-observability/` |
| 20 | Cost Summary 与 Activity Query | `docs/step-20-cost-activity/` |
| 21 | Budget / Governance | `docs/step-21-governance/` |
| 22 | Attachment / Storage | `docs/step-22-storage/` |
| 23 | Auth / Actor / Access | `docs/step-23-access/` |
| 24 | Recovery / Observability / Compatibility | `docs/step-24-hardening/` |
| 25 | Plugin Framework | `docs/step-25-plugins/` |

主依赖链为：

`base -> server -> contract -> db -> scope -> orgs -> issues -> review -> approvals -> projects -> agent-execution-and-conversation -> goals -> run-hardening -> runtime-expansion -> workspace -> chat-expansion -> org-resources-skills -> chat-refs -> debug-visibility -> cost-activity -> governance -> storage -> access -> hardening -> plugins`

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
- 已完成交付：agent contract、持久化与管理 API（含缺省个人名称分配和名称建议入口）、配置变更边界、wakeup/heartbeat run 基线、统一 runtime adapter contract，以及 `process` 与 `codex_local` 可执行路径。
- 已完成交付：仅覆盖 agent 执行触发和响应保存的 conversation/message 最小链路；经上游核对，chat assistant invocation 不持久化为 heartbeat run。
- 验收：agent 可在 organization scope 内由消息触发 `codex_local` 实际执行并查询持久化回复；独立 wakeup/heartbeat run 结果保持可查询；Goal 可安全引用已存在 agent。

### Step 12: Goal 管理

目录：`docs/step-12-goals/`

- 目标：实现 goal 的创建、查询、更新、层级与 organization/project/owner agent/issue 关联，不在组织创建时伪造未证实的默认 Goal 副作用。
- 交付：goal contract、持久化、服务逻辑、project `goalIds`/`goals` 聚合、issue 默认 organization Goal fallback 与工作流测试。
- 验收：goal 的关联关系、层级约束、状态字段、issue fallback 及当前已具备依赖的删除阻塞行为与上游一致；governance 和独立 automation 依赖随对应步骤补齐。

### Step 13: Run 调度与恢复

目录：`docs/step-13-runs/`

- 目标：在 Step 11 可运行基线上补齐上游 server 的调度、并发保护、取消与恢复语义。
- 交付：周期/队列触发、run claim 与幂等处理、取消/失败恢复及增强运行记录查询。
- 验收：重复触发、竞争领取、中断恢复和取消流程符合上游行为，且不改变 Step 11 已建立的 run contract。

### Step 14: Runtime Adapter 扩展

目录：`docs/step-14-runtime/`

- 目标：在 Step 11 已提供 `process` 与 `codex_local` 执行路径的基础上，补齐上游当前 server 已纳入的 runtime adapter、环境检查、模型发现、skills 管理与基础 quota window 能力边界。
- 交付：`http`、`claude_local`、`opencode_local` adapter 的上游兼容执行行为；runtime environment test API 的基础 probe；Codex 静态模型清单与 OpenCode 模型发现；Codex/Claude/OpenCode skills snapshot、sync、enable、private skill 和 analytics 兼容路由；adapter quota window probe 兼容结构；session/usage/错误的基础归一化。
- 执行顺序：先完成 14R1 服务端契约闭环，包括 skills enable/private/analytics、runtime metadata/config doc 和 quota window probe API；再完成 14R2 本地 CLI adapter 深化，包括 Claude/OpenCode 独立 adapter、Codex managed home、真实 environment probe、model discovery、skills entries 和 managed instructions materialization。
- 验收：新增 runtime 复用既有 run contract 与业务 API，adapter 差异不泄漏到控制面服务；模型发现、skills 管理、基础环境探针和 quota window 兼容结构均可验证；`gemini_local`、`cursor`、`pi_local`、`openclaw_gateway`、`hermes_local` 在本阶段返回明确未纳入或未实现结果。

后置边界：

- Claude/OpenCode session resume、HTTP/CLI live hello probe、完整 runtime compatibility hardening 归 Step 24。
- 真实 quota window 读取、budget 治理联动和 skills analytics 真实归集归 Step 21。
- provider/biller/cost 基础归集和 activity query 归 Step 20。
- local agent JWT/API key、secret/env binding 和真实 actor/access 归 Step 23。

### Step 15: Workspace 与执行产物

目录：`docs/step-15-workspace/`

- 目标：在 Step 11/13/14 已建立的执行、调度和 runtime adapter 基础上，实现上游兼容的 project workspace、execution workspace、workspace runtime service、workspace operation 和 work product 引用闭环。
- 交付：workspace contract/schema、project workspace 聚合、execution workspace 策略解析、runtime context 注入、workspace runtime service 生命周期、workspace operation/run 关联、work product 引用和失败清理。
- 执行顺序：先拆清 workspace 数据契约与 project 聚合，再补齐执行前 workspace 解析和 runtime context 注入，随后实现 runtime service、operation 记录、work product 引用与恢复清理。
- 验收：project/issue/run 能稳定关联 workspace；adapter 收到兼容 workspace context；runtime service 和 operation 可追踪；失败、取消或恢复后不留下不一致业务状态。

### Step 16: Chat / Messenger 扩展

目录：`docs/step-16-chat/`

- 目标：在 Step 11F 已建立 agent 对话触发基线后，优先补齐上游范围内剩余会话、消息和与业务对象的联动能力，使 agent 可以被真实使用。
- 交付：不属于 agent 执行最小链路的 conversation/message contract、API、service 与副作用。
- 验收：完整纳入范围的消息链路保持 organization scope 和兼容 payload，且不改变 Step 11F 已建立的调用闭环。

### Step 17: Organization Resources、Organization Skills 与 Agent Instructions

目录：`docs/step-17-org-resources-skills/`

- 目标：在不改 UI/CLI 的前提下，补齐 organization-scoped resource CRUD、organization skill 管理和智能体说明文件管理的服务端契约，使后续 UI/CLI 只消费稳定 API。
- 交付：organization resources 的 schema/query/service/routes、organization skills 的 schema/文件来源/API/审计、runtime skills snapshot 可消费 organization skill entry、skill entry 展示元数据兼容字段，以及基于 Step 14 managed instructions 的说明文件读取/更新/审计边界。
- 执行顺序：先对照上游确认 organization resources、organization skills 与 agent instructions 的 schema、route、service 和测试证据；再实现 resources CRUD；随后实现 organization skills CRUD/import/update/delete；再修正 agent skills snapshot 的服务端 response；最后在上游存在契约证据时补齐 agent instructions 文件管理 API，若上游仅有初始化 materialization 行为则明确记录“不提供独立管理 API”。
- 验收：organization resource 可按 organization scope 创建、查询、更新、删除并记录 activity；organization skill 可被创建、更新、删除、审计并被 agent skills snapshot/sync/enable 消费；服务端返回的 skill entry 足以支持“智能体技能标签显示描述信息”；agent instructions 文件管理边界不会改变 Step 14 runtime materialization 和执行读取行为。

### Step 18: Chat Attachments 与基础运行可见性

目录：`docs/step-18-chat-refs/`

- 目标：补齐 Chat 使用 Agent 时需要的最小附件引用、产物引用和执行可见性，不等待完整 Storage 或完整 Observability；同时收口 Step 16 遗留的消息持久化与 runtime 失败事务边界。
- 交付：chat 用户消息先持久化且不因 runtime 失败回滚、runtime 失败摘要、message attachment/artifact reference、chat 到 run/runtime result 的基础可见字段、跨 organization 引用校验。
- 执行顺序：先完成 18A message persistence/runtime failure boundary，确保非流式和流式发送中已经 ack 的用户消息可刷新查询；再实现附件/产物引用；最后补齐执行可见性字段。
- 验收：runtime 失败后用户消息仍可通过 message list 查询，错误可读；消息可以关联已存在附件/产物/run 信息；失败执行有可读摘要；不引入完整 storage lifecycle。

### Step 19: Basic Observability / Debug Visibility

目录：`docs/step-19-observability/`

- 目标：在真实 Auth 接入前，优先补齐 chat、run、runtime、workspace 的基础调试可见性。
- 交付：run events、runtime stdout/stderr 摘要、错误摘要、workspace operation/work product 关联查询、chat execution error 可读响应。
- 验收：开发和 UI/CLI 联调能定位 agent 对话、run 执行和 workspace 操作问题；完整生产级 hardening 仍归 Step 24。

### Step 20: Cost Summary 与 Activity Query

目录：`docs/step-20-cost-activity/`

- 目标：先实现不阻塞主链路的成本摘要和 activity 查询，让用户能看见 agent/run/chat 做了什么、消耗了多少。
- 交付：cost event、cost summary/query、provider/biller 基础归一化、organization/issue/run activity 查询。
- 验收：run 消耗可归集，activity 可查询，成本和活动可解释；budget hard-stop、quota 和 skills analytics 归 Step 21。

### Step 21: Budget / Governance

目录：`docs/step-21-governance/`

- 目标：在 Step 20 成本和活动记录基础上，实现预算限制、quota window 和 skills analytics 等治理闭环。
- 交付：budget policy、budget incident、hard-stop、budget approval 副作用、provider quota windows 聚合、skills analytics 真实归集。
- 验收：预算和 quota 限制可解释；hard-stop 能暂停并阻止新 work；skills analytics 基于持久化 evidence。

### Step 22: Attachment / Storage

目录：`docs/step-22-storage/`

- 目标：实现 attachment 元数据、对象存储边界、业务引用，以及 runtime/chat/workspace 产物需要的完整存储引用能力。
- 交付：storage abstraction、attachment API、关联验证、上传/读取和产物/消息附件引用 lifecycle。
- 验收：上传、读取、关联和产物引用行为可测试，存储实现不改变外部契约。

### Step 23: Auth / Actor / Access

目录：`docs/step-23-access/`

- 目标：按上游证据接入真实认证、actor、授权行为和运行时 secret/env 解析边界，替代开发 actor 数据源。
- 交付：身份上下文、访问检查、local agent JWT/API key 兼容入口、secret/env binding 解析和迁移策略。
- 验收：真实 actor 与开发 actor 复用同一结构边界；runtime env/secret 不泄漏、不改变业务 API。

### Step 24: Recovery / Observability / Compatibility

目录：`docs/step-24-hardening/`

- 目标：补齐失败恢复、生产级可观测性与全链路兼容验收。
- 交付：恢复策略、Claude/OpenCode session resume 与 cwd mismatch 处理、HTTP/CLI live hello probe、日志/指标边界、完整 contract/workflow 回归。
- 验收：主要 server 场景可恢复、可定位，并通过兼容测试集。

### Step 25: Plugin Framework

目录：`docs/step-25-plugins/`

- 目标：按上游 server 的 plugin framework 实现 Python 兼容子系统，覆盖插件注册、生命周期、配置、状态、工具、webhook、job、UI bridge 和运行时 worker 边界。
- 交付：plugin 数据模型与迁移、manifest/schema 校验、registry/lifecycle service、管理 API、plugin state/config/entities/logs/jobs/webhooks 持久化、tool dispatcher、worker RPC 边界、插件 UI 静态资源和 bridge API、内置/示例插件目录约定。
- 执行顺序：先实现只读 catalog/manifest/registry 和管理 API；再实现生命周期、配置、状态、日志；随后接入 worker、tools、jobs、webhooks、UI bridge；最后补齐 SDK/脚手架兼容和 Linear 等一方插件。
- 验收：插件管理 API 与上游路径和 payload 对齐；ready/disabled/error/upgrade_pending/uninstalled 状态流转可测试；插件 worker、tool、webhook、job 和 UI bridge 在本地单实例部署可验证；明确不承诺上游尚未完成的云端多实例插件分发能力。

## 6. 可选扩展

automation、calendar、secrets 等能力不预占主线步骤。只有在确认属于当前 server 兼容范围并取得上游契约证据后，才单独规划并插入依赖链。organization resources 与 organization skills 已作为服务端独立能力提前纳入 Step 17。

Plugins 已确认属于上游 server 的独立子系统，纳入 Step 25，不再作为可选扩展悬置。其范围以 `D:\coding\rudder\doc\plugins\PLUGIN_SPEC.md`、`server/src/routes/plugins.ts`、`server/src/bootstrap/plugin-host-runtime.ts`、`server/src/services/plugin-*`、`packages/db/src/schema/plugin_*.ts` 和 `packages/plugins/*` 为证据来源。

### Skills 后续拆分边界

- Runtime skills 消费能力继续归 Step 14：本地 runtime adapter 如何发现、选择、materialize 或 mount skills。
- Skills 使用统计真实归集归 Step 21：基于 run/event/activity 记录计算 loaded/requested/used 统计，不在 Step 14 伪造数据。
- Organization skills 管理提前纳入 Step 17，不塞进 Step 16 Chat。范围包括 organization skill 的数据库/文件来源、创建/更新/删除 API、权限与审计、与 `agentRuntimeConfig.skillsRootPath` 的迁移关系，以及 agent skills snapshot 返回描述与来源元数据的服务端兼容修正。
- Agent instructions 管理缺口纳入 Step 17：Step 14 只负责默认 instructions 初始化、路径配置和 runtime 读取；Step 17 负责按上游证据确认是否存在独立说明文件管理 API，并在存在时补齐读取、更新、路径安全、scope/access 和 activity 审计。
- External skills 当前仅作为 runtime home 中的外部安装项检测；如后续要支持“导入/接管外部 skill”，应归独立 skills 管理步骤，并先确认上游是否存在对应服务端契约。

## 7. 验收与更新规则

- 每个步骤开始前，在对应目录维护 `TASK.md` 中的任务范围、契约依据和验收标准；复杂步骤可同时拆分规格与执行计划。
- 每个步骤完成时，确保 `TASK.md` 汇总实现范围、关键文件、验证证据和未纳入事项，附属过程文档只在仍有独立参考价值时保留。
- 步骤拆分或调整时，先更新本文件与目录映射，再迁移步骤文档。
- 只有用户明确要求提交后，才提交已验证的实现与文档。
