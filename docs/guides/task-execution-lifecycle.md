# Task Execution Lifecycle Guide

本文说明 Octopus 当前任务执行逻辑，重点解释 issue/task 被分配、执行、释放执行锁、以及为什么成功 run 后可能出现第二次执行。

相关队列底层机制见：

```text
docs/guides/task-queue.md
```

本文关注业务生命周期，而不是通用 queued run 调度细节。

## 核心结论

Octopus 的任务执行不是“run 成功就等于 issue 完成”。

核心语义来自上游 upstream reference：

```text
run succeeded 表示一次执行进程成功结束
issue done 必须由明确 close-out 动作产生
```

如果一个 issue run 成功结束，但 issue 仍是 `todo` 或 `in_progress`，并且该 run 没有留下 close-out signal，server 会触发同 agent 的 passive follow-up。

这就是用户看到“任务好像执行了两次”的主要原因。

第二次 run 的语义不是重新分配任务，而是 close-out governance：

```text
issue_passive_followup
```

它要求 agent 检查第一次 run 的结果，并补上进展评论、完成、阻塞或明确交接。

## 关键对象

| 对象 | 作用 |
| --- | --- |
| `issues` | 业务任务本体，保存 assignee、reviewer、status 和执行锁 |
| `agent_wakeup_requests` | 记录一次唤醒请求，包括分配、评论、review、follow-up 等原因 |
| `heartbeat_runs` | 记录一次实际 runtime 执行 |
| `issue_comments` | 任务评论，可作为 close-out signal |
| `activity_log` | 记录 issue close-out、review decision、follow-up 等可审计事件 |

关键字段：

| 字段 | 含义 |
| --- | --- |
| `issues.checkout_run_id` | 当前签出该 issue 的 run |
| `issues.execution_run_id` | 当前持有 issue 执行锁的 run |
| `issues.execution_agent_name_key` | 当前执行 agent 的 name key |
| `issues.execution_locked_at` | 执行锁创建时间 |
| `heartbeat_runs.context_snapshot.issueId` | run 和 issue 的稳定关联 |
| `heartbeat_runs.context_snapshot.wakeReason` | run 被唤醒的业务原因 |

## 基本执行流

一次 issue 执行通常经过：

```text
issue assigned / execute clicked
  ↓
agent wakeup request
  ↓
heartbeat_run(status = queued)
  ↓
issue execution lock
  ↓
heartbeat_run(status = running)
  ↓
runtime adapter execute
  ↓
succeeded / failed / timed_out / cancelled
  ↓
release issue execution lock
  ↓
close-out governance
```

其中队列领取只保证 run 执行权，不代表 issue 已完成。

## 入队来源

常见 issue 相关 wake reason：

| reason | 场景 |
| --- | --- |
| `issue_assigned` | 创建或分配给 agent 的任务 |
| `issue_checked_out` | checkout 后需要唤醒负责人 |
| `issue_execute` | UI 或 API 主动启动任务执行 |
| `issue_status_changed` | backlog 进入可执行状态 |
| `issue_changes_requested` | reviewer 请求修改 |
| `issue_comment_added` | 负责人任务收到新评论 |
| `issue_comment_mentioned` | 评论中 mention agent |
| `issue_passive_followup` | 成功 run 缺少 close-out，需要补收尾 |
| `issue_review_closeout_missing` | reviewer run 缺少结构化 review decision |

## 执行锁

issue 执行时会写入：

```text
issues.execution_run_id = heartbeat_runs.id
issues.checkout_run_id = heartbeat_runs.id
```

执行锁的作用：

- 防止同一 issue 被多个普通 assignment run 并行处理。
- 让 UI 能知道当前活跃 run。
- 让 run 终态后能安全释放或 promote 后续 deferred wakeup。

当前 Octopus 实现中，assignment run 创建后会尝试 claim issue execution：

```text
server/services/heartbeat.py
  _claim_issue_execution_for_assignment_run(...)
```

