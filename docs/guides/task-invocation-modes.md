# 任务调用方式与对话任务创建指南

本文整理 Octopus 当前几类“任务调用方式”的执行情况，并说明它们和 issue、agent inbox、heartbeat run、chat invocation 的关系。

相关底层机制见：

```text
docs/guides/task-queue.md
docs/guides/task-execution-lifecycle.md
docs/guides/heartbeat-scheduler.md
```

本文关注入口语义：用户从哪里触发、系统会创建什么记录、是否会进入 agent runtime 执行，以及应该在哪里观察结果。

## 核心结论

Octopus 里需要区分三件事：

| 概念 | 含义 |
| --- | --- |
| `issue` | 产品任务或工作项，保存标题、状态、负责人、reviewer、评论和执行锁 |
| `agent_wakeup_request` | 唤醒某个 agent 的请求，记录来源、原因、payload 和延期状态 |
| `heartbeat_run` | 一次真实 agent runtime 执行记录，可能是 queued、running、succeeded、failed、cancelled 或 timed_out |

不是所有用户动作都会直接产生 `heartbeat_run`。

最重要的边界：

```text
chat assistant invocation 不等同于 heartbeat run
```

对话可以生成 issue proposal，也可以把 proposal 转成 issue；但 chat 中直接调用 assistant/runtime 回复用户时，不应为了可见性伪造成 `heartbeat_run`。

## 当前入口总览

| 入口 | 会创建/更新 issue | 会创建 wakeup request | 会创建 heartbeat run | 主要观察位置 |
| --- | --- | --- | --- | --- |
| Issue create/update | 是 | 视状态、负责人和 reviewer 而定 | 视 wakeup 是否可执行 | issue 详情、agent inbox、runs |
| Issue checkout | 是，写入 checkout 语义 | 通常会唤醒负责人 | 是，除非被延期 | issue 详情、runs |
| Issue execute | 是，写入执行语义/锁 | 是 | 是，除非被延期 | issue 详情、runs |
| Manual wakeup | 否 | 是 | 是，除非 paused 或被策略阻止 | agent runs |
| Timer heartbeat | 否 | 是 | 是，按 scheduler 到期触发 | agent runs、scheduler 日志 |
| Assignment / review | 是，状态或负责人变化 | 是 | 是，除非被延期 | agent inbox、issue 详情、runs |
| Comment / mention | 是，新增 comment | 是 | 是，普通评论给 assignee，mention 给被提及 agent | agent inbox、issue 评论、runs |
| Retry / recovery | 否或更新 run 状态 | 可能创建恢复 wakeup | 是或恢复已有 run | heartbeat runs、events |
| Chat reply | 是，保存 chat message | 否 | 否 | chat transcript/message |
| Chat to issue | 是，创建 issue 并关联 chat | 取决于新 issue assignee/reviewer/status | 取决于 issue 创建后的 wakeup | chat、issue 详情、agent inbox |

## Issue：用户创建、更新、checkout、execute 一个任务

Issue 是业务任务本体，不是执行队列本身。

用户创建或更新 issue 时，server 会先保存 `issues` 记录，然后根据任务状态和关联 agent 决定是否唤醒 agent。

常见情况：

| 动作 | 主要影响 |
| --- | --- |
| 创建 issue 且指定 `assigneeAgentId` | 可能产生 `issue_assigned` wakeup |
| backlog 变成 todo/in_progress | 可能产生可执行任务唤醒 |
| 指定 reviewer 或进入 `in_review` | 可能产生 review wakeup |
| checkout | 建立签出语义，并让负责人知道该任务已进入执行准备状态 |
| execute | 明确要求 agent 执行该 issue，创建带 `issueId` context 的 run |

执行相关 run 会在 `heartbeat_runs.context_snapshot.issueId` 中携带 issue id。UI 可以通过 issue 详情、run 列表和 run events 追踪执行过程。

注意：

```text
run succeeded != issue done
```

一次 runtime 成功结束只表示进程执行成功。Issue 是否完成，仍需要明确 close-out，例如评论、标记 done、进入 review 或记录 review decision。

## Agent Inbox：智能体如何看到待办

Agent inbox 是轻量待办视图，不是新的执行队列。

它聚合两类来源：

| 来源 | 说明 |
| --- | --- |
| issue 当前责任 | 该 agent 是 assignee 或 reviewer，并且 issue 仍在可执行或待评审状态 |
| comment wakeup | 该 agent 收到普通评论唤醒或 `@agent` 提及唤醒 |

关系标签：

| relationship | 含义 |
| --- | --- |
| `assignee` | 该 agent 是任务负责人，需要执行或继续处理 |
| `reviewer` | 该 agent 是 reviewer，需要评审或处理 blocked review |
| `mentioned` | 评论中明确提及该 agent，需要查看上下文 |

