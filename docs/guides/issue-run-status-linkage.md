# Issue status and run status linkage

本文说明 Octopus 中“任务阶段”和“任务运行状态”的边界、联动规则、UI 控制，以及排查时应该看哪些字段。

相关背景文档：

- `docs/guides/task-execution-lifecycle.md`
- `docs/guides/task-invocation-modes.md`
- `docs/guides/task-queue.md`

## Concepts

### Issue status

Issue status 是任务本身的业务阶段，回答“这个任务现在应该怎么处理”。

当前常见值：

| Status | 中文含义 | 说明 |
| --- | --- | --- |
| `backlog` | 待规划 | 任务还没有进入可执行队列。 |
| `todo` | 待执行 | 任务可执行，但尚未开始。 |
| `in_progress` | 进行中 | 任务正在处理，或等待下一次执行/补充。 |
| `in_review` | 评审中 | 已产出结果，等待 reviewer 给出结构化结论。 |
| `blocked` | 阻塞 | 需要人工、外部依赖或明确后续动作。 |
| `done` | 完成 | 任务业务上已完成。 |
| `cancelled` | 取消 | 任务业务上取消。 |

Issue status 存在于 `issues.status`，影响 issue board、agent inbox、review 操作、执行按钮和筛选。

### Run status

Run status 是一次 runtime 执行记录的状态，回答“这一次 agent/run 跑到哪了”。

当前常见值：

| Status | 中文含义 | 说明 |
| --- | --- | --- |
| `queued` | 排队中 | run 已创建，等待 claim 或并发槽位。 |
| `running` | 运行中 | runtime adapter 正在执行。 |
| `succeeded` | 成功 | 本次执行成功结束。 |
| `failed` | 失败 | 本次执行失败。 |
| `timed_out` | 超时 | 本次执行超时。 |
| `cancelled` | 取消 | 本次执行被取消。 |

Run status 存在于 `heartbeat_runs.status`。一个 issue 可以有多次 run，因此 issue status 不能简单等同于 latest run status。

## Core rule

任务阶段和运行状态不能强同步。

- Run status 是执行事实。
- Issue status 是业务判断。

因此联动应该是“受控推进”，不是“run 结束后直接覆盖 issue status”。

例如：

| Issue status | Latest run status | 含义 |
| --- | --- | --- |
| `in_progress` | `running` | 当前任务正在执行。 |
| `in_progress` | `failed` | 任务仍在处理中，但最近一次执行失败，可以重新执行。 |
| `in_review` | `succeeded` | 执行已成功产出，等待 reviewer 评审。 |
| `blocked` | `failed` / `succeeded` / none | 阻塞是业务判断，不一定等于运行失败。 |
| `done` | `succeeded` | 任务业务上已完成，通常最近一次执行成功。 |

## Current linkage rules

### Execution starts

当 assignment run claim 到 issue execution lock 时：

- 如果 issue status 是 `backlog` 或 `todo`，自动推进到 `in_progress`。
- 写入 `issues.checkout_run_id` 和 `issues.execution_run_id`。
- 写入 `issues.execution_agent_name_key` 和 `issues.execution_locked_at`。
- 如果 `started_at` 为空，补 `started_at`。

这发生在 `server/services/heartbeat.py` 的 issue execution claim 路径。

### Run is live

当 latest run 是 `queued` 或 `running`：

- Issue status 通常保持 `in_progress`。
- UI 上任务阶段下拉禁用，避免运行中人工切阶段造成锁和业务状态不一致。
- 用户应等待 run 结束、取消 run，或查看 run 详情。

### Assignment run succeeds

当 assignment run 成功，并且 issue 仍是 `in_progress`：

| 条件 | 结果 |
| --- | --- |
| issue 有 `reviewer_agent_id` | 自动推进到 `in_review`，并 queue reviewer wakeup。 |
| issue 没有 reviewer | 不自动改成 `done`。保持 `in_progress`，等待 closeout、人工处理或后续规则。 |

自动进入 `in_review` 时会记录 activity：

- `action = "issue.updated"`
- `details.reason = "run_succeeded"`
- `run_id = heartbeat_runs.id`

### Assignment run fails, times out, or is cancelled

当 run 进入 `failed`、`timed_out` 或 `cancelled`：

- 清理 `issues.execution_run_id` / `checkout_run_id` 等 execution lock 字段。
- 不自动把 issue 改成 `blocked`。
- Issue status 通常保持 `in_progress`。
- UI 显示 latest run 失败，并提供重新执行入口。

不自动 `blocked` 的原因：失败可能来自 runtime、Ctrl+C、server restart、模型输出格式、依赖环境等执行层问题，不一定代表任务业务阻塞。

### Review decision

Reviewer 应通过结构化 review decision 推进任务：

| Review decision | Issue status |
| --- | --- |
| `approve` | `done` |
| `request_changes` | `in_progress` |
| `blocked` | `blocked` |
| `needs_followup` | 保持 `in_review`，并记录 human intervention activity。 |

