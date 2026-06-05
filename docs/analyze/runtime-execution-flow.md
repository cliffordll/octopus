# 智能体运行时执行链路分析报告

## 1. 目标

本文分析一次智能体运行从 server 触发到任务成功完成的完整链路，重点说明运行时需要哪些资源、skills、上下文和配置，这些信息如何流转，以及智能体输出如何被 server 接收、落库、登记和展示。

该报告用于回答：

- runtime 是怎么被启动的。
- `cwd`、`AGENT_HOME`、managed home、workspace 和 artifacts 分别是什么。
- agent instructions、skills、resources、provider/model 配置如何进入运行时。
- 智能体如何输出 stdout/stderr、结构化结果、文件产物和任务状态。
- 什么才算一次任务执行成功。

## 2. 核心对象

### 2.1 Agent

Agent 是执行主体。关键配置包括：

- `agent_runtime_type`：选择 runtime adapter，例如 `process`、`codex_local`、`opencode_local`、`claude_local`。
- `agent_runtime_config`：传给 runtime adapter 的执行配置，例如 model、cwd、instructions 路径、extra args。
- `runtime_config`：server 控制层配置，例如 heartbeat 策略、并发限制。
- enabled skills：agent 选择启用的组织 skill 或私有 skill，当前选择记录在 `agent_enabled_skills`。
- instructions bundle：`SOUL.md`、`HEARTBEAT.md`、`TOOLS.md`、`MEMORY.md` 等说明文件，DB 锚点在 `agents.agent_runtime_config`。

### 2.2 Issue / Chat

Issue 和 Chat 是常见触发入口。

- Issue 触发时，server 会围绕 `issueId` 构造执行上下文。
- Chat 触发时，server 会围绕 conversation、message、selected agent 和 context links 构造对话上下文。
- 如果 chat 或 issue 绑定 `projectId`，运行时应获得项目上下文和项目资源。
- Chat 中的 `issue_proposal` 是“创建 issue 的草案”，不是 issue 本身，也不表示任务已经开始执行。

### 2.3 Heartbeat Run

`Heartbeat Run` 是历史命名。在当前系统里，它更准确地表示一次 agent runtime execution 的持久化主记录；不只限于周期性 heartbeat，也包括 issue execute、assignment wakeup、review wakeup、manual invoke、retry 等触发来源。

`heartbeat_runs` 记录：

- run 状态：`queued`、`running`、`succeeded`、`failed`、`cancelled`、`timed_out`。
- agent、org、issue、wakeup source。
- started/finished 时间。
- stdout/stderr 摘要。
- result JSON、usage、session id。
- run log 与 events。

运行时执行过程不能只存在内存里，必须能通过 run 查询和 events/log 复盘。

如果一次 run 来自 issue，它会通过 `context_snapshot.issueId` 或 `context_snapshot.primaryIssueId` 关联到 issue；issue 执行中还会在 `issues.execution_run_id`、`issues.checkout_run_id` 上指向当前 run。run 是执行主记录，但 issue 的业务事实不只存在 `heartbeat_runs`：

- `issues`：issue 本体、状态、assignee/reviewer、当前执行锁。
- `activity_log`：issue 行为轨迹，可通过 `entity_type="issue"`、`entity_id=issueId`、`run_id=heartbeatRunId` 关联到具体 run。
- `issue_comments`：评论、closeout、执行说明。
- `issue_documents`：任务文档。
- `issue_work_products`：运行产物或交付物。
- `issue_attachments`：附件。
- `issue_approvals`：approval 与 issue 的关联。
- `heartbeat_run_events` 和 run log：runtime 执行过程、stdout/stderr、生命周期事件。

run 不直接来自 Chat；run 可以来自 Chat 转化后的 Issue。

### 2.4 Workspace

Workspace 分为几类：

