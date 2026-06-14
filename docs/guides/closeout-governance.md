# Closeout 执行逻辑说明

这篇文档用通俗方式说明：一个智能体任务运行结束后，Octopus 怎么判断它是不是真的把 issue 收尾了，什么时候会自动追问，什么时候应该交给用户处理。

## 一句话结论

智能体说“我完成了”还不够。系统需要看到一个明确动作：

- 留下 issue 评论
- 把 issue 改成完成、阻塞或待评审
- 记录评审结论

如果没有这些动作，系统就认为这个任务“运行结束了，但 issue 还没收尾”。

## 为什么需要 Closeout

一次 run 成功，只代表智能体进程正常结束，不代表任务阶段已经处理完。

例如：

- 智能体在日志里说“已完成”，但 issue 仍是 `todo`
- 智能体做了代码修改，但没有评论说明结果
- 智能体跑完了，但没有把任务改成 `done`
- 有 reviewer 的任务只说“完成了”，但没有进入评审或给出评审结论

这些都会让用户不知道下一步该做什么。因此 Octopus 要求 run 结束时留下一个可追踪的收尾信号。

## 系统如何判断已经收尾

任务运行结束后，系统会看当前 run 是否对这个 issue 做过明确操作。

判断时主要看三类数据：

| 类型 | 字段或事件 | 含义 |
| --- | --- | --- |
| 当前运行 | `heartbeat_runs.id` | 当前结束的 run id |
| 当前运行状态 | `heartbeat_runs.status = succeeded` | 只有成功结束的 run 才进入普通 closeout 判断 |
| 当前 issue | `issues.id` | run 正在处理的 issue |
| 当前 issue 状态 | `issues.status` | 如果状态已经离开 `todo` / `in_progress`，通常说明 issue 已进入下一阶段 |
| 当前 issue 执行锁 | `issues.execution_run_id` | 表示这个 issue 当前由哪个 run 占用执行 |
| 操作事件 | `activity_log.action` | 记录 run 对 issue 做过什么动作 |
| 事件归属 | `activity_log.run_id` | 必须等于当前 `heartbeat_runs.id`，才算当前 run 留下的信号 |
| 事件对象 | `activity_log.entity_type = issue`，`activity_log.entity_id = issues.id` | 确认这个事件是写给当前 issue 的 |
| 事件详情 | `activity_log.details.status` | 对 `issue.updated` 来说，用来判断改到了哪个任务阶段 |

没有 reviewer 的 issue，以下任一情况都算收尾：

- 当前 run 给 issue 发了评论：`activity_log.action = issue.comment_added`
- 当前 run 把 issue 改成 `done`：`activity_log.action = issue.updated` 且 `activity_log.details.status = done`
- 当前 run 把 issue 改成 `blocked`：`activity_log.action = issue.updated` 且 `activity_log.details.status = blocked`
- 当前 run 把 issue 改成 `in_review`：`activity_log.action = issue.updated` 且 `activity_log.details.status = in_review`

有 reviewer 的 issue，要求更严格：

- 当前 run 把 issue 交到 `in_review`：`activity_log.action = issue.updated` 且 `activity_log.details.status = in_review`
- 当前 run 把 issue 改成 `done` 或 `blocked`：`activity_log.action = issue.updated` 且 `activity_log.details.status` 是 `done` 或 `blocked`
- reviewer run 记录了明确评审结论：`activity_log.action = issue.review_decision_recorded`

有 reviewer 时，普通评论不能替代评审流程。这样可以避免任务绕过评审。

## Closeout 命令如何生效

智能体不能只在最后回复里写“完成了”。它必须调用控制面命令，让 server 写入可追踪的数据。

完整链路是：

1. server 给智能体的运行提示里写明 closeout 要求
2. 本地 runtime 启动时，把 `control-plane` 命令放进智能体的 `PATH`
3. 智能体执行 `control-plane issue done`、`control-plane issue block`、`control-plane issue comment` 或 `control-plane issue review`
4. CLI 从环境变量读取当前上下文
5. CLI 请求 server 的 issue 接口
6. server 写入 issue 状态、评论或评审结论
7. server 同时写入 `activity_log`
8. run 结束时，heartbeat finalize 读取这些事件，判断 closeout 是否完成

