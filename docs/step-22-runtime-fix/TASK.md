# Step 22: Runtime Tool & Output Bug Fix

状态：待开发

## 目标

集中修复本地 runtime 执行闭环里的两个阻塞 bug：tool schema 注入不清导致 OpenCode 工具调用失败，以及 stdout/stderr/json event 不能实时落库导致 UI 长时间看不到执行过程。

典型问题一：`opencode_local` 中模型调用 `bash` 工具时必须知道 `description`、`command` 等参数约束，不能让模型自行猜测工具 schema。

典型问题二：runtime 已经产生 stdout/stderr 或 JSON event，但 server/UI 需要等进程结束、缓冲区 flush 或长时间超时后才看到输出，导致任务详情页无法动态展示执行过程。

## 上游证据

- `D:\coding\rudder\packages\agent-runtimes\opencode-local\`
- `D:\coding\rudder\packages\agent-runtimes\codex-local\`
- `D:\coding\rudder\packages\agent-runtimes\claude-local\`
- OpenCode CLI 内置 tool schema 与本地 `opencode run --format json` 输出协议。

## 任务

- 为 `opencode_local`、`codex_local`、`claude_local` 建立 runtime tool capability 描述边界。
- 在 runtime prompt/instructions/context 中注入可用工具、关键参数、禁止猜测 schema 的说明。
- 明确 `opencode_local` 内置 `bash` 工具调用必须携带 `description` 和 `command`，避免只传 `command` 造成 schema error。
- 将工具 schema error 从 adapter 崩溃中区分出来，保留原始 tool name、缺失字段、input 和可读诊断。
- 对 OpenCode tool error 做结果归一化：如果 run 后续仍能继续并产生有效结果，不应仅因早期 tool error 直接覆盖最终 run error；如果进程终态失败，则错误摘要应指向首个阻断性错误和退出原因。
- 为 `opencode_local`、`codex_local`、`claude_local` 明确 stdout/stderr/json event 的实时读取策略，避免等待进程结束或长时间 buffer flush 才写入 run events/log。
- 将 runtime 输出按 chunk/event 持续写入 run log，并按现有 run event contract 生成可轮询、可流式读取的增量事件。
- 增加 contract/workflow tests 覆盖：OpenCode bash 缺 `description` 的诊断、正确 schema guidance 注入、tool error 后续恢复、进程 `^C`/取消与 tool error 的错误优先级、stdout/stderr 在运行期间增量落库。

## 边界

- 不新增插件 tool dispatcher；插件工具归 Step 27。
- 不把 OpenCode/Codex/Claude CLI 内置工具改造成 Octopus 自有工具系统；本步骤只负责能力描述、schema guidance、输出 ingestion、错误诊断和兼容归一化。
- 不改变 runtime adapter 的业务触发协议；adapter 继续复用 Step 11/13/14 的 run contract，同时补充 tool capability 运行上下文。
- 不处理 cost、budget、governance、auth 或 plugin 子系统。

## 验收

- Tests 覆盖 `opencode_local` tool capability/schema guidance 注入。
- Tests 覆盖 `bash` 缺少 `description` 时返回可诊断错误，不再表现为不可解释 adapter 崩溃。
- Tests 覆盖工具调用错误与进程取消/失败同时出现时的错误优先级。
- Tests 覆盖 stdout/stderr/json event 在 runtime 运行期间持续进入 run events/log，UI 不需要等进程结束才能看到过程输出。
- Tests 覆盖 runtime tool capability 不改变 run API shape、状态值和 existing adapter contract。
