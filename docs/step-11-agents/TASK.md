# Step 11: Agent 执行子系统与交互闭环

状态：11A-11F 已完成并通过基线验收

## 调整原因

上游 `goals.owner_agent_id` 直接引用 agent，同时 agent 并非只用于保存配置：上游 route、service 和 schema 已包含 wakeup、heartbeat run、runtime state、task session 与 runtime adapter 调用边界。因此本步骤不再交付一个无法运行的 Agent CRUD 外壳，而是建立可实际执行且可通过消息交互触发的 Agent 服务端闭环。

## 上游证据范围

以本地上游参考源码为准，开发前逐项核对：

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
- 实现 manager/reporting 关系、workspace key 或同类已证实约束时，仅按上游行为落地，不引入额外归属或聚合模型。

实施记录：

- Shared contract 已实现 Agent status、role、runtime type、pause reason、request/response type、validator 与管理 API path。
- Database 已实现 `agents` schema/query 及 `20260527_000003_agents.py` migration，保留 organization、status、reports-to 和 workspace-key 索引边界。
- Server 已实现 organization-scoped Agent 创建/列表/详情/更新、个人名称建议，以及暂停、恢复、终止生命周期 API；详情响应保留 `chainOfCommand` 与 `access` 结构。
- Service 已实现省略 `name` 时从兼容个人名称池自动选取未占用名称、短名和 workspace key 派生、同 organization manager 校验、reporting cycle 拒绝、terminated 列表过滤与 activity 输出。
- Tests 已覆盖 contract、migration、管理路由、缺省名称分配/名称建议、跨 organization scope、manager 校验、生命周期 activity 与 reporting cycle。

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
- Server 已实现手动 wakeup/invoke、organization-scoped run 查询和 run event 查询；经 Step 13 扩展后，HTTP 触发先返回 `queued` run，由后台派发推进 running/final 状态并更新 agent/runtime state。
- Activity 遵循手动调用边界记录 `heartbeat.invoked`；内部 wakeup 的业务活动仍由各自触发流程负责，避免扩大副作用语义。
- 本阶段执行采用可验证的即时 process 执行路径；队列调度、并发领取、取消/恢复、多 adapter 与完整 workspace 仍分别归 Step 13-15 扩展。

### 11D: 基线验收

- 建立 contract、workflow、scope 与 runtime integration tests。
- 提供从 organization、agent 创建到触发一次执行并查询结果的本地验收 demo。
- 对照上游记录本步骤已实现和延后的 endpoint、表与副作用清单。

实施记录：

- Contract tests 已覆盖 agent/heartbeat path、枚举、validator、数据库模型、migration、配置脱敏与 process runtime 的 HTTP 执行读取路径。
- Workflow tests 已覆盖生命周期 activity、配置 revision/session reset activity，以及失败的 process run 对 wakeup、run、event 与 activity 的持久化影响。
- Scope tests 已覆盖跨 organization agent 列表拒绝，以及 agent 不能调用同 organization 内的其他 agent。
- Acceptance flow 已覆盖通过 HTTP 创建 organization、创建 process agent、触发一次 heartbeat、读取 run 结果与 runtime state。
- 验收审查同时修复了新增 heartbeat dependency 覆盖已有 dependency 导出的回归，保留既有 service 导出边界。

### 11E: Codex Runtime Adapter

- 对照上游 `codex_local` contract 与 runtime 行为，实现真实 Codex 执行 adapter，不以通用 `process` 配置替代其对外语义。
- 实现 adapter 配置校验、认证/环境读取边界、命令调用、输出/错误/result event 映射，以及已有 heartbeat run/runtime state 链路接入。
- 保留 `process` 路径用于既有验收和通用执行测试；`codex_local` 成为本步骤验证智能体真实启动的目标路径。

实施记录：

- Runtime 已新增 `codex_local` adapter 注册与执行实现，按兼容命令边界调用 `codex exec --json --disable plugins`，支持 `command`、`cwd`、`model`、`modelReasoningEffort`、`search`、`dangerouslyBypassApprovalsAndSandbox`、`extraArgs`、`promptTemplate`、`env` 与 `timeoutSec` 基线配置。
- Adapter 已解析 Codex JSONL 的 `thread.started`、agent message 与 `turn.completed` usage，并将响应摘要、session id 和 token usage 返回至统一 run contract。
- Heartbeat 执行链路已将 `sessionIdAfter` 与 `usageJson` 持久化到 run，并同步更新 runtime state 的当前 session 和累计 token 字段。
- Contract integration test 通过受控 Codex 执行输出验证 CLI 参数、stdin prompt、run 读取与 runtime state 更新，不要求本地测试环境存在真实账号凭据。
- 真实对话消息作为 prompt 的来源归 11F；完整 session 续接、workspace 上下文和跨 runtime 增强仍按后续能力边界补齐。