- `cwd`：current working directory（当前工作目录），runtime 子进程实际启动目录。相对路径读写默认发生在这里。
- `project workspace`：项目绑定的源码或本地工作目录，通常作为任务执行的优先 cwd。
- `organization workspace`：Octopus 管理的组织共享目录，存放 agents、skills、plans、artifacts 等组织级内容。
- `execution workspace`：一次 run 解析出的执行工作区上下文，可能来自项目工作区，也可能 fallback 到组织工作区。
- `agent workspace home`：Octopus 给某个产品 agent 准备的长期目录，通常位于 organization workspace 下的 `agents/<agentWorkspaceKey>/`，用于保存该 agent 的 `instructions/` 和 agent-private `skills/`。
- `runtime managed HOME`：启动某个 local runtime CLI 时为子进程准备的隔离 HOME，通常按 runtime type、org、agent 生成，用于放 CLI 配置、credential 链接或副本、materialized skills 和 runtime session 状态。
- `AGENT_HOME`：运行时环境变量。在当前 local runtime 中，`AGENT_HOME` 通常指向 `runtime managed HOME`，不等同于 `agent workspace home`，也不等同于任务源码目录。

这里的 `fallback` 是“兜底方案”：优先使用 project workspace；如果 project 没配置 cwd、cwd 不存在或不可用，再退回到 Octopus 管理的 execution workspace / organization workspace。

当前 canonical organization workspace 路径应按 instance 维度解析：

```text
<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/organizations/<orgId>/workspaces

开发默认使用本地 SQLite 时通常等价于：
.octopus/instances/default/organizations/<orgId>/workspaces
```

`OCTOPUS_HOME` 的解析规则应与数据库同源：

- 显式设置 `OCTOPUS_HOME` 时，以该值为准。
- 未设置 `OCTOPUS_HOME` 且 `OCTOPUS_DATABASE_URL` 是本地 SQLite 文件时，默认 home 是数据库文件同级的 `.octopus/`。
- 使用 PostgreSQL、`:memory:` 或无法推导本地 DB 文件时，才退回用户目录 `~/.octopus`。

因此开发阶段可以使用：

```text
D:/coding/octopus/octopus.db
D:/coding/octopus/.octopus
```

正式或桌面运行也可以使用用户目录，但 DB 和 home 应一起切换，避免同一个 DB 中持久化出不同 `instructionsRootPath` / workspace root。

本地如果还存在下面这种路径，应视为 legacy layout 或迁移残留：

```text
.octopus/organizations/<orgId>/workspaces
```

`ensure_organization_workspace_root(orgId)` 会在使用组织工作区前检查 legacy layout：如果 canonical root 为空，会把 legacy `workspaces/` 移到 canonical instance 路径；如果 canonical root 已存在，会合并 legacy 下未冲突的内容，冲突内容保留在 legacy path，避免覆盖数据。

如果 UI 的“组织 - 工作区 - 文件”与 runtime / skill / artifact 写入使用了不同路径，就会出现文件树为空或数据分散的问题。例如 UI workspace browser 当前应读 canonical instance 路径；如果真实内容仍写在 legacy 路径，ensure 入口会先迁移/合并再展示。

## 3. 执行主链路

### 3.1 触发

一次任务执行通常从以下入口开始：

1. 用户或智能体创建 issue。
2. issue 被分配给 agent。
3. server 创建 wakeup request。
4. server 创建或 claim 一个 `heartbeat_run`。
5. run 进入 `queued`，随后被 dispatcher/scheduler claim 为 `running`。

在 Chat 场景下，assistant 可能先生成 issue proposal。根据组织配置：

- 普通对话：selected agent 只生成 assistant message。
- `issue_proposal`：当用户要求创建 task/issue/ticket 时，assistant 返回结构化草案，例如 title、description、priority、assigneeAgentId、projectId 等。
- `auto_create`：server 保存 `issue_proposal` assistant message 后，立即将草案 convert to issue，绑定 conversation primary issue，并追加 `issue_created` system message。
- `manual_approval`：server 保存 `issue_proposal` assistant message，并创建 `chat_issue_creation` approval；用户批准后才 convert to issue。
- `disabled`：server 只保留 proposal/回复，不创建任务。

