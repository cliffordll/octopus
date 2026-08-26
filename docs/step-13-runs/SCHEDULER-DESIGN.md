# Step 13 Scheduler 设计文档：任务是怎么被执行的

这份文档只解释一件事：

```text
Octopus 里有一个任务之后，它是怎么排队、怎么启动 agent、怎么继续执行下一条任务的。
```

先给结论：

```text
任务系统负责判断“哪个任务该跑”。
业务入口负责写入 wakeup/run 记录。
dispatcher 负责把 queued run 启动成 running。
scheduler 负责兜底扫描和到期推进。
timer heartbeat 不是任务执行主链路。
```

## 1. 一条任务从创建到执行完，完整流程是什么

假设用户把任务 A 分配给 Agent-1。

系统执行链路是：

```text
1. 用户/系统改变 issue
   例如：创建任务、分配 assignee、点击执行、进入 review、触发自动收口。

2. issue 业务逻辑判断：这个任务现在应该让哪个 agent 跑。

3. 写入 agent_wakeup_requests
   记录“为什么要唤醒 Agent-1”。

4. 写入 heartbeat_runs
   创建一条 status=queued 的 run。

5. 调用 dispatcher
   尝试把 Agent-1 的 queued run 跑起来。

6. dispatcher 检查 Agent-1 是否还有执行容量。
   有容量：把 run 从 queued 改成 running，并启动 agent runtime。
   没容量：run 保持 queued，等之后再执行。

7. agent runtime 执行任务。

8. 执行结束后写 heartbeat_runs 最终状态。
   succeeded / failed / cancelled / timed_out。

9. 当前 run 结束后，再调用一次 dispatcher。
   如果 Agent-1 还有 queued run，就继续启动下一条。
```

一句话：

```text
任务事件入队；dispatcher 从队列取 run；run 结束后 dispatcher 再拉下一条。
```

## 2. 这里涉及哪些表

| 表 | 作用 | 谁主要写 |
| --- | --- | --- |
| `issues` | 任务本身，包含状态、assignee、reviewer、执行锁等 | issue 业务逻辑 |
| `agents` | agent 配置，包含 runtime config、并发上限、心跳配置 | agent 管理逻辑 |
| `agent_wakeup_requests` | 唤醒请求，记录哪个 agent 因为什么要运行 | 业务入口 / heartbeat service |
| `heartbeat_runs` | 一次具体执行，记录 queued/running/succeeded/failed | heartbeat service / dispatcher |
| `heartbeat_run_events` | run 执行过程事件、stdout、stderr | runtime / heartbeat service |
| `activity_log` | issue comment、done、block、review decision 等业务证据 | issue/control-plane 逻辑 |

最核心三张表：

```text
agent_wakeup_requests   为什么要跑
heartbeat_runs          哪一次执行
heartbeat_run_events    执行过程发生了什么
```

## 3. wakeup 和 run 分别是什么

### 3.1 wakeup：为什么要跑

`agent_wakeup_requests` 表示一条唤醒意图。

例如：

```text
Agent-1 需要运行，因为 issue A 被分配给它。
```

关键字段语义：

| 字段 | 含义 |
| --- | --- |
| `agent_id` | 要唤醒哪个 agent |
| `source` | 来源：assignment/review/automation/on_demand/timer |
| `reason` | 具体原因，例如 issue_execute、issue_passive_followup |
| `payload` | 参数，例如 issueId |
| `requested_at` | 什么时候执行，立即或未来时间 |
| `status` | queued/scheduled/claimed/completed/failed |
| `run_id` | 物化出来的 run |

### 3.2 run：一次具体执行

`heartbeat_runs` 表示一次实际执行。

例如：

```text
Agent-1 执行 issue A 的第 1 次 task run。
```

关键字段语义：

| 字段 | 含义 |
| --- | --- |
| `agent_id` | 执行 agent |
| `wakeup_request_id` | 来自哪条 wakeup |
| `invocation_source` | 触发来源 |
| `run_purpose` | 执行目的：task_execution/review/closeout_followup/heartbeat |
| `status` | queued/running/succeeded/failed/cancelled |
| `context_snapshot` | 执行上下文，例如 issueId、wakeReason |
| `error_code` | 机器可读错误，例如 closeout_missing |

## 4. dispatcher 到底是什么

dispatcher 不是常驻进程。

它可以理解成一个函数：

```text
try_start_next_run(agentId)
```

它被调用时做这些事：

```text
1. 查 Agent-1 有没有 queued run。
2. 查 Agent-1 当前 running 数是否超过 maxConcurrentRuns。
3. 如果有容量，claim 一条 queued run。
4. 把 heartbeat_runs.status 从 queued 改成 running。
5. 启动 agent runtime 执行。
6. run 结束后写最终状态。
7. 再检查同一个 agent 是否还有下一条 queued run。
```

它不做：

