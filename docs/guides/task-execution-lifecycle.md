# 任务执行生命周期

本文总结 Octopus 如何把产品里的工作项转成 agent 的实际执行。

最重要的区分是：

```text
issue
= 产品里的任务 / 工作项

heartbeat_run
= agent 的一次可执行运行
```

一个 issue 可以触发 run，但执行队列不是 issue 看板。真正的执行队列持久化在数据库里的 `heartbeat_runs.status`。

## 总体流程

```text
Issue / Chat / 手动触发 / 定时心跳 / 重试
  -> wakeup request
  -> heartbeat_run(status = queued)
  -> claim
  -> heartbeat_run(status = running)
  -> runtime adapter 执行
  -> events、logs、usage、cost、runtime state、work products 回写
  -> succeeded / failed / timed_out / cancelled
```

核心实现位置：

```text
server/services/heartbeat.py
server/services/issue_assignment_wakeup.py
server/routes/issues.py
server/lifespan.py
packages/runtimes/types.py
packages/runtimes/registry.py
packages/database/schema/heartbeat.py
```

相关文档：

```text
docs/guides/task-queue.md
docs/guides/heartbeat-scheduler.md
```

## 执行入口

Run 可以由多种产品事件创建：

| 来源 | 含义 |
| --- | --- |
| Issue 分配或执行 | 任务分配给 agent，或用户显式执行任务。 |
| Issue checkout | agent 领取任务并开始处理。 |
| Timer heartbeat | scheduler 发现某个 agent 到了定时执行时间。 |
| Manual wakeup | 用户或 agent 手动唤醒某个 agent。 |
| Review / follow-up | 待 review 或后续跟进工作唤醒 agent。 |
| Retry / recovery | 终态 run 或 orphaned run 创建新的 queued run。 |
| Chat | Chat 可以调用 runtime 或转成 issue，但不会为了展示而伪造 heartbeat run。 |

主要的 issue 执行接口是：

```text
POST /api/issues/{id}/execute
```

它要求 issue 已经有 `assigneeAgentId`。如果该 issue 已经存在 active 的 queued/running run，会直接返回已有 run，避免重复创建。

## Issue 如何变成 Wakeup

Issue 驱动的唤醒通过 `queue_issue_assignment_wakeup()` 创建。

它会构造类似这样的 wakeup payload：

```json
{
  "source": "assignment",
  "triggerDetail": "system",
  "reason": "issue_execute",
  "payload": {
    "issueId": "issue-id",
    "mutation": "execute"
  },
  "contextSnapshot": {
    "issueId": "issue-id",
    "wakeSource": "assignment",
    "wakeReason": "issue_execute",
    "issue": {
      "id": "issue-id",
      "title": "任务标题",
      "description": "任务描述",
      "status": "todo",
      "priority": "medium"
    }
  }
}
```

这里的 issue 快照只是 runtime 执行时的上下文。真正进入执行队列的对象仍然是 `heartbeat_run`。

## Wakeup 与 Queued Run 创建

`HeartbeatService.wakeup()` 是 run 入队前的 gate。

它会检查：

- agent 是否存在
- agent 状态，拒绝 `terminated` 和 `pending_approval`
- 非 timer wakeup 是否被 `wakeOnDemand=false` 禁止
- budget 是否阻止本次调用
- idempotency key 是否已经对应已有 run
- agent paused 时是否需要延期
- issue 是否已有执行锁

如果允许执行，会调用 `_create_queued_run()` 写入：

```text
agent_wakeup_requests.status = queued
heartbeat_runs.status = queued
```

同时会：

- 初始化本地 run log
- 把 wakeup request 关联到 run
- 如果上下文里有 issue id，则补齐 issue context
- 写入第一条 lifecycle event：`run queued`
- assignment run 会尝试给 issue 写入执行锁

## Scheduler 与 Dispatch

Scheduler 从 `server/lifespan.py` 启动。

启动时会执行：

```text
recover_orphaned_runs()
dispatch_all_queued_runs()
```

之后每个 tick 执行：

```text
tick_timers()
dispatch_all_queued_runs()
```

Timer heartbeat 只负责创建 wakeup。真正执行仍然走同一套 queued、claim、running、runtime adapter 流程。

## Claim 与并发控制

Claim 是从 queued 变成 running：

```text
queued -> running
```

它的作用是防止重复执行。多个 dispatcher 可能同时看到同一个 queued run，但只有一个 dispatcher 能 claim 成功。

并发限制按 agent 控制：

```text
runtimeConfig.heartbeat.maxConcurrentRuns
```

Dispatcher 会按下面方式计算可用容量：

```text
maxConcurrentRuns - 数据库中 running 的 run - 当前进程内 active 的 run
```