Chat 草案落成 issue 后，仍不等于 issue 已执行。正式任务执行继续走 Issue assignment、heartbeat wakeup 或 `POST /api/issues/{id}/execute` 链路。

### 3.2 Preflight

run 正式调用 runtime adapter 前，server 应做 workspace preflight：

- 解析 issue/project/agent。
- 解析 project workspace 或 fallback 到 organization workspace。
- 准备组织工作区目录。
- 准备 organization artifacts 目录。
- 生成 workspace context 和 env。
- 记录 workspace operation，说明 runtime 将在哪个 cwd 执行。

这些步骤不只是“设置输出物目录”。它们同时确定两类路径：

- runtime execution cwd：子进程启动目录，决定相对路径默认读写到哪里。
- durable artifact directory：server 注入给 runtime 的 organization artifacts 目录，决定报告、截图、CSV、handoff 文件等交付物应该放哪里。

二者不能混用。`cwd` 是执行位置，不等于产物归档位置；artifacts 目录是交付物的优先落点，不等于源码工作目录。严格对齐上游时，默认只有 organization artifacts；issue/run 关联由 DB work products 元数据表达，不靠文件系统目录分层表达。

如果 preflight 失败，adapter 不应继续执行，run/event/log 要记录可读失败原因。

### 3.3 Runtime Config 汇总

server 调用 adapter 前会汇总 runtime config：

- agent 的 `agent_runtime_config`。
- provider/model 配置，例如 provider、model、base_url、api_key。
- instructions bundle 路径。
- workspace context，例如 cwd、artifacts dir、resources prompt。
- desired skills。
- issue/chat/project context。
- tool capability guidance。

最终 adapter 收到的是一个归一化后的 `RuntimeExecutionContext`，而不是直接读取数据库。

### 3.4 Runtime 启动

adapter 根据 `agent_runtime_type` 启动不同执行路径：

- `process`：启动指定 command/args。
- `opencode_local`：启动本地 OpenCode CLI，并准备 managed home。
- `codex_local`：启动本地 Codex CLI，并准备 managed home。
- `claude_local`：启动本地 Claude CLI，并准备 managed home。

启动时关键参数：

- `cwd`：子进程工作目录。
- `env`：注入 runtime 所需环境变量。
- stdin/prompt：包含任务、上下文、工具约束、输出约束。
- stdout/stderr reader：实时读取输出并写入 run log/events。

## 4. 上下文流转

### 4.1 Issue Context

Issue context 应包含：

- issue 标题、描述、状态、优先级。
- assignee/reviewer。
- parent/child 关系。
- comments 和 review closeout 相关摘要。
- issue documents/work products 入口。
- projectId、goalId 等业务归属。

智能体执行任务时，不能只收到一句自然语言，需要收到能恢复任务现场的结构化上下文。

### 4.2 Project Context

如果 run 解析到 `projectId`，server 应注入：

- project 名称、描述、状态、目标日期。
- project workspace / primary workspace。
- project resources。
- project 相关 issue/goal 摘要。

上游 Rudder 的语义是：项目是业务对象，项目工作区是本地 runtime anchor。文件浏览、terminal、git、dev server 和插件等本地工具应优先锚定项目工作区。

### 4.3 Resource Context

资源分两层：

- Organization Resources：组织级资源目录，可被查询，但不应默认全部注入每次 run。
- Project Resources：项目挂载的组织资源。只有当 run 有 project context 时，才应加载该项目挂载的资源。

这样可以避免把整个组织资源库塞进 prompt，降低 token 成本和相关性噪音。

### 4.4 Skill Context

Skill 来源包括：

- server 内置 skills。
- organization skills。
- agent private skills。
- runtime home 中发现的外部 skills。

server 的职责：

- 管理 organization skills。
- 记录 agent desired skills。
- 在 runtime snapshot/sync/enable API 中返回可选项。
- 在执行前将启用的 skills materialize 到对应 runtime home。

数据库边界：

