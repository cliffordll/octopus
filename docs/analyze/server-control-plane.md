# Octopus Server 控制面与智能体协调分析报告

## 1. 目标

本文分析 server 如何控制资源、上下文、配置，并与智能体协作完成任务。重点说明 server 管什么、不管什么，如何协调 agent、issue、project、runtime、workspace，以及如何监控智能体运行态。

该报告用于回答：

- server 在智能体系统里承担什么职责。
- server 如何决定给智能体什么上下文。
- server 如何管理 provider/model、instructions、skills、resources 和 workspace。
- server 如何调度、取消、重试和恢复 run。
- server 如何监控 agent 和任务运行态。

## 2. Server 的定位

Octopus server 是控制面和执行协调层，不是单纯 API wrapper。

它负责：

- 管理组织、项目、任务、智能体、审批、资源、技能和运行记录。
- 将用户请求转成 durable work item。
- 将 work item 分配给合适 agent。
- 为 runtime 准备上下文和执行环境。
- 调用 runtime adapter。
- 记录执行过程、状态、日志和产物。
- 提供 UI/CLI 可查询的事实状态。

它不应该：

- 让 UI 伪造任务完成。
- 让 runtime 随意决定数据库状态。
- 把整个组织资源库无差别塞进每次 prompt。
- 把项目源码目录和组织产物目录混成同一个概念。
- 长期污染用户全局 runtime 配置。

## 3. 核心控制对象

### 3.1 Organization

Organization 是最高业务隔离边界。它拥有：

- agents。
- projects。
- issues。
- goals。
- resources。
- skills。
- approvals。
- organization workspace。

所有数据查询、运行和文件浏览都必须保持 org scope。

### 3.2 Project

参考上游 upstream reference，Project 的作用是围绕一个明确 deliverable 组织 issues。

Project 不是目录。它是业务对象，承载：

- 交付目标。
- 状态、负责人、目标日期。
- issues 分组。
- project resources。
- project workspaces。

Project workspace 才是本地 runtime anchor，用于 cwd、git、文件浏览、terminal、dev server 等本地工具场景。

### 3.3 Issue

Issue 是具体任务单元。它应记录：

- 任务标题/描述。
- 状态和优先级。
- assignee/reviewer。
- project/goal/parent。
- comments、documents、work products、attachments。
- execution run 关联。

Issue 是 server 和智能体协作的 durable work item。

### 3.4 Agent

Agent 是执行者。server 管理：

- agent 身份。
- role/title/reporting line。
- runtime type/config。
- enabled skills。
- instructions path。
- status。
- permissions。
- runtime state。

智能体可以提出创建/雇佣其他 agent，但 server 必须执行权限、审批和汇报关系规则。

### 3.5 Run

Run 是一次执行记录。server 通过 run 控制：

- queued/running 领取。
- 并发限制。
- cancel/timeout/retry。
- stdout/stderr/events/log。
- runtime service 和 workspace operation。
- result/work products。

没有 run 记录，就无法复盘智能体到底做了什么。

## 4. 上下文控制

### 4.1 上下文来源

server 可从以下来源组合上下文：

- organization metadata。
- agent config 和 instructions。
- selected skills。
- issue detail。
- project summary。
- goal summary。
- comments/review/document prompts。
- project resources。
- workspace context。
- chat conversation state。
- wakeup payload。

这些上下文不能由 UI 拼接后直接交给 runtime。UI 只负责选择和触发，server 负责构造可信上下文。

### 4.2 Project Resource 策略

上游语义是：

- Organization Resources 是组织级资源目录。
- Project Resources 是项目选择使用哪些组织资源。
- run 有 project context 时，只加载该项目挂载资源。
- run 没有 project context 时，不默认加载资源 prompt。

这可以避免 token 浪费和上下文污染。

### 4.3 Skills 策略

server 管理 skills 的选择和 materialization 边界：

- organization skills 是组织库。
- agent desired skills 是选择结果。
- private skills 位于 agent home。
- runtime adapter 启动前根据 desired skills 准备 managed home。