关键环境变量：

| 环境变量 | 用途 |
| --- | --- |
| `OCTOPUS_AGENT_ID` | 当前执行智能体 |
| `OCTOPUS_ORG_ID` | 当前组织 |
| `OCTOPUS_RUN_ID` | 当前 heartbeat run |
| `OCTOPUS_API_URL` | control-plane server 地址 |
| `OCTOPUS_API_KEY` | 需要认证时使用的 key |

CLI 会把这些信息转成请求 header，尤其是当前 run id。这样 server 写入 `activity_log.run_id` 时，才能把 closeout 信号归到正确的 run 上。

常用命令：

```bash
control-plane issue comment "11C5D5-17" --body "已完成主要修改，等待用户确认。" --json
control-plane issue done "11C5D5-17" --comment "已完成并验证。" --json
control-plane issue block "11C5D5-17" --comment "缺少外部凭证，暂时阻塞。" --json
control-plane issue review "11C5D5-17" --decision approve --comment "评审通过。" --json
```

这些命令里的 issue 可以是数据库 UUID，也可以是用户看到的编号，例如 `11C5D5-17`。系统会解析成真实的 `issues.id` 后再写入数据。

命令成功后，通常会产生这些事件：

| 命令 | 主要写入 | closeout 判断使用的事件 |
| --- | --- | --- |
| `issue comment` | `issue_comments` | `activity_log.action = issue.comment_added` |
| `issue done` | `issues.status = done`，可附带评论 | `activity_log.action = issue.updated`，`details.status = done` |
| `issue block` | `issues.status = blocked`，可附带评论 | `activity_log.action = issue.updated`，`details.status = blocked` |
| `issue review --decision approve` | `issues.status = done` | `activity_log.action = issue.review_decision_recorded` |
| `issue review --decision request_changes` | `issues.status = in_progress` | `activity_log.action = issue.review_decision_recorded` |
| `issue review --decision blocked` | `issues.status = blocked` | `activity_log.action = issue.review_decision_recorded` |
| `issue review --decision needs_followup` | 保持评审跟进 | `activity_log.action = issue.review_decision_recorded` |

如果命令没有执行成功，或者执行成功但没有带上当前 `OCTOPUS_RUN_ID`，heartbeat finalize 就看不到属于当前 run 的 closeout 信号。

## 用户人工介入后怎么处理

人工介入不等于“这个 run 已经收尾”，但它代表 issue 已经回到用户手里。

判断人工介入时主要看 issue 之后有没有用户动作：

| 类型 | 字段或事件 | 含义 |
| --- | --- | --- |
| 用户评论 | `activity_log.action = issue.comment_added`，`activity_log.actor_type = user` | 用户已经在 issue 上留下新信息 |
| 用户改阶段 | `activity_log.action = issue.updated`，`activity_log.actor_type = user` | 用户已经手动调整 issue |
| 阶段结果 | `activity_log.details.status` | 如果是 `done` / `blocked` / `in_review`，说明用户已经给出明确下一阶段 |
| 当前 issue 状态 | `issues.status` | 用来确认 issue 是否仍需要自动跟进 |
| 当前执行锁 | `issues.execution_run_id` | 如果还指向 follow-up run，需要避免把取消 follow-up 误显示为 issue cancelled |

因此建议规则是：

- 用户评论了 issue：停止后续自动 follow-up
- 用户修改了任务阶段：停止后续自动 follow-up
- 用户取消了 passive follow-up：停止这条自动跟进，不把 issue 本身改成 cancelled

也就是说，人工介入是“不要再自动追问”的信号，不是“补认智能体已完成”的证据。

## Passive Follow-up 是什么

如果 run 成功结束，但系统没有看到收尾信号，Octopus 不会立刻再启动智能体。

默认逻辑是：

1. 先提示用户：这个 issue 可能需要收尾
2. 等待一段时间，默认 1800 秒
3. 如果期间用户没有处理，再创建一次 `issue_passive_followup`
4. 这次 follow-up 的任务不是重新做需求，而是要求智能体检查前一个 run 的结果并补上收尾动作