这一路径在 `server/services/issues.py` 中处理。

## UI controls

Issue detail 的任务阶段下拉不是自由状态机入口。它应防止用户绕过运行和评审流程。

当前控制规则：

| 场景 | UI 行为 |
| --- | --- |
| latest run 是 `queued` 或 `running` | 禁用任务阶段下拉。 |
| 想切到 `in_review` 但没有 reviewer | 禁用 `in_review` option。 |
| issue 在 `in_review` 或 `blocked` | 禁用直接切到 `done`、`in_progress`、`todo`；应走 review decision。 |
| issue 是 `done` | 禁用普通阶段跳转；应走 reopen 流程。 |
| issue 是 `cancelled` | 禁用普通阶段跳转；应走 reopen 流程。 |
| reviewer agent 等于 assignee agent | 禁用该 reviewer 选项；server 也会拒绝写入。 |

UI 控制只是防误操作。Server 仍应保留关键业务校验和联动，因为 API/CLI/agent 都可能绕过 UI。

## Re-execution behavior

重新执行时：

- 如果 latest run 是 `queued` 或 `running`，不允许再启动一次同 issue execution。
- 如果 latest run 是 `failed`、`timed_out` 或 `cancelled`，允许重新执行。
- 提交重新执行请求后，UI 会临时隐藏顶部旧的 latest run error，避免用户误以为新执行立刻失败。
- 历史运行记录仍保留旧失败摘要，便于审计和排查。

重新执行不会删除旧 run。每次 run 都是独立历史事实。

## Data fields to inspect

排查 issue/run 联动时，优先看这些字段：

### `issues`

| Field | 用途 |
| --- | --- |
| `status` | 当前任务阶段。 |
| `assignee_agent_id` | 当前执行负责人。 |
| `reviewer_agent_id` | reviewer agent。 |
| `execution_run_id` | 当前持有 execution lock 的 run。 |
| `checkout_run_id` | 当前 checkout run。 |
| `execution_locked_at` | execution lock 获取时间。 |
| `started_at` | 首次进入执行时间。 |
| `completed_at` | 完成时间。 |

### `heartbeat_runs`

| Field | 用途 |
| --- | --- |
| `status` | 单次 run 状态。 |
| `invocation_source` | run 来源，例如 `assignment`、`review`、`timer`、`on_demand`。 |
| `context_snapshot.issueId` | run 关联的 issue。 |
| `context_snapshot.wakeReason` | 唤醒原因。 |
| `error` / `error_code` | 失败原因。 |
| `process_pid` | 本地子进程 pid。 |
| `retry_of_run_id` | recovery/retry 来源。 |

### `agent_wakeup_requests`

| Field | 用途 |
| --- | --- |
| `source` | wakeup 来源。 |
| `reason` | 业务原因。 |
| `status` | wakeup/request 状态。 |
| `run_id` | 创建或关联的 run。 |
| `idempotency_key` | 合并/去重键。 |

### `activity_log`

| Field | 用途 |
| --- | --- |
| `action` | issue 行为，例如 `issue.updated`、`issue.review_decision_recorded`。 |
| `entity_type` / `entity_id` | 关联 issue。 |
| `run_id` | 关联具体 run。 |
| `details.reason` | 自动状态变化原因，例如 `run_succeeded`。 |

## Expected user-facing states

### Run failed, issue still in progress

推荐展示：

```text
任务阶段：进行中
最新运行：失败
操作：重新执行
```

不要展示成：

```text
任务阶段：阻塞
```

除非 reviewer 或用户明确把任务标记为 blocked。

### Run succeeded, reviewer exists

推荐展示：

```text
任务阶段：评审中
最新运行：成功
操作：等待评审结论
```

### Run is live

推荐展示：

```text
任务阶段：进行中
最新运行：运行中
任务阶段选择：禁用
```

## Implementation references

主要实现位置：

- `server/services/heartbeat.py`
  - issue execution lock claim
  - run finalization
  - assignment success to review linkage
  - reviewer wakeup after successful assignment run
- `server/services/issues.py`
  - review decision to issue status mapping
  - issue status side effects
- `ui/src/pages/IssuePage.tsx`
  - latest run display
  - re-execution old error hiding
  - issue status select disabling
- `tests/workflows/test_step13_run_workflow.py`
  - assignment success moves issue to review and wakes reviewer
- `ui/src/test/issue-page.test.tsx`
  - issue status option disabling

## Design cautions

- 不要让 `failed` 自动变成 `blocked`。
- 不要让 `succeeded` 无条件变成 `done`。
- 不要删除旧 run 来“清空错误”；旧 run 是审计事实。
- 不要只在 UI 做状态联动；server 必须维护真实业务状态。
- 不要把 chat assistant invocation 伪装成 heartbeat run。Chat 转 issue 后，issue 执行才进入 heartbeat run 体系。
