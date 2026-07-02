# Step 13 Scheduler 开发文档

这份文档给开发者用。目标不是解释概念，而是规定改代码时怎么落地。

一句话规则：

```text
新增任何“让 agent 跑起来”的能力，都必须先判断它是哪种 wakeup source。
不要用 timer heartbeat 代替 assignment/review/automation。
```

## 1. 改代码先看这张表

| 你要做的事 | 应该用 | 不应该用 |
| --- | --- | --- |
| issue 分配后执行 | `source=assignment` | timer heartbeat |
| 用户点击执行 issue | `source=assignment` 或 `on_demand`，但 run purpose 是 task execution | 直接调用 adapter |
| issue 进入评审 | `source=review` | assignment |
| 自动收口 follow-up | `source=automation` | timer heartbeat |
| 用户提前触发自动收口 | materialize existing `automation` scheduled wakeup | 新建无关联 run |
| 周期巡检 | `source=timer` | assignment/review |
| 恢复 queued run | dispatcher claim queued run | 重新创建重复 wakeup |

## 2. 关键文件

| 文件 | 改什么 |
| --- | --- |
| `server/services/heartbeat.py` | wakeup、run 创建、dispatch、execute、closeout governance |
| `server/lifespan.py` | server scheduler tick 的启动和循环 |
| `server/services/issue_assignment_wakeup.py` | issue assignee 精确唤醒 |
| `server/services/issue_review_wakeup.py` | reviewer 精确唤醒 |
| `server/routes/issues.py` | issue execute、manual passive follow-up、comment/status 入口 |
| `packages/database/queries/heartbeat.py` | wakeup/run 查询、claim、scheduled materialize |
| `packages/database/schema/agent_state.py` | `agent_wakeup_requests` |
| `packages/database/schema/heartbeat.py` | `heartbeat_runs` / `heartbeat_run_events` |
| `packages/shared/constants/heartbeat.py` | source、status、run purpose 常量 |
| `ui/src/pages/IssuePage.tsx` | closeout/follow-up/run 展示 |

## 3. Wakeup 创建规则

所有 issue 相关 wakeup 都必须有：

```text
org_id
agent_id
source
reason
payload.issueId
contextSnapshot.issueId
contextSnapshot.wakeReason
idempotencyKey
```

推荐字段语义：

| 字段 | 约定 |
| --- | --- |
| `source` | `assignment` / `review` / `automation` / `on_demand` / `timer` |
| `reason` | 业务原因，例如 `issue_execute`、`issue_review_requested`、`issue_passive_followup` |
| `runPurpose` | `task_execution` / `review` / `closeout_followup` / `heartbeat` |
| `idempotencyKey` | 同一个业务事件不能创建重复 run |
| `requestedAt` | 立即执行用 now；延迟执行用未来时间 |

## 4. 各场景实现规则

### 4.1 issue 执行

入口：

- issue 被分配给 agent；
- issue 状态进入可执行；
- 用户点击执行。

实现：

```text
create assignment wakeup
  -> create queued run(runPurpose=task_execution)
  -> after commit dispatch_queued_agent(agentId)
```

禁止：

```text
等待 300 秒 timer heartbeat 再让 agent 自己找任务。
```

### 4.2 review

入口：

- issue 进入 `in_review`；
- reviewer 被设置或变更；
- assignee done 后需要 reviewer。

实现：

```text
create review wakeup
  -> create queued run(runPurpose=review)
  -> dispatch reviewer agent
```

review closeout 只认 reviewer run 产生的结构化 decision activity。

### 4.3 自动收口

入口：

- task run 成功；
- 当前 run 没有产生 closeout signal。

实现规则：

```text
attempt 未用尽:
  run.status = succeeded
  run.errorCode = null
  create scheduled automation wakeup(reason=issue_passive_followup)

attempt 用尽:
  run.status = failed
  run.errorCode = closeout_missing
  write issue.closure_needs_operator_review
```

人工提前触发：

```text
POST /api/issues/{issueId}/passive-followup
  -> 优先找到已有 scheduled automation wakeup
  -> 立即 materialize 成 queued run
  -> dispatch
```

不要新建一条和原 follow-up 无关的孤立 run。

### 4.4 timer heartbeat

只在“周期职责 agent”场景使用。

必须同时满足：

```text
runtimeConfig.heartbeat.enabled = true
runtimeConfig.heartbeat.intervalSec > 0
agent 到期
preflight 通过
```

建议 preflight：

| 条件 | 结果 |
| --- | --- |
| 已有 due pending wakeup | skip，避免重复 |
| 有明确周期维护任务 | allow |
| 没有 actionable work | skip |

## 5. Scheduler tick 规则