等待时间可以通过配置调整：

```powershell
$env:OCTOPUS_ISSUE_PASSIVE_FOLLOWUP_DELAY_SECONDS = "600"
```

也可以在 UI 上手动触发“立即收尾跟进”，跳过等待时间。

自动等待时，系统先写一条待触发请求，而不是立刻创建正在运行的任务：

| 类型 | 字段或事件 | 含义 |
| --- | --- | --- |
| 待触发请求 | `agent_wakeup_requests.reason = issue_passive_followup` | 说明这是一次收尾跟进 |
| 请求状态 | `agent_wakeup_requests.status = scheduled` | 还在等待，不应该显示成正在执行 |
| 触发时间 | `agent_wakeup_requests.requested_at` | 到这个时间后才会物化成 run |
| 触发来源 | `agent_wakeup_requests.source = automation` | 系统自动安排 |
| 触发细节 | `agent_wakeup_requests.trigger_detail = system` | 系统触发，不是用户手动 |
| 幂等键 | `agent_wakeup_requests.idempotency_key` | 防止同一个 run 重复安排多条 follow-up |
| 请求内容 | `agent_wakeup_requests.payload.issueId` | 要收尾的 issue |
| 请求内容 | `agent_wakeup_requests.payload.originRunId` | 最早缺少收尾的 run |
| 请求内容 | `agent_wakeup_requests.payload.previousRunId` | 本次 follow-up 针对的上一个 run |
| 请求内容 | `agent_wakeup_requests.payload.attempt` | 第几次 follow-up |

手动“立即收尾跟进”会复用同一套数据，只是把 `requested_at` 改到当前时间，并把 `trigger_detail` 标记为 `issue_passive_followup`，然后立即物化成 run。

## Follow-up 应该做什么

`issue_passive_followup` 不是新的普通任务。它只应该处理收尾问题。

物化成 run 后，可以通过这些字段识别它是收尾跟进：

| 类型 | 字段或事件 | 含义 |
| --- | --- | --- |
| run 类型 | `heartbeat_runs.run_purpose = closeout_followup` | 这是收尾跟进 run，不是普通任务执行 |
| run 来源 | `heartbeat_runs.invocation_source = automation` | 由自动化触发 |
| run 触发原因 | `heartbeat_runs.trigger_detail` | 通常是 `system`，手动立即触发时可体现 `issue_passive_followup` |
| 关联请求 | `heartbeat_runs.wakeup_request_id` | 指向对应的 `agent_wakeup_requests.id` |
| 上下文 | `heartbeat_runs.context_snapshot.issueId` | 当前要处理的 issue |
| 上下文 | `heartbeat_runs.context_snapshot.wakeReason = issue_passive_followup` | 明确告诉智能体这是收尾任务 |
| 上下文 | `heartbeat_runs.context_snapshot.passiveFollowup.originRunId` | 最早缺少收尾的 run |
| 上下文 | `heartbeat_runs.context_snapshot.passiveFollowup.previousRunId` | 本次要检查的上一个 run |
| 上下文 | `heartbeat_runs.context_snapshot.passiveFollowup.attempt` | 当前第几次收尾跟进 |
| 上下文 | `heartbeat_runs.context_snapshot.passiveFollowup.maxAttempts` | 最多允许几次跟进 |

智能体应该先检查当前 issue 和前一个 run 的结果，然后只做一个明确动作：

- 如果确实完成了，评论说明结果，或把 issue 标记为 `done`
- 如果还需要评审，把 issue 改成 `in_review`
- 如果无法继续，把 issue 标记为 `blocked` 并说明原因
- 如果需要用户处理，留下清楚的说明

## 为什么会反复 Follow-up

常见原因有四类：

1. 智能体只在日志里说完成了，没有操作 issue
2. 智能体发了评论，但评论没有关联到当前 run
3. 有 reviewer 的 issue 只发了普通评论，没有进入评审或记录评审结论
4. follow-up run 没识别出自己是收尾任务，又按普通任务跑完了
5. runtime 里没有可执行的 `control-plane` 命令
6. CLI 没有实现 skill 要求的 `issue done` / `issue block` / `issue review --comment`
7. CLI 没有把 `OCTOPUS_RUN_ID` 传给 server，导致事件没有归属到当前 run
8. 智能体使用了 `11C5D5-17` 这样的 issue 编号，但 server 只按 UUID 查找 issue