### 11F: Agent 对话闭环

- 仅实现能够支撑 Agent 交互执行的最小 conversation/message contract、持久化、API 与 service 行为。
- 打通用户或 board 消息创建、关联 agent、直接调用 `codex_local` runtime、保存响应及查询消息的闭环。
- 不以本阶段实现宣称完整 Chat / Messenger 已交付；未被该调用链需要的会话能力和消息副作用继续归 Step 16。

实施记录：

- 上游核对确认 chat assistant 使用内部 `chat-*` invocation id 直接调用所选 Agent runtime，并不为对话回复建立持久化 `heartbeat_runs` 关系；本步骤按该边界修正了早期规划中的 run 关联假设。
- Shared contract 已实现 conversation/message 核心 path、枚举、payload type 与最小 validator。
- Database 已实现 `chat_conversations`、`chat_messages` schema/query 及 `20260527_000006_chats.py` migration，仅纳入 Agent 对话闭环依赖的上游核心表。
- Server 已实现 organization 内对话创建/列表/详情、消息读取及非流式消息回复入口；对话通过 `preferredAgentId` 选择 Agent runtime，并持久化 user/assistant message 与 `replyingAgentId`。
- Contract tests 已覆盖 schema/migration、payload/path 以及由 `codex_local` 执行输出产生并读取持久化 assistant reply 的 HTTP 链路。
- Context link、完整副作用和 Messenger 聚合归 Step 16；消息附件/产物引用与基础运行可见性归 Step 17；基础调试可见性归 Step 18。

## 已实现兼容清单

### API

| Method / path | 本步骤行为 |
| --- | --- |
| `GET /api/orgs/{orgId}/agents` | organization 内 agent 列表 |
| `POST /api/orgs/{orgId}/agents` | 创建 agent；省略 `name` 时由 server 分配个人名称 |
| `GET /api/orgs/{orgId}/agents/name-suggestion` | 获取当前 organization 可用的个人名称建议 |
| `GET /api/agents/{id}`、`PATCH /api/agents/{id}` | 详情与配置更新 |
| `POST /api/agents/{id}/pause`、`resume`、`terminate` | 生命周期操作 |
| `GET /api/orgs/{orgId}/agent-configurations` | organization 配置列表 |
| `GET /api/agents/{id}/configuration` | 脱敏配置读取 |
| `GET /api/agents/{id}/config-revisions`、`/{revisionId}` | 配置 revision 查询 |
| `POST /api/agents/{id}/config-revisions/{revisionId}/rollback` | 无敏感占位的配置回滚 |
| `GET /api/agents/{id}/runtime-state` | 运行状态查询 |
| `GET /api/agents/{id}/task-sessions` | task session 查询 |
| `POST /api/agents/{id}/runtime-state/reset-session` | task session 清理 |
| `POST /api/agents/{id}/wakeup`、`heartbeat/invoke` | 手动执行触发 |
| `GET /api/orgs/{orgId}/heartbeat-runs` | run 列表 |
| `GET /api/heartbeat-runs/{runId}`、`/events` | run 结果与事件读取 |
| `GET`、`POST /api/orgs/{orgId}/chats` | 对话列表与创建 |
| `GET /api/chats/{id}` | 对话详情 |
| `GET`、`POST /api/chats/{id}/messages` | 消息读取与 Agent 回复触发 |

### Tables

| Table | 本步骤用途 |
| --- | --- |
| `agents` | Agent 主对象和生命周期状态 |
| `agent_config_revisions` | 配置变更快照 |
| `agent_runtime_state` | 最近运行结果与 runtime 状态 |
| `agent_task_sessions` | task/session 状态边界 |
| `agent_wakeup_requests` | wakeup 持久化和状态结果 |
| `heartbeat_runs` | 执行实例、结果和失败状态 |
| `heartbeat_run_events` | 运行事件与输出记录 |
| `chat_conversations` | Agent 对话主体与首选回复 Agent |
| `chat_messages` | user/assistant 消息与回复 Agent 记录 |

### Activity

| Action | 产生条件 |
| --- | --- |
| `agent.created`、`agent.updated` | Agent 创建或配置更新 |
| `agent.paused`、`agent.resumed`、`agent.terminated` | 生命周期动作 |
| `agent.config_rolled_back` | 配置 revision 回滚 |
| `agent.runtime_session_reset` | runtime session 清理 |
| `heartbeat.invoked` | 手动 wakeup/invoke 入口触发执行 |
| `chat.created` | 创建 Agent 对话 |

## 延后能力

