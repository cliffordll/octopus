# Heartbeat Scheduler Guide

本文说明 Octopus / upstream reference 系列实现里的 heartbeat 定时任务逻辑、开关层级和 UI 含义。

核心结论：

```text
/instance/settings/heartbeats 管的是 timer heartbeat
不是所有 wakeup 的总开关
```

也就是说，关闭该页面中的某个 agent heartbeat，只会关闭该 agent 的定时心跳；如果其他唤醒来源仍然开启，例如任务分配、审批通过、评论 mention、手动 invoke、retry 或 automation，该 agent 仍可能被唤醒。

## 核心概念

| 概念 | 作用 |
| --- | --- |
| scheduler | server 后台周期任务，按固定间隔扫描 agent timer heartbeat |
| timer heartbeat | 按 agent 配置的 interval 自动触发的 heartbeat |
| wakeup request | 一次唤醒请求，来源可能是 timer、assignment、review、manual、automation 等 |
| heartbeat run | 真正进入执行队列的 run，通常由 wakeup 创建 |
| agent heartbeat policy | agent runtimeConfig 中的 heartbeat 配置 |
| preflight | timer 触发前检查 agent 是否确实有可执行任务 |

## 全局 scheduler 开关

后台 scheduler 默认开启。

全局关闭方式：

```bash
HEARTBEAT_SCHEDULER_ENABLED=false
```

默认 tick 间隔：

```bash
HEARTBEAT_SCHEDULER_INTERVAL_MS=30000
```

含义：

- `HEARTBEAT_SCHEDULER_ENABLED=false` 会关闭 server 后台定时扫描。
- `HEARTBEAT_SCHEDULER_INTERVAL_MS` 控制 scheduler 多久 tick 一次，默认 30 秒。
- 这个开关是实例级 / server 级开关，不是 agent 配置，也不是 UI 上逐行开关。

关闭全局 scheduler 后，timer heartbeat 不会由后台周期任务触发；但已有 queued run、手动 invoke、retry、assignment wakeup 等是否执行，还取决于其他服务逻辑和 agent policy。

## Agent 级 heartbeat policy

每个 agent 的定时行为来自：

```json
{
  "runtimeConfig": {
    "heartbeat": {
      "enabled": true,
      "intervalSec": 300,
      "wakeOnDemand": true,
      "preflightEnabled": true,
      "maxConcurrentRuns": 1
    }
  }
}
```

常用字段：

| 字段 | 含义 |
| --- | --- |
| `enabled` | 是否允许 timer heartbeat |
| `intervalSec` | timer heartbeat 间隔；`0` 表示没有有效定时周期 |
| `wakeOnDemand` | 是否允许非 timer wakeup，例如 assignment、manual、automation |
| `preflightEnabled` | timer 触发前是否先检查有没有可执行任务 |
| `maxConcurrentRuns` | 限制该 agent 可并发运行数量 |

默认解释：

```text
enabled 默认 true
intervalSec 默认 0
wakeOnDemand 默认 true
preflightEnabled 默认 true
```

所以一个 agent 即使 `enabled=true`，如果 `intervalSec=0`，也只是“配置未激活”，不会被 timer scheduler 定时跑。

## Timer heartbeat 触发流程

后台 scheduler 大致按以下流程运行：

```text
server interval tick
  ↓
遍历 active agents
  ↓
读取 runtimeConfig.heartbeat
  ↓
跳过 paused / terminated / pending_approval agent
  ↓
检查 enabled 和 intervalSec
  ↓
检查距离 lastHeartbeatAt 是否超过 intervalSec
  ↓
执行 timer preflight
  ↓
创建 wakeup / heartbeat run
```

关键条件：

```text
agent.status 不能是 paused / terminated / pending_approval
heartbeat.enabled 必须为 true
heartbeat.intervalSec 必须 > 0
距离上次 heartbeat 已超过 intervalSec
```

如果开启 preflight，timer 在真正入队前还会检查该 agent 是否有值得执行的工作。

## Timer preflight 检查什么

默认 preflight 会避免“空跑”。

常见通过条件：

```text
存在 assignee issue:
  issue.assigneeAgentId = agent.id
  issue.status in [todo, in_progress, blocked]

或存在 reviewer issue:
  issue.reviewerAgentId = agent.id
  issue.status in [in_review, blocked]
```

如果没有可执行任务，timer wakeup 会被 skip，并记录类似：

```text
heartbeat.preflight.no_work
heartbeat.preflight.pending_wakeup_request
```

实际命名以实现为准，但产品含义是：timer tick 到了，不代表一定会启动 runtime。

## 非 timer wakeup

Timer heartbeat 只是唤醒来源之一。

其他常见来源：

| 来源 | 示例 |
| --- | --- |
| assignment | 创建任务时分配 agent；或把任务分配给 agent |
| status change | 从 backlog 移到 todo / in_progress，且已有 assignee |
| review | 进入 in_review 或 reviewer 变化 |
| manual / on-demand | 手动 invoke agent |
| approval | 审批通过后唤醒 requester 或相关 assignee |
| mention | 评论中 mention 某个 agent |
| retry / recovery | 失败 run 重试或进程丢失恢复 |
| automation | 自动化规则触发 |

这些来源通常走 `source !== "timer"` 的路径。

如果要关闭非 timer wakeup，需要配置：