```text
判断某个 issue 业务上该不该执行。
扫描所有 issue 自己决定谁该跑。
修改 issue 的业务状态。
```

这些是 issue 业务逻辑的责任。

## 5. dispatcher 不常驻，怎么知道有任务

靠两个正常触发点，加一个 scheduler 兜底。

### 5.1 新任务入队后触发一次

```text
issue 业务逻辑创建 queued run
  -> after commit 调 RunDispatchService.dispatch_agent(agentId)
```

如果 agent 空闲，马上启动。

如果 agent 正忙，run 留在 `queued`。

### 5.2 当前 run 结束后再触发一次

```text
Run-1 finished
  -> 当前执行流程再调 RunDispatchService.dispatch_agent(agentId)
  -> 如果有 Run-2 queued，就继续启动 Run-2
```

所以超过并发上限才会真正排队；容量释放后 dispatcher 会继续拉下一条。

### 5.3 scheduler 定期兜底

如果 server 重启、后台 task 丢了、after commit dispatch 没跑起来，scheduler 会定期扫：

```text
queued run
scheduled wakeup
orphaned running run
到期 timer heartbeat
```

然后再调用 dispatcher。

## 6. scheduler 做什么，不做什么

scheduler 是 server 里的常驻后台循环。

它应该做：

```text
1. materialize_due_scheduled_wakeups()
   到期的 scheduled wakeup 转成 queued run。

2. RunDispatchService.dispatch_all()
   扫 queued run，调用 dispatcher。

3. recover_orphaned_runs()
   处理 server 崩溃或进程丢失导致的 running run。

4. tick_timer_heartbeats()
   对配置了 timer heartbeat 且到期的 agent 创建 timer wakeup。
```

它不应该做：

```text
扫描所有 issue -> 自己判断哪些 issue 该执行 -> 直接启动 agent。
```

更准确地说：

```text
scheduler 可以扫 run/wakeup 这类调度表。
scheduler 不应该成为 issue 业务规则判断者。
```

如果确实需要定期补偿遗漏 issue，应该是专门的 issue reconciliation：

```text
issue reconciliation
  -> 扫描 issue
  -> 发现缺失 wakeup/run
  -> 创建 assignment/review/automation wakeup
  -> 后续仍然交给 dispatcher 执行
```

## 7. timer heartbeat 在这里是什么角色

timer heartbeat 只是 wakeup 的一种来源。

它适合：

```text
周期巡检
定时同步
长期后台维护
非 issue 型 agent 定时工作
```

它不适合：

```text
任务分配后等 300 秒再让 agent 自己找任务
review 等 300 秒再开始
自动收口等 timer 心跳顺便做
```

所以关闭 timer heartbeat，只应该影响周期心跳，不应该影响：

```text
assignment wakeup
review wakeup
automation wakeup
on_demand wakeup
已经 queued 的 run
```

## 8. 四种主要执行场景

### 8.1 普通任务执行

```text
issue assigned to Agent-1
  -> agent_wakeup_requests(source=assignment, reason=issue_execute)
  -> heartbeat_runs(status=queued, run_purpose=task_execution)
  -> dispatcher claim queued -> running
  -> Agent-1 执行
```

### 8.2 agent 忙时的新任务

```text
Agent-1 正在执行 Run-1
新任务创建 Run-2 queued
  -> dispatcher 被调用
  -> 发现 running 数达到 maxConcurrentRuns
  -> Run-2 保持 queued

Run-1 结束
  -> dispatcher 再次被调用
  -> claim Run-2
  -> Run-2 running
```

### 8.3 评审

```text
issue 进入 in_review
  -> agent_wakeup_requests(source=review)
  -> heartbeat_runs(run_purpose=review)
  -> dispatcher 启动 reviewer agent
```

### 8.4 自动收口

```text
task run succeeded 但没有 closeout activity
  -> 创建 agent_wakeup_requests(source=automation, reason=issue_passive_followup, status=scheduled)
  -> 到期后 scheduler materialize 成 queued run
  -> dispatcher 启动 closeout_followup run
```

人工提前触发：

```text
POST /api/issues/{issueId}/passive-followup
  -> 找已有 scheduled follow-up
  -> 提前 materialize
  -> dispatcher 执行
```

## 9. closeout 为什么不应该立刻报错

run 成功只表示 agent 进程执行结束。

issue 是否完成，要看当前 run 有没有写出明确 closeout 证据：

```text
issue.comment_added
issue.status_changed -> done/in_review/blocked
issue.review_decision_recorded
```

如果第一次缺 closeout：

```text
run 保持 succeeded
创建 automation follow-up
不立刻 errorCode=closeout_missing
```

只有自动 follow-up 尝试用尽仍没有 closeout，才：

```text
heartbeat_runs.status = failed
heartbeat_runs.error_code = closeout_missing
activity_log 写 issue.closure_needs_operator_review
```

## 10. 设计不变量

