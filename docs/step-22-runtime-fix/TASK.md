# Step 22: Runtime & Closed-loop Alignment Fix

状态：已完成

## 目标

集中补齐当前最小任务执行闭环中已经暴露的上游对齐缺口，优先保证“创建 issue -> 分配/执行 -> runtime 输出 -> workspace 产物 -> issue/chat 可见”能稳定跑通。

本步骤不是新增 Cost、Budget、Auth 或 Plugin 模块；它只补强已实现主链路中阻塞调试和真实任务执行的缺口。

典型问题一：`opencode_local` 中模型调用 `bash` 工具时必须知道 `description`、`command` 等参数约束，不能让模型自行猜测工具 schema。

典型问题二：runtime 已经产生 stdout/stderr 或 JSON event，但 server/UI 需要等进程结束、缓冲区 flush 或长时间超时后才看到输出，导致任务详情页无法动态展示执行过程。

典型问题三：Workspace、Issue 执行闭环和 Chat/Messenger 已有基础实现，但仍需要对照上游 `workspace-runtime.*`、issue closeout/review/followup、chat stream/generation lock/helper 细节做补强，否则任务执行结果仍可能无法稳定登记、展示或恢复。

## 上游证据

- `D:\coding\rudder\packages\agent-runtimes\opencode-local\`
- `D:\coding\rudder\packages\agent-runtimes\codex-local\`
- `D:\coding\rudder\packages\agent-runtimes\claude-local\`
- OpenCode CLI 内置 tool schema 与本地 `opencode run --format json` 输出协议。
- `D:\coding\rudder\server\src\services\workspace-runtime.ts`
- `D:\coding\rudder\server\src\services\workspace-runtime.helpers.ts`
- `D:\coding\rudder\server\src\services\workspace-runtime.lifecycle.ts`
- `D:\coding\rudder\server\src\services\workspace-runtime.services.ts`
- `D:\coding\rudder\server\src\services\workspace-runtime.comments.ts`
- `D:\coding\rudder\server\src\services\workspace-backups.ts`
- `D:\coding\rudder\server\src\services\managed-workspace-preflight.ts`
- `D:\coding\rudder\server\src\services\workspace-operation-log-store.ts`
- `D:\coding\rudder\server\src\services\issue-assignment-wakeup.ts`
- `D:\coding\rudder\server\src\services\issue-review-wakeup.ts`
- `D:\coding\rudder\server\src\services\runtime-kernel\`
- `D:\coding\rudder\server\src\services\chat-generation-locks.ts`
- `D:\coding\rudder\server\src\services\chat-assistant.helpers.ts`
- `D:\coding\rudder\server\src\routes\chats.stream-routes.ts`
- `D:\coding\rudder\server\src\routes\messenger.ts`

## 任务

### 22A: Runtime tool schema 与实时输出

- 为 `opencode_local`、`codex_local`、`claude_local` 建立 runtime tool capability 描述边界。
- 在 runtime prompt/instructions/context 中注入可用工具、关键参数、禁止猜测 schema 的说明。
- 明确 `opencode_local` 内置 `bash` 工具调用必须携带 `description` 和 `command`，避免只传 `command` 造成 schema error。
- 将工具 schema error 从 adapter 崩溃中区分出来，保留原始 tool name、缺失字段、input 和可读诊断。
- 对 OpenCode tool error 做结果归一化：如果 run 后续仍能继续并产生有效结果，不应仅因早期 tool error 直接覆盖最终 run error；如果进程终态失败，则错误摘要应指向首个阻断性错误和退出原因。
- 为 `opencode_local`、`codex_local`、`claude_local` 明确 stdout/stderr/json event 的实时读取策略，避免等待进程结束或长时间 buffer flush 才写入 run events/log。
- 将 runtime 输出按 chunk/event 持续写入 run log，并按现有 run event contract 生成可轮询、可流式读取的增量事件。
- 确保 `cancelled`、`timed_out`、runtime error、tool error 也能在 run events/log 中形成可读过程记录，不能只在最终 run row 中出现。
- 增加 contract/workflow tests 覆盖：OpenCode bash 缺 `description` 的诊断、正确 schema guidance 注入、tool error 后续恢复、进程 `^C`/取消与 tool error 的错误优先级、stdout/stderr 在运行期间增量落库、取消/超时/失败实时事件一致性。

### 22B: Workspace runtime 对齐补强

- 对照上游 `workspace-runtime.*` 审查当前 workspace runtime service、operation、work product、preflight 和 operation log 行为。
- 补齐必要的 managed workspace preflight 结果记录，确保 runtime 执行前能解释 cwd、workspace source、service intents 和失败原因。
- 补齐 workspace operation log store 与 run log 的关系，避免只写内存摘要或只在最终 run result 中体现。
- 补强 workspace runtime service 生命周期：启动、绑定 run、释放、失败清理和可见状态必须与现有 run/workspace operation 查询一致。
- 审查 workspace backup/browser 相关上游能力；只补齐任务执行闭环必须依赖的 server 行为，完整 backup/browser UI 能力不在本步骤扩张。

### 22C: Issue 执行闭环补强

- 用真实 issue 执行路径验证 checkout、heartbeat-context、assignment wakeup、review wakeup、passive followup 和 work product 登记。
- 确保成功 run 产生的文件或结构化 workProducts 能稳定进入 issue documents/work-products API。
- 确保 closeout、review、followup 不会因为 runtime 输出延迟、缺失 tool schema 或 workspace 产物登记失败而卡在 `in_progress`。
- 对齐上游 runtime-kernel closeout/followup 行为，只补齐 server 已有 issue/run/workspace 模型需要的状态和事件，不发明新的项目经理式自动编排。

### 22D: Chat / Messenger 执行可见性补强

- 对照上游 `chat-generation-locks.ts`、`chat-assistant.helpers.ts` 和 `chats.stream-routes.ts` 审查当前 chat sync/stream/proposal 行为。
- 补齐必要的 generation lock，避免同一 conversation 并发发送导致重复 runtime 调用、消息顺序错乱或 SQLite lock。
- 确保 chat stream 与非 stream 路径的 issue proposal、manual approval、auto create 行为一致。
- 确保 assistant transcript、runtime error、tool/output events 和最终消息状态在 UI 刷新后仍可解释。
- Messenger 只补强现有 system thread 和业务引用可见性，不新增 dashboard/sidebar 等外围能力。

### 22E: 端到端闭环验收脚本

- 增加一个最小真实闭环验收脚本或 workflow test，覆盖：创建 issue、分配 agent、执行任务、实时读取 run stream/log、生成或登记产物、查询 issue documents/work-products、确认 run 最终状态。
- 脚本必须使用公开 API 或现有 service 边界，不直接伪造最终数据库状态。
- 脚本输出要能定位失败层级：agent 配置、workspace preflight、runtime spawn、tool schema、stdout/log ingestion、work product 登记、issue closeout/followup。
- 如果外部 CLI/runtime 不可用，保留等价的 process adapter 或 fake adapter 测试路径；真实 opencode/codex/claude 手工验证步骤单独记录。

## 边界

- 不新增插件 tool dispatcher；插件工具归 Step 27。
- 不把 OpenCode/Codex/Claude CLI 内置工具改造成 Octopus 自有工具系统；本步骤只负责能力描述、schema guidance、输出 ingestion、错误诊断和兼容归一化。
- 不改变 runtime adapter 的业务触发协议；adapter 继续复用 Step 11/13/14 的 run contract，同时补充 tool capability 运行上下文。
- 不处理 cost、budget、governance、auth 或 plugin 子系统。
- 不把 workspace backup/browser、dashboard、calendar、automation 等上游外围能力混入本步骤；只处理当前最小执行闭环必须依赖的 server 行为。
- 不改 UI/CLI；如发现 UI/CLI 必须配合的行为，只记录 server 已提供的契约和 UI 需要消费的字段。

## 验收

- Step 22 最小闭环验收入口：
  `uv run pytest tests/contract/test_step22_closed_loop_acceptance.py -q`
- Tests 覆盖 `opencode_local` tool capability/schema guidance 注入。
- Tests 覆盖 `bash` 缺少 `description` 时返回可诊断错误，不再表现为不可解释 adapter 崩溃。
- Tests 覆盖工具调用错误与进程取消/失败同时出现时的错误优先级。
- Tests 覆盖 stdout/stderr/json event 在 runtime 运行期间持续进入 run events/log，UI 不需要等进程结束才能看到过程输出。
- Tests 覆盖取消、超时、runtime error、tool error 都会形成可读实时事件，UI 不再只看到长期 `in_progress`。
- Tests 覆盖 runtime tool capability 不改变 run API shape、状态值和 existing adapter contract。
- Tests 或 workflow 覆盖 workspace preflight、runtime service、workspace operation log 和 work product 登记的端到端可见性。
- Tests 或 workflow 覆盖 issue execute 成功后 run、events/log、documents/work-products、closeout/followup 状态可查询。
- Tests 覆盖 chat stream 与非 stream 在 issue proposal、manual approval、auto create 和 runtime error 场景下行为一致。
- 手工或脚本化 demo 能复现：创建 issue、分配 agent、执行任务、实时看到输出、任务详情看到 run 与产物、chat/messenger 侧能解释结果。