server 应返回 skill metadata、description、来源、状态，供 UI 展示和选择。

### 4.4 Instructions 策略

server 管理 instructions 初始化和路径配置：

- 创建 agent 时生成默认说明文件。
- 配置中记录 entry file 和 root path。
- runtime 执行时读取英文说明文件。
- 中文说明文件只用于人工查看。

说明文件不能散落到未管理目录，否则 agent 行为不可复现。

## 5. 配置控制

### 5.1 Runtime Provider / Model

server 应作为 provider/model 配置来源：

- provider 名称。
- protocol。
- base_url。
- api_key。
- model 列表。
- runtime type 适配关系。

执行时，server 从数据库读取配置，生成 runtime managed home 中的配置文件。agent 配置只保存所选 `provider/model`，避免 UI 和本地 CLI 全局配置不一致。

### 5.2 Agent Runtime Config

`agentRuntimeConfig` 是 adapter 需要的执行配置，例如：

- model。
- cwd。
- command/args。
- instructions path。
- extraArgs。

server 必须校验关键字段。例如 `opencode_local` 必须有 `provider/model` 格式的 model。

### 5.3 Runtime Config

`runtimeConfig` 是控制层配置，例如：

- heartbeat enabled。
- intervalSec。
- wakeOnDemand。
- maxConcurrentRuns。

它不应和 provider/model、cwd、instructions 混在一起。

### 5.4 Workspace Policy

项目 workspace CRUD 和 execution workspace policy 不是同一个东西。

- project workspace：登记项目可用的 cwd/repo。
- execution workspace policy：决定 run 如何使用 workspace，例如共享、独立、分支派生、复用范围。

server 在 preflight 阶段解析两者，形成最终 runtime workspace context。

## 6. 智能体协调

### 6.1 创建与雇佣

server 控制 agent 创建：

- board 可直接创建。
- agent 发起雇佣要经过权限判断。
- 如果组织要求审批，新 agent 进入 `pending_approval`。
- 审批通过才激活。
- agent 创建下属时，默认 `reportsTo` 指向创建者 agent。
- 智能体发起创建时，命名应按 role 序号，避免模型生成随意中文名或不稳定名称。

### 6.2 任务分配

任务执行前必须确定：

- issue 存在。
- assignee agent 可运行。
- issue 没有正在执行的 active run，或 server 明确返回已有 run/409。
- checkout/claim 防止多个 agent 同时执行同一任务。

### 6.3 Wakeup

Wakeup 是 server 唤醒 agent 的入口。来源包括：

- assignment。
- on demand。
- review。
- timer。
- recovery。
- passive followup。

不同 wake reason 会影响注入上下文和 agent 应采取的行为。

### 6.4 Review / Followup

server 不应做完整“项目经理式自动验收”，但应支持：

- reviewer wakeup。
- structured review decision。
- closeout missing detection。
- passive followup。
- blocked/request_changes/approve 等结果记录。

这样可以防止 run 成功但 issue 永久卡在不可解释状态。

## 7. 队列与并发

### 7.1 Run Queue

server 管理 run 队列：

- 创建 queued run。
- scheduler/dispatcher claim run。
- 更新 running。
- 执行完成后更新 terminal status。

claim 必须是原子行为，避免重复执行。

### 7.2 并发控制

server 应限制同一 agent 的并发 run：

- 读取 persisted running runs。
- 结合内存 active run set。
- 超过限制时保持 queued。

### 7.3 Generation Lock

Chat 同一 conversation 同时发送消息时，需要 generation lock，避免：

- 重复 runtime 调用。
- 消息顺序错乱。
- SQLite lock。
- 用户消息/assistant 回复不一致。

UI 看到“reply already being generated”时，说明 server 正在保护同一会话并发生成。

## 8. 运行态监控

### 8.1 Agent Status

agent status 表达智能体当前状态：

- idle。
- running。
- paused。
- error。
- pending_approval。
- terminated。

run 执行开始/结束时，server 应同步 agent status，但不能把 agent status 当作 run 历史。

