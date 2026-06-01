# Task Queue Guide

本文说明 Octopus 当前任务队列的控制方式。

当前实现里，任务队列不是 Redis、Celery 或外部消息队列，而是基于数据库状态的持久化队列。

核心思想：

```text
heartbeat_runs.status = queued
```

表示任务已经进入队列，等待被领取和执行。

## 核心对象

| 对象 | 作用 |
| --- | --- |
| `agent_wakeup_requests` | 记录 agent 被唤醒的请求，包括手动触发、timer、paused 延期等 |
| `heartbeat_runs` | 记录一次实际执行 run，是队列和执行状态的核心表 |
| scheduler | server 后台周期任务，负责 timer、恢复和推进 queued runs |
| dispatcher | 领取 queued run，并调用 runtime adapter 执行 |
| runtime adapter | 具体执行 Codex/Claude/OpenCode/http 等 runtime |

相关代码：

```text
server/services/heartbeat.py
server/lifespan.py
packages/database/queries/heartbeat.py
packages/database/schema/heartbeat.py
packages/database/schema/agent_state.py
```

## 基本状态流

一次任务执行大致经过：

```text
wakeup request
  ↓
heartbeat_run(status = queued)
  ↓ claim
heartbeat_run(status = running)
  ↓ runtime adapter execute
succeeded / failed / timed_out / cancelled
```

含义：

- `queued`：任务已登记，尚未开始执行。
- `running`：任务已被某个 dispatcher 领取，正在执行。
- `succeeded`：执行成功。
- `failed`：执行失败。
- `timed_out`：执行超时。
- `cancelled`：执行被取消。

## 入队

当 agent 被唤醒时，server 会创建一条 run：

```text
heartbeat_runs.status = queued
```

常见入队来源：

- 手动 wakeup
- HTTP invoke
- timer heartbeat
- retry/recovery
- paused agent 恢复后重放延期 wakeup

如果 agent 当前是 paused，wakeup 不会立即创建普通可执行 run，而会先延期：

```text
agent_wakeup_requests.status = deferred_agent_paused
```

agent 恢复后，延期 wakeup 再重新变成 queued run。

## 并发控制

队列不是全局只跑一个任务，而是按 agent 控制并发。

每个 agent 的最大并发来自：

```text
runtimeConfig.heartbeat.maxConcurrentRuns
```

当前规则：

```text
默认值：3
允许范围：1..10
```

调度时会检查该 agent 当前 `running` 数量：

```text
running_count >= maxConcurrentRuns
```

如果已达到上限，新的 run 保持：

```text
queued
```

等已有 running run 结束后，scheduler 再继续领取 queued run。

## Claim 是什么

`claim` 是“领取执行权”。

它不是审批，也不是权限判断。

它解决的是并发竞争问题：多个 dispatcher 可能同时看到同一个 `queued` run，必须保证只有一个 dispatcher 真正执行它。

典型状态变化：

```text
queued -> running
```

典型条件更新：

```sql
UPDATE heartbeat_runs
SET status = 'running'
WHERE id = :run_id
  AND status = 'queued'
```

如果更新成功，说明当前 dispatcher 拿到了唯一执行权。

如果没有更新到记录，说明：

- 该 run 已经被其他 dispatcher claim
- 或该 run 已被取消、重试、恢复、状态改变

此时当前 dispatcher 必须放弃执行。

## Scheduler 怎么推进队列

server 启动时，`server/lifespan.py` 会启动 heartbeat scheduler。

启动阶段会做：

```text
recover_orphaned_runs()
dispatch_all_queued_runs()
```

之后按周期执行：

```text
tick_timers()
dispatch_all_queued_runs()
```

配置项：

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| `OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED` | `true` | 是否启动 heartbeat scheduler |
| `OCTOPUS_HEARTBEAT_SCHEDULER_INTERVAL_SECONDS` | `5` | scheduler 周期，单位秒 |

如果关闭 scheduler，queued run 仍会被创建，但不会由后台周期任务自动推进。

## Dispatcher 怎么执行

dispatcher 的核心动作：

1. 找到有 queued run 的 agent。
2. 检查 agent 状态和并发容量。
3. 对 queued run 执行 claim。
4. claim 成功后准备 runtime context。
5. 调用 runtime adapter。
6. 写入 run events、result、usage、error、cost 等执行结果。
7. 把 run 更新为终态。

简化流程：

```text
list queued agent ids
  ↓
for each agent
  ↓
check maxConcurrentRuns
  ↓
claim queued runs
  ↓
execute claimed runs
```

## 取消

queued 或 running run 可以取消。

取消 queued run：

```text
queued -> cancelled
```

取消 running run：

```text
running -> cancelled
```

running run 取消时，本地 runtime adapter 会尝试通过当前内存里的 process handle 中断 child process。

取消是当前活跃执行层面的操作，不等同于恢复阶段扫描历史 PID 并 kill OS 进程。

## 重试

只有终态 run 可以重试，例如：

```text
failed
timed_out
cancelled
```

重试会创建新的 recovery run：