如果 issue 已经有 `execution_run_id` 或 `checkout_run_id`，普通 issue wakeup 会先延期：

```text
agent_wakeup_requests.status = deferred_issue_execution
```

当前执行锁释放后，server 再 promote 最早的 deferred issue wakeup。

## Run 成功不自动 Done

上游和 Octopus 都不把成功 run 自动转换成：

```text
issues.status = done
```

原因：

- runtime 进程成功只说明 agent 进程正常结束。
- agent 可能只完成了一部分工作。
- agent 可能需要 reviewer。
- agent 可能生成了产物但还未更新任务状态。
- 自动 done 会掩盖未收尾、未交付、未评审的问题。

因此 issue 完成必须由明确动作产生，例如：

- 添加进展或交接评论。
- 将 issue 标记为 `done`。
- 将 issue 标记为 `blocked` 并说明原因。
- 将 issue 移入 `in_review`。
- reviewer 记录结构化 review decision。

## Close-Out Signal

当前 Octopus 识别的 close-out signal 主要来自 `activity_log`：

```text
issue.comment_added
issue.review_decision_recorded
```

也就是说，如果 agent 的 run 成功结束，但没有产生这些动作，并且 issue 仍处于 `todo` 或 `in_progress`，server 会认为任务缺少 close-out。

对应代码：

```text
server/services/heartbeat.py
  _run_has_issue_closeout_signal(...)
```

## Passive Follow-Up

当成功 issue run 缺少 close-out 时，server 会创建后续 wakeup：

```text
reason = issue_passive_followup
```

当前 Octopus 会构造 context：

```text
contextSnapshot.wakeReason = issue_passive_followup
contextSnapshot.wakeSource = passive_issue_followup
contextSnapshot.passiveFollowup.originRunId = <first-run-id>
contextSnapshot.passiveFollowup.previousRunId = <first-run-id>
contextSnapshot.passiveFollowup.reason = missing_closure
```

这个 follow-up 的正确语义：

```text
不是新任务
不是失败重试
不是重新从头执行
```

agent 应该先检查上一个 run 已完成的内容和副作用，然后执行一个 close-out 动作。

## 为什么看起来执行了两次

典型情况：

```text
1. 用户点击“启动执行”
2. server 创建 assignment run
3. run 成功结束
4. issue 仍然是 todo / in_progress
5. run 没有写 issue comment，也没有 review decision
6. server queue issue_passive_followup
7. scheduler/dispatcher 执行 follow-up run
```

因此看到两条 run：

```text
assignment run
automation/passive follow-up run
```

这不是同一个 run 被重复 claim。底层 claim 使用条件更新：

```text
heartbeat_runs.status == queued
```

同一条 run 只能被一个 dispatcher 从 `queued` 改成 `running`。

## 上游 upstream reference 行为

上游参考实现位于：

```text
D:\coding\upstream-reference
```

关键文件：

```text
D:\coding\upstream-reference\server\src\services\runtime-kernel\heartbeat.release.ts
D:\coding\upstream-reference\server\src\services\runtime-kernel\heartbeat.recovery.ts
D:\coding\upstream-reference\server\src\services\runtime-kernel\heartbeat.sessions.ts
D:\coding\upstream-reference\packages\agent-runtime-utils\src\server-utils.prompts.ts
D:\coding\upstream-reference\server\src\__tests__\heartbeat-passive-issue-closeout.test.ts
```

上游主线：

```text
execute run finishes
  ↓
releaseIssueExecutionAndPromote(run)
  ↓
evaluatePassiveIssueClosureForLockedIssue(...)
  ↓
queue issue_passive_followup / reviewer closeout / operator review
```

上游关键规则：

| 规则 | 上游行为 |
| --- | --- |
| 成功 run 自动 done | 不会 |
| 缺 close-out | queue `issue_passive_followup` |
| follow-up source | `automation` |
| follow-up wake source | `passive_issue_followup` |
| failure reason | `missing_closure` |
| max attempts | 2 |
| cooldown | 第 1 次约 2 分钟，第 2 次约 5 分钟 |
| 有 reviewer 且 attempts exhausted | 请求 convergence review |
| 无 reviewer 且 attempts exhausted | 记录 operator review |