这些情况下，系统仍然看不到明确收尾信号，就可能继续安排 follow-up。

因此，排查 closeout 时不要只看智能体最终回复，要按这条链路查：

1. run 日志里是否真的执行了 `control-plane ...`
2. `control-plane` 是否在 runtime 的 `PATH` 上
3. 命令是否返回成功 JSON
4. 请求是否带上当前 `OCTOPUS_AGENT_ID`、`OCTOPUS_ORG_ID`、`OCTOPUS_RUN_ID`
5. server 是否写入了当前 issue 的 `activity_log`
6. `activity_log.run_id` 是否等于当前 `heartbeat_runs.id`
7. issue 编号是否被解析到了正确的 `issues.id`

反复触发时重点看这些数据：

| 类型 | 字段或事件 | 含义 |
| --- | --- | --- |
| run 是否成功 | `heartbeat_runs.status = succeeded` | 只有成功结束但没收尾，才会进入 passive follow-up |
| run 是否普通任务 | `heartbeat_runs.run_purpose = task_execution` | 普通任务缺收尾会排 follow-up |
| run 是否收尾跟进 | `heartbeat_runs.run_purpose = closeout_followup` | follow-up 自己也必须留下收尾信号 |
| issue 是否仍打开 | `issues.status in (todo, in_progress)` | 仍打开才继续自动跟进 |
| assignee 是否一致 | `issues.assignee_agent_id = heartbeat_runs.agent_id` | 只让当前 assignee 补自己的收尾 |
| 是否已有请求 | `agent_wakeup_requests.idempotency_key` | 防止同一 run 重复创建 follow-up |
| 尝试次数 | `context_snapshot.passiveFollowup.attempt` 或 `agent_wakeup_requests.payload.attempt` | 超过上限后不再继续自动追问 |
| 缺少评论信号 | 没有当前 `run_id` 的 `issue.comment_added` | 普通无 reviewer issue 会继续缺 closeout |
| 缺少状态信号 | 没有当前 `run_id` 的 `issue.updated` 到 `done` / `blocked` / `in_review` | issue 没进入下一阶段 |
| 缺少评审信号 | 没有当前 `run_id` 的 `issue.review_decision_recorded` | reviewer 场景没有评审结论 |

## 什么时候应该提示用户

当系统已经多次尝试 follow-up，或者用户取消了 follow-up，UI 应该提示：

```text
任务运行已结束，但 issue 还没有明确收尾。
请检查结果后，将任务阶段改为 done、blocked 或 in_review，或留下说明评论。
```

这个提示应该出现在 issue 页面，让用户知道现在需要人工判断任务阶段，而不是继续等待智能体。

提示可以由这些信号触发：

| 类型 | 字段或事件 | 含义 |
| --- | --- | --- |
| follow-up 耗尽且无 reviewer | `activity_log.action = issue.closure_needs_operator_review` | 自动收尾已停止，需要用户判断 |
| follow-up 耗尽且有 reviewer | `activity_log.action = issue.convergence_review_requested` | 自动收尾没有收敛，需要 reviewer 或用户判断 |
| reviewer closeout 耗尽 | `activity_log.action = issue.review_closure_needs_operator_review` | reviewer 运行也没有给出明确结论 |
| 用户取消 follow-up run | `heartbeat_runs.status = cancelled`，且 `heartbeat_runs.run_purpose = closeout_followup` | 只代表取消了跟进 run，不代表 issue cancelled |
| issue 仍未结束 | `issues.status in (todo, in_progress)` | 仍需要用户决定下一阶段 |

## 不应该当作收尾的情况

以下情况不能当作当前 run 已经收尾：

- run 日志里出现“完成了”
- 历史上有人评论过 issue，但不是当前 run 写的
- 有 reviewer 的任务只留下普通评论
- 用户取消了 passive follow-up run

取消 follow-up 只表示停止这次自动跟进，不表示 issue 被取消，也不表示任务完成。
