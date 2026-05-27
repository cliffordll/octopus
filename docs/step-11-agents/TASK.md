# Step 11: Agent 执行子系统

状态：待开发

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

### 11B: 配置治理与运行状态

- 落地 runtime 配置表示、校验、敏感字段处理及 configuration revision 边界。
- 落地运行所需的 runtime state、task session、wakeup request 等已证实持久化对象。
- 纳入权限、hire 或 API key 行为时，必须先核实其是否属于本步骤首个可运行路径或上游 Agent 管理的强制契约。

### 11C: 首个可运行闭环

- 定义统一 runtime adapter contract，并实现一个具备上游证据且本地可验证的实际 adapter 路径。
- 接入 agent wakeup、heartbeat run 建立、状态迁移、执行结果和失败语义。
- 记录该闭环必须产生的活动与最小执行上下文，使 run 不是仅保存配置的伪实现。

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