上游 prompt 也明确写明：

```text
This is a passive issue follow-up, not a fresh assignment and not a failure recovery.
```

## 当前 Octopus 与上游差异

当前 Python 实现已经具备基础 close-out governance，并已对齐 passive follow-up 的
automation source、wake source、failure reason、attempt metadata、idempotency key
和 cooldown 排队语义。

已实现：

- 成功 run 不自动 done。
- 成功 issue run 缺 close-out 时 queue passive follow-up。
- reviewer run 缺少结构化 decision 时 queue reviewer closeout。
- issue execution lock 终态释放。
- deferred issue wakeup 在锁释放后 promote。

主要差异：

| 维度 | 当前 Octopus | 上游 upstream reference |
| --- | --- | --- |
| passive follow-up source | `automation` | `automation` |
| wake source | `passive_issue_followup` | `passive_issue_followup` |
| reason 文案 | `missing_closure` | `missing_closure` |
| attempts metadata | `maxAttempts = 2` | `maxAttempts = 2` |
| cooldown | 第 1 次约 2 分钟 | 第 1 次约 2 分钟，第 2 次约 5 分钟 |
| escalation | 基础实现较少 | reviewer convergence / operator review |
| events/activity | 基础实现较少 | 记录 follow-up queued、operator review、convergence review |
| idempotency key | `issue_passive_followup:<run>` | `issue_passive_followup:<run>` |

这些差异不会改变“为什么会出现第二次 run”的核心结论，但会影响用户对重复执行、延迟、升级和审计记录的感知。

## Agent 应该如何避免被再次唤醒

agent 在成功退出前，应留下一个明确 close-out signal。

推荐动作：

```text
完成了任务：
  PATCH issue status = done

还没完成但有进展：
  添加 issue comment，说明已完成内容和下一步

被阻塞：
  PATCH issue status = blocked，并写清原因

需要 review：
  PATCH issue status = in_review

只是交接给别人：
  添加明确 handoff comment
```

不要只让 runtime 进程成功退出。进程成功但 issue 未收尾时，server 会按治理逻辑继续唤醒 agent。

## 排查“执行两次”的方法

先区分是哪一种：

```text
同一 run 执行两次
两条不同 run，第二条是 passive follow-up
两条不同 run，来自两个独立 wakeup
```

排查字段：

```text
heartbeat_runs.id
heartbeat_runs.invocation_source
heartbeat_runs.status
heartbeat_runs.context_snapshot.issueId
heartbeat_runs.context_snapshot.wakeReason
heartbeat_runs.context_snapshot.passiveFollowup
agent_wakeup_requests.reason
agent_wakeup_requests.idempotency_key
issues.execution_run_id
issues.checkout_run_id
activity_log.action
```

判断方式：

| 现象 | 结论 |
| --- | --- |
| 第二条 run 的 `wakeReason = issue_passive_followup` | close-out governance |
| 第二条 run 的 `retryOfRunId` 不为空 | retry/recovery |
| 第二条 run 的 `reason = issue_execute` | 用户/API 重新执行 |
| 多条 queued run 但 issue lock 未释放 | deferred wakeup/promotion 需要检查 |
| 同一 run 出现两次 `adapter.invoke` | 才需要怀疑同一 run 被重复执行 |

## 相关代码

当前 Octopus：

```text
server/services/heartbeat.py
server/routes/issues.py
server/services/issue_assignment_wakeup.py
server/services/issue_review_wakeup.py
packages/database/queries/heartbeat.py
packages/database/schema/heartbeat.py
packages/database/schema/issues.py
```

相关测试：

```text
tests/contract/test_step11_agent_management.py
tests/contract/test_step8_issue_management.py
tests/workflows/test_step13_run_workflow.py
```