UI 中的“待办收件箱”展示 issue 标题、状态、优先级、更新时间，以及评论唤醒的摘要。CLI 可通过 agent inbox 查询同一信息。

## Comment / Mention：评论如何唤醒智能体

用户在 issue 下评论时，当前规则是：

| 场景 | 行为 |
| --- | --- |
| 普通评论，评论者不是 assignee 本人 | 唤醒 assignee，reason 为 `issue_comment_added` |
| 评论中出现 `@agent-id`、`@agent-url-key` 或 `@AgentName` | 额外唤醒被提及 agent，reason 为 `issue_comment_mentioned` |
| assignee 自己评论 | 不给自己创建普通评论唤醒 |
| mention 到评论者自己 | 不给自己创建 mention 唤醒 |
| mention 到 assignee 且普通评论唤醒已创建 | 避免重复，保留普通 assignee 评论唤醒 |

评论唤醒的 run context 会携带：

```text
issueId
wakeReason
commentId
commentBody
issue summary
```

因此 runtime 可以知道自己为什么被叫醒，也可以通过环境或上下文读取对应任务和评论。

`issue_comment_mentioned` 有一个特殊点：即使 issue 当前有普通执行锁，也允许 mention wakeup 通过。原因是 mention 更像“请看一下这条评论”，不是普通 assignment 的并行执行。

## Manual Wakeup：手动唤醒 agent

手动唤醒是用户直接要求 agent 跑一次。

典型入口：

```text
POST /api/agents/{id}/wakeup
```

它会创建 `agent_wakeup_request`，通常也会创建 `heartbeat_run(status = queued)`，随后 dispatcher 将其 claim 成 running。

如果 agent 处于 paused：

```text
agent_wakeup_requests.status = deferred_agent_paused
```

这时不会立即执行。恢复 agent 后，延期 wakeup 才会重新推进。

Manual wakeup 不一定关联 issue。只有 payload 或 context 中包含 issue 信息时，它才会成为 issue execution 语义的一部分。

## Timer Heartbeat：scheduler 周期性检查

Timer heartbeat 是后台 scheduler 按 agent 的 heartbeat policy 定期触发。

关键配置在 agent runtime config 中：

```text
runtimeConfig.heartbeat.enabled
runtimeConfig.heartbeat.intervalSec
runtimeConfig.heartbeat.maxConcurrentRuns
```

timer 的语义不是“用户新建了一个任务”，而是“到点检查 agent 是否需要继续工作”。

当前实现会避免重复创建同一 agent 的 active timer run。如果该 agent 已经有 active timer run，scheduler 不应继续堆积新的 timer runs。

Timer run 的观察位置：

| 位置 | 可见内容 |
| --- | --- |
| agent runs | run source 为 timer |
| scheduler 日志 | 到期扫描、跳过、创建 queued run |
| heartbeat run events | runtime 执行事件 |

## Review / Assignment：任务进入可执行或待 review 状态后触发唤醒

Assignment 和 review 是 issue 状态流转带来的业务唤醒。

常见 reason：

| reason | 场景 |
| --- | --- |
| `issue_assigned` | issue 创建或分配给 agent |
| `issue_status_changed` | issue 从不可执行状态进入可执行状态 |
| `issue_checked_out` | issue 被 checkout，需要负责人继续 |
| `issue_execute` | 用户主动执行 issue |
| `issue_changes_requested` | reviewer 要求修改 |
| `issue_review_requested` | issue 进入待 review |
| `issue_review_closeout_missing` | reviewer run 结束但缺少 review decision |

普通 assignment/review run 会受 issue 执行锁约束。如果同一 issue 已有 `checkout_run_id` 或 `execution_run_id`，后来的普通 issue wakeup 可能先延期：

```text
agent_wakeup_requests.status = deferred_issue_execution
```

当前执行释放后，server 再 promote 最早的 deferred wakeup。

## Retry / Recovery：失败、取消、server 重启后的恢复 run

Retry/recovery 不是用户直接创建的新任务，而是系统为了恢复一致性而推进 run。

常见场景：

| 场景 | 行为 |
| --- | --- |
| runtime 失败 | run 进入 failed，并记录错误、stdout/stderr 摘要和 events |
| 用户取消 | run 进入 cancelled，并释放相关执行锁 |
| server 重启时发现遗留 running process | 根据进程状态恢复、重试或标记失败 |
| queued run 长时间未执行 | scheduler 后续周期继续尝试 claim |
| paused agent 恢复 | deferred wakeup 被重放 |

观察位置：

```text
heartbeat_runs
heartbeat_run_events
agent_wakeup_requests
issue execution lock 字段
```

如果恢复 run 仍然关联 issue，需要同时检查 issue 是否还有 execution/check-out 锁残留。