- `organization_skills`：组织 skill 库，记录组织可选的 skill 本体和元数据，包括 `key`、`slug`、`name`、`markdown`、`source_type`、`file_inventory` 等。
- `agent_enabled_skills`：agent 已启用 skill 选择，记录某个 agent 当前启用了哪些 skill，核心字段是 `org_id`、`agent_id`、`skill_key`。
- 私有 skill 的文件内容仍以 runtime/agent home 下的 skill package 为事实来源；`agent_enabled_skills.skill_key` 只表达“选择了什么”，不是完整 skill 内容表。

runtime 的职责：

- 在启动时读取自己 home 下的 skills。
- 按说明文件执行 skill 指令。

### 4.5 Instructions Context

说明文件包括：

- `SOUL.md`：智能体身份、行为边界和长期角色。
- `HEARTBEAT.md`：每次 heartbeat 执行的检查清单。
- `TOOLS.md`：工具使用约束。
- `MEMORY.md`：记忆和上下文摘要。

英文文件提供给 runtime 使用；中文文件只供人查看，不能改变运行时调用逻辑。

数据库和文件边界：

- instructions bundle 不是独立内容表；当前配置挂在 `agents.agent_runtime_config`。
- `agent_runtime_config` 中的关键字段包括 `instructionsBundleMode`、`instructionsRootPath`、`instructionsEntryFile`、`instructionsFilePath`。
- `instructionsRootPath` 表示说明文件 bundle 的目录路径，不是单个文件路径。
- `instructionsEntryFile` 表示该 bundle 的入口文件名，例如 `SOUL.md`。
- `instructionsFilePath` 表示当前 runtime 实际读取的入口文件完整路径，通常等于 `instructionsRootPath` + `instructionsEntryFile`。
- `SOUL.md`、`HEARTBEAT.md`、`TOOLS.md`、`MEMORY.md` 等具体 Markdown 内容落在 agent home 的 `instructions/` 目录。
- instructions 配置变更历史可进入 `agent_config_revisions`，但当前运行时读取仍以 `agents.agent_runtime_config` 和对应文件为准。

## 5. 配置流转

### 5.1 Provider / Model

server 应管理 provider/model 配置，并在执行时生成 runtime 可读配置。

OpenCode 这类本地 runtime 需要 managed home 中的配置文件，但不应长期污染用户全局配置。推荐模式：

1. UI/server 管理 provider 和 model。
2. agent 配置保存所选 `provider/model`。
3. 执行前 server 从数据库读取 provider/model/base_url/api_key。
4. server 生成 runtime managed home 配置。
5. runtime 只读取 managed home。

### 5.2 cwd

`cwd` 是 runtime 子进程启动目录，优先级应是：

1. issue/project run 解析出的 execution workspace cwd。
2. project workspace cwd。
3. organization workspace fallback。
4. 非 issue/project run 的显式 runtime config cwd。

issue/project run 一旦解析出 workspace cwd，server 应使用该 cwd 覆盖 agent runtime config 里的旧 `cwd`。否则旧 agent 配置可能把任务带回 server 启动目录或 repo 根目录，例如 `D:/coding/octopus`，导致相对路径产物泄漏到开发仓库。

server 进程启动目录不能作为 issue/project run 的默认执行 cwd。它只是 server 自己运行的位置，不代表用户希望 agent 修改或写入的项目目录。

`fallback` 不是特殊功能名，只表示首选目录不可用时的备用目录。例如优先使用 `D:/workspaces/project-a`；如果项目没有配置 cwd，则可能退回到 `.octopus/instances/<instanceId>/organizations/<orgId>/workspaces/executions/<executionWorkspaceId>/worktree/`。

没有配置项目工作区时，不能默认假设运行目录就是用户想操作的源码目录。

### 5.3 Agent Home / AGENT_HOME / Runtime Managed HOME

需要区分两类 home：