### 8.2 Runtime State

runtime state 记录：

- last run id。
- last status。
- session id。
- token/usage 累计。
- last error。

它用于观察 agent 长期运行状态，不替代 run events。

### 8.3 Run Events / Logs

run events/log 是执行过程事实：

- queued。
- started。
- process spawned。
- stdout/stderr chunks。
- workspace preflight。
- tool error。
- cancelled/timed_out/failed/succeeded。

UI 动态展示任务过程时，应消费 events/log，而不是只看最终 run row。

### 8.4 Workspace Operations

workspace operation 记录一次执行中的 workspace 行为：

- preflight。
- adapter execution。
- runtime service lifecycle。
- operation log。
- cwd。
- exit code。

它回答“智能体在哪个目录、通过哪个操作、产生了什么过程日志”。

### 8.5 Activity Log

activity log 记录业务侧行为：

- agent.created。
- agent.hired。
- issue.created。
- issue.assigned。
- heartbeat.invoked。
- approval.created。

它用于审计和解释用户/智能体/系统对业务对象做了什么。

## 9. 状态机边界

### 9.1 Run Status

run status 是执行状态，不等同于 issue status。

run succeeded 表示一次执行成功结束，但不必然表示 issue done。issue 是否完成需要 closeout/review 或明确任务规则。

### 9.2 Issue Status

issue status 是任务业务状态：

- todo。
- in_progress。
- in_review。
- done。
- blocked。
- cancelled。

server 可以根据执行锁、checkout、review 决策更新部分状态，但不能把所有子任务完成后自动判定主任务完成，除非上游有明确 server-side 编排规则。

### 9.3 Agent Status

agent status 是执行主体状态。它应跟随当前运行态变化，但不能作为任务完成依据。

### 9.4 Approval Status

approval status 控制需要人类或 board 确认的动作，例如 hire agent 或 manual issue creation。

没有审批通过，server 不应假装任务或 agent 已创建完成。

## 10. 安全与隔离

### 10.1 组织隔离

所有 API 和文件路径必须限制在 org scope 内。

### 10.2 路径隔离

server 必须防止路径逃逸：

- organization workspace browser 只能访问组织工作区根目录内文件。
- project workspace cwd 应作为显式配置，不应从用户输入任意拼接。
- artifact 下载需要限制路径范围。

### 10.3 配置隔离

不建议长期写用户全局 runtime 配置。

推荐：

- DB/接口是 provider/model 配置来源。
- 执行前生成到 managed home。
- runtime 只读取 managed home。

### 10.4 UI 边界

UI 不能伪造：

- run 成功。
- issue done。
- work product 存在。
- 文件内容。
- approval 已通过。

UI 只能展示 server 返回的事实和触发 server API。

## 11. 结果沉淀

server 需要把执行结果沉淀到多个层次：

- run events/log：过程。
- workspace operations：执行环境和操作过程。
- organization artifacts：真实文件。
- issue work products：任务维度产物索引。
- issue documents：任务文档。
- comments/messages：沟通记录。
- activity log：审计记录。

这些不是重复，而是面向不同问题：

- “过程发生了什么？”看 run events/log。
- “在哪个目录执行？”看 workspace operations。
- “文件在哪？”看 organization workspace/artifacts。
- “这个任务交付了什么？”看 issue work products/documents。
- “谁做了什么业务动作？”看 activity log。

## 12. 最小闭环

server 控制面应支持以下闭环：

1. 创建 organization。
2. 创建 CEO agent。
3. 配置 provider/model。
4. 创建 project。
5. 绑定 project workspace。
6. 创建 issue。
7. 分配 issue 给 agent。
8. server 创建 wakeup/run。
9. runtime 执行并实时输出。
10. server 记录 events/log/operation。
11. agent 生成 artifacts。
12. server 登记 work products。
13. issue 页面可见 run 和产物。
14. organization workspace 可见真实文件。
15. review/closeout/followup 状态可解释。

如果这条链路中任何一步需要 UI 伪造或人工查数据库，说明 server 控制面还没有闭环。