必须保持这些规则：

- 业务入口判断 issue 是否该执行。
- wakeup 记录为什么要唤醒 agent。
- run 记录一次具体执行。
- dispatcher 只负责 queued -> running -> final status。
- scheduler 只负责到期推进、queued 兜底、timer、orphan recovery。
- timer heartbeat 不参与普通任务执行主链路。
- closeout 必须来自当前 run 的结构化 activity。
- 后台 dispatch 必须保证 DB session close/rollback。

## 11. 验收标准

读这份设计后，应该能判断下面问题：

1. 一个新任务来了，谁写 `agent_wakeup_requests`？
2. 谁写 `heartbeat_runs(status=queued)`？
3. dispatcher 什么时候被调用？
4. agent 忙时新 run 为什么会排队？
5. 当前 run 结束后，下一条 queued run 谁拉起来？
6. scheduler 为什么不是业务判断者？
7. timer heartbeat 为什么不是任务执行主链路？
8. 自动收口为什么等待期不应该报错？

如果这些问题回答不清楚，说明实现或文档还没有把职责边界讲清楚。

## 12. scheduler 的真实扫描模型

当前 scheduler 不是“所有业务表一个个无脑扫”。它分两类扫描。

### 12.1 timer 巡检扫描

这部分会按组织和 agent 扫：

```text
list_organizations()
for each org:
  list_org_agents(org.id)
  for each agent:
    读取 runtime_config.heartbeat
    对比 last_heartbeat_at / created_at 和 intervalSec
    检查是否已有 timer queued/running run
    到期则创建 timer wakeup / queued run
```

涉及表：

```text
organizations
agents
heartbeat_runs
agent_wakeup_requests
```

这就是 timer 巡检，也就是“定时巡检/低频诊断”路径。

### 12.2 scheduled / queued 推进扫描

这部分不是按组织 agent 全扫，而是直接查调度状态：

```text
agent_wakeup_requests
  where status = scheduled
  and requested_at <= now
```

到期后 materialize 成：

```text
heartbeat_runs.status = queued
```

然后查：

```text
heartbeat_runs
  where status = queued
select distinct agent_id
```

再对这些 agent 调 dispatcher。

所以准确表述是：

```text
timer 巡检：按 org -> agent 扫
任务推进：按 scheduled / queued 状态查
```

## 13. scheduler、dispatcher、inbox 的职责边界

这三个概念不能混用。

| 概念 | 职责 | 不做什么 |
| --- | --- | --- |
| scheduler | 周期性恢复、scheduled materialize、queued dispatch 兜底、timer 巡检 | 不作为 issue 业务规则判断中心 |
| dispatcher | 把 queued run claim 成 running，并启动 runtime | 不决定哪个 issue 业务上该执行 |
| inbox | 展示 agent 相关待办事项 | 不是执行队列，不是调度入口 |

`inbox` 查的是待办视图，例如：

```text
assignee_agent_id = 当前 agent 且 status in todo/in_progress/blocked
reviewer_agent_id = 当前 agent 且 status in in_review/blocked
相关 comment wakeup
```

它不能替代 queued run。

常规任务执行不应该是：

```text
scheduler 到点唤醒 agent
agent 查 inbox
agent 自己决定执行哪个任务
```

更合理的是：

```text
server 侧 issue 事件创建 queued run
dispatcher 启动对应 agent run
agent 执行明确的 issue context
```

## 14. Agent 级手动运行和 issue 级执行的区别

Agent 页面上的手动运行不是任务执行入口。

| 操作 | 有没有 issue context | 业务含义 | cwd |
| --- | --- | --- | --- |
| Run heartbeat / 运行诊断 | 默认没有 | 手动启动一次 agent runtime，用于诊断/健康检查 | heartbeat sandbox workspace |
| issue execute / 执行任务 | 有 | 执行具体 issue | issue workspace |
| assignment wakeup | 有 | 被分配任务后执行 | issue workspace |
| review wakeup | 有 | 执行评审 | issue workspace |
| closeout followup | 有 | 针对具体 issue 做收口补偿 | issue workspace |

所以 UI 不应该同时暴露“唤醒”和“运行诊断”两个 agent 级按钮。建议只保留一个：

```text
运行诊断
```

说明：

```text
启动一次无任务 agent run，用于验证 runtime、provider、control-plane 和 agent 配置是否正常；不会执行具体 issue。
```

## 15. scheduler 巡检唤醒的定位

scheduler 巡检唤醒不是任务主链路。

它可以保留为：

- 低频兜底。
- runtime 健康检查。
- 开发/诊断入口。
- 兼容尚未事件化的边缘检查。

但不应该依赖它完成普通任务调度。

如果所有任务来源都能事件化为 queued run，那么 timer 巡检可以弱化，甚至默认关闭。至少它的 UI 文案应该从“心跳”改为更清楚的“定时巡检”。
