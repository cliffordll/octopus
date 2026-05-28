# Step 14: Runtime Adapter 扩展

状态：已完成

## 上游依据

- 参考工程：`D:\coding\rudder`
- Runtime 枚举：`packages/shared/src/constants.ts`
- Runtime registry：`server/src/agent-runtimes/registry.ts`
- Server 内置 adapter：`server/src/agent-runtimes/process/`、`server/src/agent-runtimes/http/`
- 环境检查入口：`POST /api/orgs/:orgId/adapters/:type/test-environment`

## 依赖边界

Step 11 已定义统一 adapter contract，并由 11C 提供 `process` 路径、由 11E 提供 `codex_local` 智能体执行路径。本步骤扩展其余上游 runtime 覆盖范围，不承担首次打通 Agent 交互执行闭环。

Step 13 已补齐 run 调度、取消、恢复和事件查询。本步骤必须复用既有 run 状态机，不新增独立执行模型。

## 14A：HTTP Adapter

- 实现 `http` runtime adapter。
- 支持 `url`、`method`、`headers`、`payloadTemplate`、`timeoutSec` 等上游配置字段。
- 将 HTTP 状态、响应 body、超时和网络错误归一化为 `RuntimeExecutionResult`。
- 确保 heartbeat run 与 chat direct invocation 均通过统一 adapter contract 调用。

## 14B：Runtime 环境检查

- 新增上游兼容路径 `POST /api/orgs/{orgId}/adapters/{type}/test-environment`。
- 输入使用 `agentRuntimeConfig`，输出包含 runtime type、整体 status 与 checks。
- `process`、`codex_local`、`http` 返回可执行的环境检查结果。
- 对当前不实施的 runtime 返回兼容的 unavailable/failed 检查结果，不抛出未实现异常。

## 14C：本地 CLI Adapter

- 实现 `claude_local` runtime adapter。
- 实现 `opencode_local` runtime adapter。
- 两个本地 CLI adapter 必须复用现有 child process 运行、取消、日志和 `processPid/processStartedAt` 记录边界。
- `claude_local` 与 `opencode_local` 的 session、usage、错误解析只实现上游可核对且当前 server 需要的集合；quota window 不在本步骤展开。

## 14D：模型发现与 Skills Sync

- 实现 runtime model discovery 的服务端兼容边界。
- 实现 runtime skills sync 的服务端兼容边界。
- `process`、`http` 可返回空模型/空 skills 或不支持结果，但响应结构必须兼容。
- `codex_local`、`claude_local`、`opencode_local` 按上游证据返回可用模型和 skills sync 结果；无法访问本地 CLI 或配置不完整时返回可解释的检查失败，不改变业务 API。

## 14E：Registry 与错误归一化

- Registry 不再对已知 runtime type 直接抛出 Python 内部异常；未实施 runtime 应返回可解释的 adapter unavailable 失败。
- Run 结果中的 `errorCode`、`error`、`resultJson`、`usageJson` 和 `sessionIdAfter` 不因 adapter 类型不同而改变外部结构。
- Contract tests 覆盖 runtime type 接入、环境检查 path、模型发现、skills sync 和未实施 runtime 的错误形态。

## 当前实施记录

- Shared 已新增 adapter models、environment test、agent skills snapshot/sync API path、validator 和响应类型。
- Runtime registry 已接入 `http`、`claude_local`、`opencode_local`，并对当前未纳入的已知 runtime 返回 unavailable adapter。
- `http` adapter 已支持 `url`、`method`、`headers`、`payloadTemplate`、`timeoutSec`，并将 HTTP 成功、非 2xx、超时和网络错误归一化为 `RuntimeExecutionResult`。
- `claude_local` 与 `opencode_local` 已通过本地 CLI adapter 复用 process child execution、取消、日志和 `processPid/processStartedAt` 记录边界。
- Server 已新增 `GET /api/orgs/{orgId}/adapters/{type}/models`、`POST /api/orgs/{orgId}/adapters/{type}/test-environment`、`GET /api/agents/{id}/skills`、`POST /api/agents/{id}/skills/sync`。
- Runtime model discovery 与 skills sync 已提供兼容响应结构；当前 `process`/`http` 返回空能力，`codex_local`/`claude_local`/`opencode_local` 返回基础模型或同步结果。
- Agent 已补齐上游兼容的说明与技能字段边界：`capabilities` 作为智能体能力说明直接持久化，`agentRuntimeConfig.promptTemplate` 作为 runtime prompt 配置透传，`desiredSkills` 通过 Agent metadata 持久化并在 Agent detail、configuration、skills snapshot/sync 中返回。
- Skills sync 已使用上游一致的 `desiredSkills` 入参，成功同步后记录 `agent.skills_synced` 活动。
- Tests 已覆盖 Step 14 contract、environment/model/skills API、未纳入 runtime unavailable 响应、`http` heartbeat run 执行，以及 `claude_local`/`opencode_local` 本地 CLI 执行链路。

## 不包含

- `gemini_local`、`cursor`、`pi_local` 本步骤不做。
- `openclaw_gateway`、`hermes_local` 本步骤不做完整执行实现。
- Workspace 生命周期与产物持久化，归 Step 15。
- Workspace runtime service 建立、复用、释放和停止，归 Step 15。
- Cost/budget 治理，归 Step 16。
- Quota window 归集、展示和治理联动，归 Step 16。
- 触发 Codex Agent 的最小 conversation/message 链路，归 Step 11F。

## 验收

- `http` adapter 可以通过 heartbeat run 执行，并将成功、非 2xx、超时和网络错误写入兼容 run 结果。
- Runtime environment test API 对 `process`、`codex_local`、`http`、`claude_local`、`opencode_local` 有明确检查结果；对 `gemini_local`、`cursor`、`pi_local`、`openclaw_gateway`、`hermes_local` 返回可解释的未纳入结果。
- `claude_local` 与 `opencode_local` 的执行、取消、日志、进程元数据和失败行为复用 Step 11/13 的 adapter contract 与 run 状态机。
- Runtime model discovery 与 skills sync 对已纳入 runtime 有兼容响应，对未纳入 runtime 有明确未支持结果。
- 创建/更新 Agent 时，`capabilities`、`agentRuntimeConfig.promptTemplate`、`desiredSkills` 能按上游字段形状保存和返回；skills sync 后再次查询 Agent 与 skill snapshot 能看到最新 `desiredSkills`。
- Tests 证明 runtime 差异不会改变业务 API 或 run 状态语义。