```text
retryOfRunId = <original-run-id>
status = queued
```

这样保留原始 run 和恢复 run 的关系，而不是覆盖原 run。

## Orphaned Run 恢复

server 重启后，数据库中可能还有：

```text
heartbeat_runs.status = running
```

但原来的 server 进程已经不存在。

这类 run 称为 orphaned run。

当前策略：

1. 把原 run 标记为 failed。
2. error code 记录为 `process_lost`。
3. 写入 lifecycle event。
4. 在限制内创建一次 automatic recovery run。
5. recovery run 重新进入 `queued`。

注意：server recovery 不主动 kill 历史 PID。

原因是当前只持久化 PID，不能可靠证明该 PID 仍属于原来的 child process。Windows 和长生命周期开发环境中 PID 可能复用，盲目 kill 会误杀其他进程。

## Timer 触发

如果 agent 配置了 heartbeat timer，scheduler 会周期性检查并创建 timer 来源的 wakeup/run。

简化流程：

```text
scheduler tick
  ↓
for each organization
  ↓
tick_timers(org_id)
  ↓
create timer wakeup/run if due
  ↓
dispatch queued runs
```

timer 只是入队来源之一。真正执行仍走同一套 queued、claim、running、runtime adapter 流程。

## 幂等与合并

wakeup 可以带 `idempotencyKey`。

相同 `idempotencyKey` 的重复请求不会无限创建重复 run，而会复用或合并已有请求/结果。

paused agent 的延期 wakeup 可合并，并累计：

```text
coalescedCount
```

这样可以避免 agent 暂停期间大量重复 wakeup 造成队列膨胀。

## 与 issue 队列的关系

当前任务队列控制的是 agent run 执行队列。

它不等同于 issue board。

```text
issue
= 产品里的任务/工作项

heartbeat_run
= agent 的一次执行
```

一个 issue 可以触发 agent run，但 issue 本身不是队列里的执行单位。

执行队列真正调度的是：

```text
heartbeat_runs
```

## 与 chat 的关系

Chat assistant invocation 不应被伪装成 heartbeat run。

如果上游没有把 chat assistant 调用持久化为 heartbeat run，Octopus 也不应该为了可见性创建假的 run 记录。

因此：

- heartbeat queue 管理后台/agent wakeup/run 执行。
- chat invocation 是用户对话触发的 assistant/runtime 调用。
- 两者可以共享 runtime adapter 能力，但不是同一个业务对象。

## 常见问题

### 为什么 run 一直是 queued？

常见原因：

- scheduler 没启动
- agent 已达到 `maxConcurrentRuns`
- agent paused、pending approval 或 terminated
- runtime adapter 执行前置条件不满足
- claim 没成功
- server 没有继续 dispatch queued runs

优先检查：

```text
OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED
OCTOPUS_HEARTBEAT_SCHEDULER_INTERVAL_SECONDS
agent.status
runtimeConfig.heartbeat.maxConcurrentRuns
heartbeat_runs 中同 agent 的 running 数量
```

### 为什么同一个任务不会被执行两次？

靠 claim 条件更新保证：

```sql
WHERE id = :run_id
  AND status = 'queued'
```

只有一个 dispatcher 能把它改成 `running`。

### 为什么 server 重启后 run 会失败并重新排队？

重启后原 `running` run 失去了当前进程上下文。server 无法确认旧 child process 是否仍安全可控，所以把原 run 标记为 `failed/process_lost`，再创建 recovery run。

### 为什么不直接 kill 旧 PID？

因为 PID 可能复用。

只持久化 PID 时，server 无法可靠证明该 PID 仍是原 child process。盲目 kill 可能误杀无关 Python、Codex、测试或系统进程。

## 调试顺序

### 1. 看 run 状态

```text
heartbeat_runs.status
```

重点看：

```text
queued
running
failed
timed_out
cancelled
```

### 2. 看 agent 状态

```text
agents.status
```

重点看：

```text
idle
running
paused
pending_approval
terminated
error
```

### 3. 看并发容量

```text
runtimeConfig.heartbeat.maxConcurrentRuns
同 agent 的 running run 数量
```

### 4. 看 events

```text
GET /api/heartbeat-runs/{runId}/events?afterSeq=0&limit=50
```

events 能看到 run started、run cancelled、run failed、adapter invoke 等 lifecycle 证据。

### 5. 看 scheduler 是否运行

确认 server 配置：

```text
OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED=true
```

如果 scheduler 关闭，只创建 queued run，不会周期性自动推进。

## 总结

Octopus 当前任务队列由数据库状态控制：

```text
queued 表示入队
running 表示已领取并执行中
claim 防止重复执行
maxConcurrentRuns 控制每 agent 并发
scheduler 周期性推进 timer 和 queued runs
recovery 处理 server 重启后的 orphaned running runs
```

一句话：

```text
Octopus 的任务队列是基于 heartbeat_runs 的持久化 DB 队列，通过状态机、条件 claim、per-agent 并发限制和 scheduler 推进执行。
```