## Chat：对话、任务 proposal 和 issue 创建

Chat 有两条路径，必须分开理解。

### 1. Chat assistant invocation

用户在 chat 中发消息，系统会保存用户消息，然后调用选定 agent/runtime 生成 assistant 回复。

这条路径保存的是：

```text
chat_conversations
chat_messages
chat transcript
```

它不保存为：

```text
heartbeat_runs
```

原因是 chat assistant invocation 是对话调用，不是 heartbeat 队列里的 agent run。文档和实现都应保持这个边界，避免用假的 run 混淆执行来源。

### 2. Chat 转成 issue

Chat 可以生成 `issue_proposal`，也可以通过转换接口创建真实 issue。

典型入口：

```text
POST /api/chats/{chatId}/convert-to-issue
```

转换成功后会：

| 动作 | 说明 |
| --- | --- |
| 创建 issue | 使用 proposal 中的 title、description、priority、assignee 等字段 |
| 关联 chat | conversation 写入 primary issue 或上下文关系 |
| 写 system message | 在 chat 中留下“已创建 issue”的系统消息 |
| 写 activity | 记录 `chat.issue_converted` |
| 触发后续 issue wakeup | 如果新 issue 有 assignee/reviewer 且状态需要执行或评审 |

也就是说：

```text
chat 本身不等于 heartbeat run
chat 转成 issue 后，issue 流程可能再触发 heartbeat run
```

## 对话任务创建逻辑

当前对话任务创建可理解为四步：

```text
用户在 chat 描述需求
  ↓
assistant 生成 issue proposal 或用户手动提供 proposal
  ↓
approval / manual conversion / auto-create 规则决定是否创建 issue
  ↓
issue 创建后按普通 issue assignment/review 规则触发 wakeup/run
```

关键点：

- 如果只是 chat 回复，结果留在 chat message/transcript 中。
- 如果需要进入任务体系，必须变成 issue。
- issue 创建后才进入 issue board、agent inbox 和 heartbeat 执行体系。
- 转换出来的 issue 是否立即执行，取决于 status、assignee/reviewer 和当前执行锁。

## 如何判断某个动作到底跑没跑

排查时按下面顺序看：

1. 是否有 issue？
   - 看 `issues`，确认 status、assignee、reviewer、checkout/execution 字段。

2. 是否有 wakeup？
   - 看 `agent_wakeup_requests`，确认 agent、reason、payload、status。

3. 是否有 run？
   - 看 `heartbeat_runs`，确认 source、status、wakeup_request_id、context_snapshot。

4. run 是否真的执行？
   - 看 `heartbeat_run_events`、stdout/stderr 摘要、runtime exit code。

5. 如果来自 chat，先判断是哪条路径：
   - 普通 chat assistant reply：看 `chat_messages` 和 transcript。
   - chat 转 issue：看 issue 是否创建，再按 issue/wakeup/run 路径排查。

## 常见误解

### 创建 issue 就一定会立刻执行吗？

不一定。

只有 issue 满足可执行状态、有关联 agent，并且没有被 paused、执行锁、预算或策略阻止时，才会推进到可执行 run。

### run succeeded 就代表任务完成吗？

不代表。

`run succeeded` 只说明 runtime 进程成功结束。任务完成必须由 issue 状态或 close-out signal 表达。

### 为什么会有 timer runs？

因为 agent 启用了 heartbeat scheduler。timer run 是周期性检查，不是用户新建的任务。

### 为什么会积压 queued/running runs？

常见原因：

- agent 并发上限已满。
- runtime 执行慢或卡住。
- server 重启前留下 running 状态，需要 recovery。
- paused agent 的 wakeup 被延期。
- 旧版本重复创建 timer run，或幂等策略不足。

### 我评论后智能体能看到吗？

普通评论会唤醒 assignee，并进入其 inbox。`@agent` 提及会唤醒被提及 agent，并在其 inbox 中显示为“提及”。

### inbox 是队列吗？

不是。

inbox 是面向 agent 的待办视图，聚合 issue 责任和评论唤醒。真正的执行队列仍然是 `heartbeat_runs(status = queued)` 和 scheduler/dispatcher。

## 建议的使用方式

| 需求 | 推荐入口 |
| --- | --- |
| 创建一个可追踪任务 | 创建 issue |
| 让负责人开始处理 | 指派 assignee 或点击 execute |
| 要求 reviewer 评审 | 设置 reviewer 并进入 `in_review` |
| 临时叫醒 agent | manual wakeup |
| 让 agent 周期性自检 | timer heartbeat |
| 从对话沉淀任务 | chat issue proposal -> convert to issue |
| 在任务里补充要求 | issue comment，必要时 `@agent` |
| 查看 agent 该做什么 | agent inbox |
| 查看真实执行 | heartbeat runs 和 run events |