```json
{
  "runtimeConfig": {
    "heartbeat": {
      "wakeOnDemand": false
    }
  }
}
```

注意：`wakeOnDemand=false` 影响面很大，可能会让 assignment、manual invoke、automation 等都无法唤醒该 agent。它不是“只关手动按钮”的开关。

## `/instance/settings/heartbeats` 页面含义

实例设置页：

```text
/instance/settings/heartbeats
```

主要对应：

```text
GET /api/instance/scheduler-heartbeats
```

它展示的是所有非隐藏、可运行 agent 的 scheduler heartbeat 状态。

页面字段通常来自：

```text
agent.runtimeConfig.heartbeat.enabled
agent.runtimeConfig.heartbeat.intervalSec
agent.status
agent.lastHeartbeatAt
```

页面里的开关写回：

```json
{
  "runtimeConfig": {
    "heartbeat": {
      "enabled": true
    }
  }
}
```

也就是说，该页面的 On / Off 控制的是：

```text
agent.runtimeConfig.heartbeat.enabled
```

不是：

```text
HEARTBEAT_SCHEDULER_ENABLED
wakeOnDemand
assignment wakeup
manual invoke
retry
review wakeup
automation wakeup
```

## 页面状态说明

页面通常会显示三类状态：

| 状态 | 含义 |
| --- | --- |
| Scheduled | `enabled=true`，`intervalSec>0`，agent 状态允许运行 |
| Configured, inactive | `enabled=true`，但 `intervalSec=0` 或 agent 当前不可调度 |
| Disabled | `enabled=false` |

其中最容易误解的是 `Configured, inactive`：它不是彻底关闭，而是“配置存在，但 timer scheduler 当前不会按周期跑”。

## 任务状态和自动执行的关系

从 UI 看，用户可能会把任务拖到 `in_progress`，然后看到 agent 开始执行。

更准确的解释是：

```text
todo / in_progress / blocked + assigneeAgentId
会被 timer preflight 认为是可执行任务
```

所以执行可能来自后台 timer，而不是拖拽动作本身直接触发。

常见触发路径：

```text
任务已分配 agent
  ↓
状态为 todo / in_progress / blocked
  ↓
scheduler tick 到该 agent
  ↓
preflight 发现可执行任务
  ↓
创建 heartbeat run
```

另外，如果任务分配动作本身发生在非 backlog 状态，也可能由 assignment wakeup 直接触发，而不需要等 timer。

## 如何彻底停止某个 agent 自动跑

按严格程度从轻到重：

### 只关闭定时自动跑

```json
{
  "runtimeConfig": {
    "heartbeat": {
      "enabled": false
    }
  }
}
```

或在 `/instance/settings/heartbeats` 把该 agent 关掉。

效果：

- timer scheduler 不会按周期唤醒它。
- assignment / manual / automation 等非 timer wakeup 仍可能触发。

### 关闭定时周期

```json
{
  "runtimeConfig": {
    "heartbeat": {
      "intervalSec": 0
    }
  }
}
```

效果与 timer inactive 类似，但 UI 可能显示为 configured inactive，而不是 disabled。

### 关闭非 timer wakeup

```json
{
  "runtimeConfig": {
    "heartbeat": {
      "wakeOnDemand": false
    }
  }
}
```

效果：

- assignment、manual invoke、automation、review 等非 timer 唤醒会被拒绝。
- 使用前要确认这符合产品预期。

### 暂停 agent

将 agent status 设为 `paused`。

效果：

- timer scheduler 会跳过。
- 部分 wakeup 可能被延期为 paused deferred 状态，恢复后再重放。

### 全局关闭 scheduler

```bash
HEARTBEAT_SCHEDULER_ENABLED=false
```

效果：

- 当前 server 实例不再跑 timer scheduler。
- 不影响所有非 timer 唤醒语义。

## 排查 checklist

如果“明明关了 heartbeat，agent 还是跑了”，按顺序检查：

1. 关的是 `/instance/settings/heartbeats` 上的 row 开关，还是 server 环境变量？
2. agent 的 `runtimeConfig.heartbeat.enabled` 是否已经变为 false？
3. agent 的 `wakeOnDemand` 是否仍为 true？
4. run 的 `invocationSource` 是 `timer`、`assignment`、`review`、`on_demand` 还是 `automation`？
5. 任务是否刚被分配给该 agent？
6. 是否有审批通过、评论 mention、retry 或 recovery 触发？
7. agent 是否 paused 后又恢复，导致 deferred wakeup 被重放？
8. 是否已有 queued run 在关闭 timer 前已经入队？

最重要的判断字段是 heartbeat run 的：

```text
invocationSource
triggerDetail
contextSnapshot.wakeReason
contextSnapshot.wakeSource
```

## 建议的产品表达

为了减少误解，UI 文案应区分：

```text
Timer heartbeats
On-demand wakeups
Assignment wakeups
Running runs
```

不要把 `/instance/settings/heartbeats` 表达成“所有自动执行总开关”。更准确的标题是：

```text
Scheduled heartbeats
Timer heartbeat state
```

对于想彻底阻止 agent 自动接任务的用户，应提供更明确的组合操作：

```text
Disable scheduled heartbeats
Disable assignment/on-demand wakeups
Pause agent
Cancel queued/running runs
```