- `agent workspace home`：Octopus server 管理的 agent 长期目录，保存 `instructions/`、agent-private `skills/`、`life/` 和 `memory/`。例如 `instructionsRootPath` 通常指向这里的 `instructions/` 子目录。
- `AGENT_HOME` / `runtime managed HOME`：runtime adapter 启动本地 CLI 时准备的隔离 HOME。local runtime 会将 `HOME`、`USERPROFILE` 和 `AGENT_HOME` 指向该目录。

二者不是同一个概念：

- `agent workspace home` 跟产品 agent 绑定，偏长期配置和资料。
- `AGENT_HOME` / `runtime managed HOME` 跟 runtime 类型和执行环境绑定，偏 CLI 运行隔离和运行态配置。
- runtime 执行任务的 `cwd` 仍应来自 project workspace / execution workspace / fallback 规则，不应把任一 home 当作任务源码目录。

路径和职责对比：

| 概念 | 典型路径 | 谁管理 | 主要内容 | runtime 子进程如何使用 |
| --- | --- | --- | --- | --- |
| `agent workspace home` | `.octopus/instances/<instanceId>/organizations/<orgId>/workspaces/agents/<agentWorkspaceKey>/` | Octopus server | `instructions/`、agent-private `skills/`、`life/`、`memory/`、agent 长期资料 | 不一定直接作为子进程 `HOME`；server 会从这里读取/同步 instructions 和 agent-private skills，并给长期记忆能力提供稳定落点 |
| `instructionsRootPath` | `<agent workspace home>/instructions/` | Octopus server | `SOUL.md`、`HEARTBEAT.md`、`TOOLS.md`、`MEMORY.md` 等说明文件 | 通过 `instructionsFilePath` 选择入口文件供 runtime prompt 读取 |
| `agent private skills root` | `<agent workspace home>/skills/` | Octopus server / agent skill API | agent 私有 skill package | agent 启用后可 materialize 到 runtime skill home |
| `life` memory root | `<agent workspace home>/life/` | Octopus server / memory skill | PARA 风格长期结构化记忆 | runtime 通过说明或 skill 约定读写，适合项目、人物、组织、资源等长期实体 |
| `daily memory root` | `<agent workspace home>/memory/` | Octopus server / memory skill | 每日或会话时间线记忆 | runtime 通过说明或 skill 约定读写，适合 `YYYY-MM-DD.md` 这类流水记录 |
| `AGENT_HOME` / `runtime managed HOME` | `.octopus/runtime-homes/<runtimeType>/<orgId>/<agentId>/home/` | runtime adapter | CLI 配置、credential 链接或副本、materialized skills、runtime session 状态 | local runtime 启动时通常设置 `HOME`、`USERPROFILE`、`AGENT_HOME` 指向这里 |
| `cwd` | project workspace cwd、execution workspace cwd，或 organization workspace fallback | workspace resolver / runtime config | 任务实际操作的源码或工作目录 | 子进程启动目录；相对路径读写默认发生在这里 |

因此，一个 issue run 里可能同时出现这些路径：

```text
agent workspace home
  -> 保存长期 agent instructions / private skills / life / memory

AGENT_HOME / runtime managed HOME
  -> local runtime CLI 看到的 HOME / AGENT_HOME

cwd
  -> runtime 实际执行任务、读写项目文件的当前工作目录
```

这三者可以相互引用或同步内容，但语义不同，不能互相替代。

关系模型：

- `agent workspace home` 不按 `agent_runtime_type` 区分，通常由 `orgId + agentWorkspaceKey` 决定。
- `AGENT_HOME` / `runtime managed HOME` 按 `runtimeType + orgId + agentId` 隔离。
- 因此，一个 `agent workspace home` 可以对应多个 `AGENT_HOME` / `runtime managed HOME`，例如同一个 agent 分别使用 `codex_local`、`opencode_local`、`claude_local` 时，会有不同的 runtime managed HOME。

示例：

