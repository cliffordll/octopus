# Step 11: Agent 执行子系统

状态：开发中（11A-11C 已完成；11D 待开发）

## 调整原因

上游 `goals.owner_agent_id` 直接引用 agent，同时 agent 并非只用于保存配置：上游 route、service 和 schema 已包含 wakeup、heartbeat run、runtime state、task session 与 runtime adapter 调用边界。因此本步骤不再交付一个无法运行的 Agent CRUD 外壳，而是建立首个可实际执行的 Agent 服务端闭环。

## 上游证据范围

以本地上游参考源码 `D:\coding\rudder` 为准，开发前逐项核对：

- Schema：`packages/db/src/schema/agents.ts`、`agent_config_revisions.ts`、`agent_runtime_state.ts`、`agent_task_sessions.ts`、`agent_wakeup_requests.ts`、`agent_api_keys.ts`。
- Contract：`packages/shared/src/types/agent.ts`、`packages/shared/src/validators/agent.ts`、`packages/shared/src/constants.ts`。
- Route/Service：`server/src/routes/agents.ts`、`server/src/routes/agents.management-routes.ts`、`server/src/services/agents.ts`。
- Runtime：`server/src/agent-runtimes/registry.ts` 与 `server/src/services/runtime-kernel/`。
- Tests：agent permissions、run context、runtime adapter 与 heartbeat/wakeup 相关上游测试。

已确认需要保持兼容的枚举边界包括：

- Agent status：`active`、`paused`、`idle`、`running`、`error`、`pending_approval`、`terminated`。
- Runtime type：`process`、`http`、`claude_local`、`codex_local`、`gemini_local`、`opencode_local`、`pi_local`、`cursor`、`openclaw_gateway`、`hermes_local`。
- Agent role：`ceo`、`cto`、`cmo`、`cfo`、`engineer`、`designer`、`pm`、`qa`、`devops`、`researcher`、`general`。
- Pause reason：`manual`、`budget`、`system`。

## 交付范围

### 11A: Agent 主对象与生命周期

- 落地 agent contract、schema/query、migration、organization scope 与管理 API。
- 实现创建、读取、更新、暂停、恢复、终止等已证实的生命周期行为。
- 实现 manager/reporting 关系、workspace key 或同类已证实约束时，仅按上游行为落地，不引入 ownership 或 pod。

实施记录：

- Shared contract 已实现 Agent status、role、runtime type、pause reason、request/response type、validator 与管理 API path。
- Database 已实现 `agents` schema/query 及 `20260527_000003_agents.py` migration，保留 organization、status、reports-to 和 workspace-key 索引边界。
- Server 已实现 organization-scoped Agent 创建/列表/详情/更新，以及暂停、恢复、终止生命周期 API；详情响应保留 `chainOfCommand` 与 `access` 结构。
- Service 已实现短名和 workspace key 派生、同 organization manager 校验、reporting cycle 拒绝、terminated 列表过滤与 activity 输出。
- Tests 已覆盖 contract、migration、管理路由、跨 organization scope、manager 校验、生命周期 activity 与 reporting cycle。

### 11B: 配置治理与运行状态

- 落地 runtime 配置表示、校验、敏感字段处理及 configuration revision 边界。
- 落地运行所需的 runtime state、task session、wakeup request 等已证实持久化对象。
- 纳入权限、hire 或 API key 行为时，必须先核实其是否属于本步骤首个可运行路径或上游 Agent 管理的强制契约。

实施记录：

- Database 已实现 `agent_config_revisions`、`agent_runtime_state`、`agent_task_sessions` 与 `agent_wakeup_requests` schema/query 及 `20260527_000004_agent_state.py` migration。
- Agent 配置型更新已写入脱敏 revision snapshot，并支持配置列表/详情、revision 列表/详情与无敏感占位快照 rollback。
- Runtime state 与 task session 已实现只读查询和 session reset；reset 支持按 task key 清理并记录 `agent.runtime_session_reset` activity。
- `agent_wakeup_requests` 本步骤只建立持久化边界，实际 wakeup 创建和状态推进归入 11C 执行闭环。
- Hire、permissions 独立管理和 API key 尚不属于当前首个运行路径的前置实现，保持延后核对，不在本步骤凭空扩展权限流程。

### 11C: 首个可运行闭环

- 定义统一 runtime adapter contract，并实现一个具备上游证据且本地可验证的实际 adapter 路径。
- 接入 agent wakeup、heartbeat run 建立、状态迁移、执行结果和失败语义。
- 记录该闭环必须产生的活动与最小执行上下文，使 run 不是仅保存配置的伪实现。

实施记录：

- Shared contract 已实现 heartbeat invocation source、wakeup/run status、wakeup payload 校验以及 wakeup、invoke、run/event 查询 API path。
- Database 已实现 `heartbeat_runs`、`heartbeat_run_events` schema/query 及 `20260527_000005_heartbeat_runs.py` migration，并将运行结果关联至既有 wakeup request 与 runtime state。
- Runtime 已建立统一 adapter contract 与 `process` adapter，支持真实命令调用、stdout/stderr 捕获、超时和退出错误归一化。
- Server 已实现手动 wakeup/invoke、organization-scoped run 查询和 run event 查询；一次调用会推进 queued/running/final 状态并更新 agent/runtime state。
- Activity 遵循手动调用边界记录 `heartbeat.invoked`；内部 wakeup 的业务活动仍由各自触发流程负责，避免扩大副作用语义。
- 本阶段执行采用可验证的即时 process 执行路径；队列调度、并发领取、取消/恢复、多 adapter 与完整 workspace 仍分别归 Step 13-15 扩展。

### 11D: 基线验收

- 建立 contract、workflow、scope 与 runtime integration tests。
- 提供从 organization、agent 创建到触发一次执行并查询结果的本地验收 demo。
- 对照上游记录本步骤已实现和延后的 endpoint、表与副作用清单。

## 后续步骤边界

- Step 12 实现 Goal CRUD、层级与 `ownerAgentId` 同 organization 引用校验。
- Step 13 在本步骤 run 基线上扩展调度、并发领取、取消、中断恢复和幂等语义。
- Step 14 扩展更多 runtime adapter 类型及 session/environment/usage 兼容行为。
- Step 15 落地完整 workspace 生命周期与执行产物；本步骤只实现首个执行路径必须使用的最小上下文。
- Step 16 落地完整 cost、budget 与 activity 治理；本步骤只保留执行闭环必须产生的记录。
- Avatar、attachment/storage 与 chat 不因 Agent 路由关联而提前并入本步骤。

## 验收

- Tests 验证 agent 管理、organization scope、配置变更和上游枚举边界。
- Tests 验证一次 wakeup/heartbeat run 能调用实际 adapter，并持久化兼容状态与结果。
- Step 12 可以使用本步骤已实现 agent 对 `Goal.ownerAgentId` 做同 organization 引用校验。