scheduler tick 只能做基础设施推进：

```text
recover_orphaned_runs()
materialize_due_scheduled_wakeups()
dispatch_all_queued_runs()
tick_timer_heartbeats()
```

要求：

- 不直接调用 runtime adapter。
- 不直接修改 issue 状态。
- 不绕过 wakeup/run 表。
- 不把 timer heartbeat 当成任务执行兜底。
- 后台 task 必须自己创建 session，不能复用 request-scoped session。
- session 必须在 success/error/cancelled 路径全部 close/rollback。

## 6. Dispatcher 规则

dispatcher 的责任：

```text
1. 找到 agent 的 queued run。
2. 原子 claim: queued -> running。
3. 启动 execute_claimed_run(runId)。
4. 写 run event / stdout / stderr / final status。
5. 释放 issue execution lock。
6. 继续 dispatch 同 agent 或相关 reviewer 的下一条 queued run。
```

claim 必须是条件更新，避免重复执行：

```sql
UPDATE heartbeat_runs
SET status = 'running'
WHERE id = :run_id
  AND status = 'queued'
```

如果没有更新到行，说明 run 已被其他 worker 领取，当前 dispatcher 必须退出。

## 7. Closeout governance 规则

closeout signal 必须来自当前 run 产生的 activity：

| agent 动作 | 可接受 activity |
| --- | --- |
| issue comment | `issue.comment_added` |
| issue done | `issue.status_changed`，目标状态为 done/in_review |
| issue block | `issue.status_changed`，目标状态为 blocked |
| review decision | `issue.review_decision_recorded` |

必须匹配：

```text
activity_log.entity_type = issue
activity_log.entity_id = issue.id
activity_log.run_id = 当前 heartbeat_run.id
```

不要用 issue 上已有的旧 comment/status 判断当前 run 已 closeout。

## 8. UI 展示规则

run 列表和 issue 页面至少应区分：

```text
invocationSource
runPurpose
wakeReason
status
errorCode
```

展示语义：

| 状态 | UI 应该表达 |
| --- | --- |
| scheduled automation follow-up 未到期 | 已安排自动收尾，不是错误 |
| follow-up 可提前触发 | 显示“立即收尾跟进” |
| follow-up 尝试用尽 | 需要人工确认收口 |
| timer heartbeat disabled | 定时心跳关闭，不代表任务执行关闭 |

## 9. 测试清单

修改 scheduler/wakeup/dispatcher/closeout 时，至少补或跑这些测试：

- assignment wakeup 创建 queued task run。
- review wakeup 创建 queued review run。
- scheduled automation wakeup 未到期不执行。
- passive-followup endpoint 可以提前触发 scheduled wakeup。
- closeout attempt 未用尽前 run 仍是 succeeded。
- closeout attempt 用尽后才是 failed/`closeout_missing`。
- timer heartbeat 在 `intervalSec=0` 时不创建 timer run。
- timer preflight 无 actionable work 时 skip。
- dispatcher 并发 claim 不重复执行同一 run。
- dispatcher 异常/取消时不泄漏 SQLAlchemy AsyncSession。

当前相关命令：

```powershell
uv run pytest tests/contract/test_step11_agent_management.py -k "passive_followup or closeout"
uv run pytest tests/contract/test_database_session_cleanup.py tests/contract/test_step11_agent_management.py -k "dispatch or scheduler or passive_followup or closeout"
uv run ruff check server/services/heartbeat.py tests/contract/test_step11_agent_management.py
uv run pyright server/services/heartbeat.py
```

## 10. 调试入口

查某个 issue 的 wakeup：

```sql
select id, source, reason, status, requested_at, run_id, payload
from agent_wakeup_requests
where payload like '%<issue-id>%'
order by created_at;
```

查某个 issue 的 run：

```sql
select id, invocation_source, run_purpose, status, error_code, created_at, started_at, finished_at
from heartbeat_runs
where context_snapshot like '%<issue-id>%'
order by created_at;
```

查 closeout activity：

```sql
select action, run_id, details, created_at
from activity_log
where entity_type = 'issue'
  and entity_id = '<issue-id>'
order by created_at;
```

## 11. 开发完成的验收口径

交付前必须能回答：

1. 这个 run 是哪个 source 触发的？
2. 它对应哪个 agent、哪个 issue、哪个 reason？
3. 是否需要等 timer heartbeat？如果需要，为什么？
4. 如果 scheduler 停掉再启动，queued/scheduled/running run 怎么恢复？
5. 如果 closeout 缺失，什么时候是等待，什么时候才是错误？
6. 这个后台路径是否保证 AsyncSession close/rollback？

回答不清楚时，不要继续堆代码；先补 wakeup/run 语义。