```text
agent:
  orgId = 16793a83-0fdd-4e35-84d7-7204f7f23663
  agentId = 65c54f76-aaaa-bbbb-cccc-123456789abc
  agentWorkspaceKey = agent-65c54f76

agent workspace home, 长期目录，不随 runtime type 改变:
  .octopus/instances/default/organizations/16793a83-0fdd-4e35-84d7-7204f7f23663/workspaces/agents/agent-65c54f76/

instructionsRootPath:
  .octopus/instances/default/organizations/16793a83-0fdd-4e35-84d7-7204f7f23663/workspaces/agents/agent-65c54f76/instructions/
  - SOUL.md
  - HEARTBEAT.md
  - TOOLS.md
  - MEMORY.md

agent private skills root:
  .octopus/instances/default/organizations/16793a83-0fdd-4e35-84d7-7204f7f23663/workspaces/agents/agent-65c54f76/skills/
  - incident-notes/SKILL.md
  - repo-maintainer/SKILL.md

life memory root:
  .octopus/instances/default/organizations/16793a83-0fdd-4e35-84d7-7204f7f23663/workspaces/agents/agent-65c54f76/life/
  - projects/
  - areas/
  - resources/
  - archives/

daily memory root:
  .octopus/instances/default/organizations/16793a83-0fdd-4e35-84d7-7204f7f23663/workspaces/agents/agent-65c54f76/memory/
  - 2026-06-05.md

AGENT_HOME / runtime managed HOME for codex_local:
  .octopus/runtime-homes/codex_local/16793a83-0fdd-4e35-84d7-7204f7f23663/65c54f76-aaaa-bbbb-cccc-123456789abc/home/
  runtime 启动后: AGENT_HOME = 这个目录

AGENT_HOME / runtime managed HOME for opencode_local:
  .octopus/runtime-homes/opencode_local/16793a83-0fdd-4e35-84d7-7204f7f23663/65c54f76-aaaa-bbbb-cccc-123456789abc/home/
  runtime 启动后: AGENT_HOME = 这个目录

AGENT_HOME / runtime managed HOME for claude_local:
  .octopus/runtime-homes/claude_local/16793a83-0fdd-4e35-84d7-7204f7f23663/65c54f76-aaaa-bbbb-cccc-123456789abc/home/
  runtime 启动后: AGENT_HOME = 这个目录

runtime task cwd, 优先来自 project workspace:
  D:/workspaces/project-a

runtime task cwd, 如果没有可用 project workspace，也可能 fallback 到 execution workspace:
  .octopus/instances/default/organizations/16793a83-0fdd-4e35-84d7-7204f7f23663/workspaces/executions/<executionWorkspaceId>/worktree/
```

在这个例子里，`instructionsRootPath` 和 agent private skills root 都挂在同一个 `agent workspace home` 下；同一个 agent 切换 `codex_local`、`opencode_local`、`claude_local` 时，长期目录不变，只会进入不同的 `runtime managed HOME`，并且该次 runtime 子进程里的 `AGENT_HOME` 指向对应的 runtime managed HOME；真正修改项目文件时使用的是 `runtime task cwd`。

`instructions/MEMORY.md` 和 `<agent workspace home>/memory/` 不同：

- `instructions/MEMORY.md` 属于 instructions bundle，用来保存会影响 prompt 的长期偏好、操作习惯和稳定经验。
- `memory/` 是文件夹，通常用于每日或会话时间线记录。
- `life/` 也是文件夹，通常用于 PARA 风格的长期实体记忆。

`runtime managed HOME` 存在的目的不只是区分 `agent_runtime_type`：

- 按 runtime 类型隔离 CLI 配置、skill 安装位置和 session 状态。
- 隔离用户真实全局 HOME，避免本地 CLI 写坏用户自己的配置目录。
- 按 agent 隔离 runtime 状态，避免不同 agent 共享 session/cache/config。
- 可控地注入 credential/config，例如复制或 symlink 必要认证文件。
- materialize 当前 agent 已启用的 skills，让 runtime 只加载这次应该可用的 skill。

更准确的说法：

```text
agent workspace home
  = agent 的长期档案库
  = instructions + agent-private skills + life + memory

AGENT_HOME / runtime managed HOME
  = runtime adapter 为某个 agent + runtime type 准备的隔离运行家目录
  = CLI config + auth/config 注入 + materialized enabled skills + session/runtime state
```