如果没有容量，run 会继续保持 `queued`。

## Runtime 执行

Run claim 成功后，`execute_claimed_run()` 会调用 `_execute_run()`。

执行服务会：

1. 加载 agent。
2. 通过 `get_runtime_adapter(agent.agent_runtime_type)` 选择 runtime adapter。
3. 准备 workspace context。
4. 为 adapter 执行创建 workspace operation。
5. 构造 agent runtime config。
6. 注入 Octopus 上下文，例如 agent 名称、run context、session id、desired skills。
7. 注入 runtime provider/model 配置。
8. 创建 `RuntimeExecutionContext`。
9. 调用 `adapter.execute(context)`。

Runtime contract 是：

```text
RuntimeExecutionContext -> RuntimeExecutionResult
```

当前已注册的 runtime adapter 包括：

```text
process
http
codex_local
claude_local
opencode_local
openclaw_gateway
```

已知但尚不可用的 runtime id 会返回 unavailable adapter，而不是让系统直接崩溃。

## 日志与事件

Runtime adapter 通过 `on_log` 回调流式输出日志。

每个 log chunk 可能写入：

- 本地 run log 文件
- `heartbeat_run_events`
- workspace operation log

本地子进程类 runtime 还可以调用 `on_process_started`，记录：

```text
process_pid
process_started_at
```

这些信息用于实时查看和取消当前执行。但恢复流程不会盲目 kill 历史 PID，因为 PID 可能被系统复用。

## 执行完成与结果持久化

Adapter 执行结束后，`_execute_run()` 会计算最终状态：

| 条件 | 最终状态 |
| --- | --- |
| `result.timed_out` | `timed_out` |
| `result.error_message` 或非 0 exit code | `failed` |
| 其它情况 | `succeeded` |

然后持久化：

- run 状态和完成时间
- exit code 和 signal
- error 和 error code
- usage JSON
- result JSON
- 执行后的 session id
- stdout/stderr 摘要
- log 元数据
- runtime services
- run work products
- 成功时生成的 workspace files
- cost event
- agent runtime state

如果 run 和 issue 相关，进入终态后会清理 issue 的执行锁。

## Issue Review 与 Approval

Review 是 issue workflow 上的业务层，不是执行队列的基础对象。

Issue review decision 对状态的影响是：

| Decision | 状态变化 |
| --- | --- |
| `approve` | `done` |
| `request_changes` | `in_progress` |
| `blocked` | `blocked` |
| `needs_followup` | 记录 human intervention activity |

Approval 是另一套审批流程，用于需要显式批准的动作。它可以影响业务流程，但不是 heartbeat queue 的核心状态机。

## 取消

Queued 和 running run 都可以取消：

```text
queued/running -> cancelled
```

对于 running run，服务会设置内存里的 cancellation event。Runtime adapter 可以观察这个事件并停止子进程。关联的 workspace operation 会被标记为 interrupted。

## 重试

只有终态 run 可以重试：

```text
failed
timed_out
cancelled
```

重试会创建一个新的 run：

```text
retryOfRunId = 原始 run id
status = queued
```

原始 run 不会被覆盖。

## Orphaned Run 恢复

如果 server 重启时某个 run 还处于 `running`，重启后的 server 可能已经没有它的进程控制权。

启动恢复流程会：

1. 找到当前进程不知道的 running runs。
2. 把它们标记为 `failed`。
3. 使用 error code：`process_lost`。
4. 写入 lifecycle 证据。
5. 在限制内创建 automatic recovery run。

恢复流程不会盲目 kill 历史 PID，因为 PID 可能复用，直接 kill 可能误杀无关进程。

## 排查顺序

当任务没有执行时，建议按这个顺序检查：

1. `heartbeat_runs.status`
2. agent 状态
3. `runtimeConfig.heartbeat.maxConcurrentRuns`
4. scheduler 是否开启
5. run events
6. run log
7. `contextSnapshot.wakeReason` 和 `invocationSource`
8. issue 执行锁，尤其是 `checkoutRunId` 和 `executionRunId`
9. runtime adapter 环境检查

常见 queued run 卡住原因：

- scheduler 关闭
- agent paused、pending approval 或 terminated
- 该 agent 的并发容量已满
- claim 失败，因为其他 dispatcher 已经领取
- wakeup 被 issue execution lock 延期
- runtime 前置条件缺失

## 总结

Octopus 的任务执行是基于数据库的 run 队列。

```text
issue 描述要做什么
heartbeat_run 表示一次实际执行
claim 防止重复执行
scheduler 和 dispatcher 推进 queued runs
runtime adapter 执行具体工作
events、logs、state、cost、work products 是执行证据
```
