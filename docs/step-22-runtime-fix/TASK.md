# Step 22: Runtime & Closed-loop Alignment Fix

状态：已完成

## 目标

集中补齐当前最小任务执行闭环中已经暴露的上游对齐缺口，优先保证“创建 issue -> 分配/执行 -> runtime 输出 -> workspace 产物 -> issue/chat 可见”能稳定跑通。

本步骤不是新增 Cost、Budget、Auth 或 Plugin 模块；它只补强已实现主链路中阻塞调试和真实任务执行的缺口。

典型问题一：`opencode_local` 中模型调用 `bash` 工具时必须知道 `description`、`command` 等参数约束，不能让模型自行猜测工具 schema。

典型问题二：runtime 已经产生 stdout/stderr 或 JSON event，但 server/UI 需要等进程结束、缓冲区 flush 或长时间超时后才看到输出，导致任务详情页无法动态展示执行过程。

典型问题三：Workspace、Issue 执行闭环和 Chat/Messenger 已有基础实现，但仍需要对照上游 `workspace-runtime.*`、issue closeout/review/followup、chat stream/generation lock/helper 细节做补强，否则任务执行结果仍可能无法稳定登记、展示或恢复。

## 上游证据

- `D:\coding\upstream-reference\packages\agent-runtimes\opencode-local\`
- `D:\coding\upstream-reference\packages\agent-runtimes\codex-local\`
- `D:\coding\upstream-reference\packages\agent-runtimes\claude-local\`
- OpenCode CLI 内置 tool schema 与本地 `opencode run --format json` 输出协议。
- `D:\coding\upstream-reference\server\src\services\workspace-runtime.ts`
- `D:\coding\upstream-reference\server\src\services\workspace-runtime.helpers.ts`
- `D:\coding\upstream-reference\server\src\services\workspace-runtime.lifecycle.ts`
- `D:\coding\upstream-reference\server\src\services\workspace-runtime.services.ts`
- `D:\coding\upstream-reference\server\src\services\workspace-runtime.comments.ts`
- `D:\coding\upstream-reference\server\src\services\workspace-backups.ts`
- `D:\coding\upstream-reference\server\src\services\managed-workspace-preflight.ts`
- `D:\coding\upstream-reference\server\src\services\workspace-operation-log-store.ts`
- `D:\coding\upstream-reference\server\src\services\issue-assignment-wakeup.ts`
- `D:\coding\upstream-reference\server\src\services\issue-review-wakeup.ts`
- `D:\coding\upstream-reference\server\src\services\runtime-kernel\`
- `D:\coding\upstream-reference\server\src\services\chat-generation-locks.ts`
- `D:\coding\upstream-reference\server\src\services\chat-assistant.helpers.ts`
- `D:\coding\upstream-reference\server\src\routes\chats.stream-routes.ts`
- `D:\coding\upstream-reference\server\src\routes\messenger.ts`

## 任务

### 22A: Runtime tool schema 与实时输出

- 为 `opencode_local`、`codex_local`、`claude_local` 建立 runtime tool capability 描述边界。
- 在 runtime prompt/instructions/context 中注入可用工具、关键参数、禁止猜测 schema 的说明。
- 在 runtime prompt 中注入 workspace output contract：可以读取任务要求的外部源码路径，但持久产物必须写入 Octopus 受管 worktree 或组织 artifacts 目录，避免写到外部源码目录后 UI 无法展示。
- 在 runtime prompt/env 中注入 issue/run 专属产物目录：`OCTOPUS_ISSUE_ARTIFACTS_DIR` 与 `OCTOPUS_RUN_ARTIFACTS_DIR`。单次执行产生的持久文件优先写入 run 目录；跨 run 共享的任务级文件写入 issue 目录。
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
- 对齐上游 `organization-workspace-browser` 的最小只读能力：server 提供组织工作区真实目录列表、文件预览和图片 content 读取；UI 的“组织 -> 工作区”页面必须消费真实 API，不再用项目/智能体数据伪造文件树。
- 组织工作区浏览根目录固定为 `OCTOPUS_HOME/instances/<instance_id>/organizations/<org_id>/workspaces`，默认 `~/.octopus/instances/default/organizations/<org_id>/workspaces`；运行产物通过 `artifacts/` 展示。该视图与 issue documents/work-products 是两个不同入口，前者是物理工作区文件浏览，后者是任务维度登记视图。
- 每次 issue run 会预创建组织 artifacts 下的专属目录：`artifacts/issues/<issue_id>/runs/<run_id>/`。该目录属于组织工作区的一部分，UI 可通过组织工作区浏览器打开。
- 补齐项目 workspace 管理闭环：server 暴露 project workspace CRUD；UI 项目配置页支持新增本地 cwd/repo 工作区、设为主工作区和删除。项目 workspace 是可选绑定；任务执行优先使用可用主项目工作区，不可用时 fallback 到组织共享工作区。
- 项目 workspace CRUD 与“执行工作区策略”不是同一个配置：前者登记项目可用的 cwd/repo；后者决定 run 使用共享工作区、独立工作区或操作分支等策略。UI 必须分区展示，不能把 cwd/repo 绑定塞进策略 JSON。

### 22C: Issue 执行闭环补强

- 用真实 issue 执行路径验证 checkout、heartbeat-context、assignment wakeup、review wakeup、passive followup 和 work product 登记。
- 确保成功 run 产生的文件或结构化 workProducts 能稳定进入 issue documents/work-products API。
- 成功 run 后扫描受管 worktree 与组织 artifacts 中本次执行新增/修改的有限文本产物，并登记为 issue work-products；外部源码目录只作为读取对象，不作为默认产物落点。
- run 专属 artifacts 目录扫描结果登记为 issue work-products 时，metadata 必须带 `workspaceBrowserPath`，让 UI 能从任务产物直接跳转到“组织 -> 工作区”中的真实文件位置。
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
- UI 只允许补齐本步骤闭环必需的组织工作区浏览与运行可见性消费，不扩 dashboard、calendar、plugin、backup 等外围 UI；CLI 不在本步骤扩张。

## 验收

- Step 22 最小闭环验收入口：
  `uv run pytest tests/contract/test_step22_closed_loop_acceptance.py -q`
- Tests 覆盖 `opencode_local` tool capability/schema guidance 注入。
- Tests 覆盖 local runtime prompt 注入 workspace output contract，明确产物写入受管 worktree/artifacts。
- Tests 覆盖 `bash` 缺少 `description` 时返回可诊断错误，不再表现为不可解释 adapter 崩溃。
- Tests 覆盖工具调用错误与进程取消/失败同时出现时的错误优先级。
- Tests 覆盖 stdout/stderr/json event 在 runtime 运行期间持续进入 run events/log，UI 不需要等进程结束才能看到过程输出。
- Tests 覆盖取消、超时、runtime error、tool error 都会形成可读实时事件，UI 不再只看到长期 `in_progress`。
- Tests 覆盖 runtime tool capability 不改变 run API shape、状态值和 existing adapter contract。
- Tests 或 workflow 覆盖 workspace preflight、runtime service、workspace operation log 和 work product 登记的端到端可见性。
- Tests 或 workflow 覆盖 worktree 与 organization artifacts 中生成的文件都会登记为 issue work-products。
- Tests 覆盖 organization workspace browser 可列出 `artifacts/`、读取文本产物、预览图片产物，并拒绝路径越界。
- Tests 覆盖 project workspace CRUD、主工作区切换和删除主工作区后的 fallback 主工作区选择；UI tests 覆盖项目配置页新增、设主、删除项目工作区。
- UI tests 覆盖“组织 -> 工作区”页面从 `/api/orgs/{orgId}/workspace/files` 和 `/api/orgs/{orgId}/workspace/file` 读取真实文件树与文件内容，不再展示本地构造的假树。
- Tests 或 workflow 覆盖 issue execute 成功后 run、events/log、documents/work-products、closeout/followup 状态可查询。
- Tests 覆盖 chat stream 与非 stream 在 issue proposal、manual approval、auto create 和 runtime error 场景下行为一致。
- 手工或脚本化 demo 能复现：创建 issue、分配 agent、执行任务、实时看到输出、任务详情看到 run 与产物、chat/messenger 侧能解释结果。