## 6. 输出流转

### 6.1 stdout/stderr

runtime 产生 stdout/stderr 时，server 应实时写入：

- run log。
- run events。
- workspace operation log。
- stdout/stderr excerpt。

不能等进程结束很久后才一次性写入，否则 UI 无法动态展示任务过程。

### 6.2 JSON Event / Result

支持 JSON event 的 runtime 应将结构化输出归一化：

- summary。
- usage。
- session id。
- tool call / tool error。
- result JSON。
- work product metadata。

即使 runtime 有中途 tool error，只要后续恢复并完成有效结果，server 不应简单用早期 tool error 覆盖最终成功状态。

### 6.3 文件产物

智能体产生文件时，推荐落点：

- durable 产物：`organization workspace/artifacts/`
- 项目源码修改：项目工作区 `cwd` 内，但需要明确登记为源码变更或 work product。

runtime 会通过 env 获得产物目录：

```text
RUDDER_ORG_ARTIFACTS_DIR
```

本地 control-plane skill 也会提供同语义变量：

```text
CONTROL_PLANE_ORG_ARTIFACTS_DIR
```

如果 agent 只是写相对路径，例如 `report.md`，文件会落到 runtime `cwd`。这适合源码修改或临时工作文件，但不适合作为稳定交付物。报告、截图、CSV、mockup、日志摘要等 durable output 应优先写入 `RUDDER_ORG_ARTIFACTS_DIR`。

server 成功 run 后应扫描受管 worktree 和组织 artifacts 中本次新增/修改文件，并登记为 issue work products。

### 6.4 Issue Documents / Work Products / Attachments

三者语义不同：

- Issue Documents：任务相关文档，例如规格、计划、报告。
- Work Products：运行产生的交付产物，例如报告、代码文件、截图、CSV。
- Attachments：评论或任务中附加的文件。

它们可以在 UI 中合并展示，但 server 数据模型应保留来源和语义，避免把 runtime stdout 当作正式交付物。

## 7. 成功判定

一次任务成功不只等于进程 exit code 为 0。

至少应满足：

- run 终态为 `succeeded`。
- wakeup request 完成。
- agent 状态回到 idle。
- issue 执行锁释放。
- stdout/stderr/log/events 可查询。
- 必要产物登记为 work products 或 documents。
- closeout/review/followup 没有留下不可解释卡点。

如果进程成功但没有产物、没有 closeout signal，server 应触发 passive followup 或留下可解释状态，而不是静默停在 `in_progress`。

## 8. 失败恢复

需要覆盖：

- process lost。
- server 重启。
- queued/running orphaned run。
- timeout。
- cancel。
- tool schema error。
- database lock 或 session 并发写错误。

恢复策略：

- orphaned running run 要能被标记失败或重试。
- retry 应关联原 run。
- cancel 应更新 run/wakeup/operation/resource service 状态。
- 错误应进入 run events/log，不只写最终 error 字段。

## 9. 数据边界

需要区分：

- DB 事实：run、issue、agent、workspace operation、work product metadata。
- 文件事实：workspace/artifacts 中的真实文件。
- runtime 临时输出：stdout/stderr/chunks。
- UI 展示状态：只能消费 server/API 事实，不能伪造任务完成或产物存在。

只有进入 DB 或组织工作区的结果，才可被 UI 稳定展示和刷新后恢复。

## 10. 最小闭环验收

建议验收链路：

1. 创建 project，并配置项目工作区。
2. 创建 agent，并配置 runtime/provider/model/skills。
3. 创建 issue，绑定 project，分配 agent。
4. 执行 issue。
5. run 进入 queued/running。
6. UI 动态看到 stdout/stderr/events。
7. 智能体在 artifacts 中写入报告。
8. server 登记 work product。
9. issue 页面可看到运行、日志和产物。
10. 组织工作区可浏览 artifacts 文件。
11. run 终态 succeeded。
12. issue 状态和 closeout/followup 可解释。