- Run 定时触发、队列领取、并发合并、取消、重试和中断恢复归 Step 13。
- `process`、`codex_local` 以外的 runtime adapter 及跨 runtime 的 session/environment/usage 深化归 Step 14。
- 完整 workspace 建立、复用、runtime service 与执行产物归 Step 15。
- cost summary 与 activity query 归 Step 19；budget、quota 与 skills analytics 治理归 Step 20。
- API key、真实用户认证与完整权限行为归对应后续接入步骤。

## 本地验收流程

启动使用本地开发 actor 的服务：

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
uv run alembic upgrade head
uv run server
```

在另一个 PowerShell 终端执行 organization、agent、heartbeat run 的完整路径：

```powershell
$base = "http://127.0.0.1:8000"
$python = (Get-Command python).Source

$org = curl.exe -s -X POST "$base/api/orgs" `
  -H "Content-Type: application/json" `
  -d '{"name":"Agent Run Demo"}' | ConvertFrom-Json

$agentBody = @{
  name = "Executor"
  role = "engineer"
  agentRuntimeType = "process"
  agentRuntimeConfig = @{
    command = $python
    args = @("-c", "print('step-11-ok')")
  }
} | ConvertTo-Json -Depth 4 -Compress

$agent = curl.exe -s -X POST "$base/api/orgs/$($org.id)/agents" `
  -H "Content-Type: application/json" `
  -d $agentBody | ConvertFrom-Json

$run = curl.exe -s -X POST "$base/api/agents/$($agent.id)/heartbeat/invoke" `
  -H "Content-Type: application/json" `
  -d '{}' | ConvertFrom-Json

curl.exe -s "$base/api/heartbeat-runs/$($run.id)"
curl.exe -s "$base/api/heartbeat-runs/$($run.id)/events"
curl.exe -s "$base/api/agents/$($agent.id)/runtime-state"
```

预期结果：经 Step 13 扩展后 `$run.status` 初始为 `queued`；随后查询到的 run detail 状态为 `succeeded` 且 `resultJson.stdout` 包含 `step-11-ok`，runtime state 的 `lastRunId` 与 `$run.id` 相同。

通过本地 Codex CLI 验收最小对话闭环：

```powershell
$codexBody = @{
  name = "Chat Codex"
  role = "engineer"
  agentRuntimeType = "codex_local"
  agentRuntimeConfig = @{ command = "codex" }
} | ConvertTo-Json -Depth 4 -Compress

$codexAgent = curl.exe -s -X POST "$base/api/orgs/$($org.id)/agents" `
  -H "Content-Type: application/json" `
  -d $codexBody | ConvertFrom-Json

$chatBody = @{
  title = "Codex Demo"
  preferredAgentId = $codexAgent.id
} | ConvertTo-Json -Compress

$chat = curl.exe -s -X POST "$base/api/orgs/$($org.id)/chats" `
  -H "Content-Type: application/json" `
  -d $chatBody | ConvertFrom-Json

curl.exe -s -X POST "$base/api/chats/$($chat.id)/messages" `
  -H "Content-Type: application/json" `
  -d '{"body":"Reply with one short readiness confirmation."}'

curl.exe -s "$base/api/chats/$($chat.id)/messages"
```

预期结果：发送消息请求返回一条 user message 和一条 assistant message，后续读取请求可以查询到相同持久化消息；该链路不会生成 `heartbeat_run`。

## 后续步骤边界

- Step 11E 已实现 `codex_local` runtime adapter，使 Agent 能通过已建立的 run contract 启动 Codex 并保存基线执行结果。
- Step 11F 已实现直接触发 Agent runtime 并记录回复的最小消息闭环；完整 Chat / Messenger 扩展仍归 Step 16。
- Step 12 实现 Goal CRUD、层级与 `ownerAgentId` 同 organization 引用校验。
- Step 13 在本步骤 run 基线上扩展调度、并发领取、取消、中断恢复和幂等语义。
- Step 14 扩展 `codex_local` 以外的更多 runtime adapter 类型及跨 runtime 的 session/environment/usage 兼容行为。
- Step 15 落地完整 workspace 生命周期与执行产物；本步骤只实现首个执行路径必须使用的最小上下文。
- Step 19/20 落地 cost、activity 与 budget 治理；本步骤只保留执行闭环必须产生的记录。
- Avatar、attachment/storage 与完整 Chat / Messenger 不因最小 Agent 对话闭环而提前并入本步骤。

## 验收

- Tests 验证 agent 管理、organization scope、配置变更和上游枚举边界。
- Tests 验证一次 wakeup/heartbeat run 能调用实际 adapter，并持久化兼容状态与结果。
- Tests 验证 `codex_local` 可经最小 conversation/message 链路触发并保存响应；chat invocation 不伪造 heartbeat run 关联。
- Step 12 可以使用本步骤已实现 agent 对 `Goal.ownerAgentId` 做同 organization 引用校验。
