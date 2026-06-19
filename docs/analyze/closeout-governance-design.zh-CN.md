# Close-Out Governance 整体设计

## 目标

当一次 issue run 已经 `succeeded`，但 issue 仍然没有明确业务收尾时，Octopus 应该先认出当前 run 里有没有已经发出的显式 close-out。只要 control-plane 已经发出 `issue done` / `issue block` / `issue comment` 之一，就应立刻把该 run 视为完成 close-out，并停止后续 `issue_passive_followup`。

核心语义保持不变：

```text
run succeeded != issue done
```

runtime 成功结束只说明 agent 进程正常退出，不代表任务已经完成。issue 是否完成，仍然必须由明确 close-out 动作表达。

## 当前问题

当前 Octopus 的问题不是“完全不会收尾”，而是缺少一个足够早、足够硬的判定层：

```text
issue run succeeded
issue 仍然是 todo / in_progress
run 没有留下可识别 close-out signal
  -> queue issue_passive_followup
```

这在无人值守自动化里是合理的，但在本地用户工作流里会显得过于主动，尤其当 control-plane 已经在当前 run 内写了评论、done 或 block 时，继续补跑 passive follow-up 就是多余的。

## 上游 Rudder 参考结论

参考的上游文件：

```text
D:\coding\rudder\server\src\services\runtime-kernel\heartbeat.recovery.ts
D:\coding\rudder\server\src\services\runtime-kernel\heartbeat.release.ts
D:\coding\rudder\server\src\services\runtime-kernel\heartbeat.core.ts
D:\coding\rudder\packages\agent-runtime-utils\src\server-utils.prompts.ts
D:\coding\rudder\server\src\__tests__\heartbeat-passive-issue-closeout.test.ts
D:\coding\rudder\server\src\__tests__\issue-lifecycle-routes.test.ts
```

上游关键规则：

- 只有当前 run 内产生的 action 才算 run-attributed close-out。
- agent 判断工作完成时，应在 run 内显式调用 `issue done` 或 `issue block`，或者留下进展评论。
- reviewer 必须记录结构化 review decision，普通评论不算 reviewer close-out。
- `issue_passive_followup` 只是在缺少显式 close-out 时的兜底，不是主路径。
- 上游同样对 follow-up 有 cooldown 和 timer continuity 约束，但它们是抑制噪音的补充，不是对显式 close-out 的替代。

## 选定方案

本次采用的规则是：

```text
control-plane issue comment / done / block
  -> 只要是当前 run 内发出的明确动作，就立刻算作 close-out 完成
  -> 立即停止后续 passive follow-up

reviewer run
  -> 仍然只认结构化 review decision
  -> 普通评论不算 reviewer close-out

run succeeded 但没有任何明确 close-out
  -> 继续沿用现有 issue_passive_followup 兜底
```

这里不引入额外的 `closeout_pending` 中间态，也不再用“评论是否足够像收尾”做文本推断。

## 核心概念

| 概念 | 含义 |
| --- | --- |
| agent close-out | assignee agent 在当前 run 内产生的收尾动作。 |
| reviewer close-out | reviewer 记录的结构化评审结论。 |
| passive follow-up | 自动创建的同 agent run，`wakeReason = issue_passive_followup`。 |

## Close-Out 信号

close-out 必须是明确动作，不能从进程成功退出推断。

| 信号 | 是否算 agent/reviewer close-out | 是否停止后续 follow-up | 说明 |
| --- | --- | --- | --- |
| control-plane 在当前 run 内写评论 | 是 | 是 | 需要带当前 `run_id`，作为进展或交接信号。 |
| control-plane 在当前 run 内调用 `issue done` | 是 | 是 | 无 reviewer 时的主要完成路径。 |
| control-plane 在当前 run 内调用 `issue block` | 是 | 是 | 应说明阻塞原因。 |
| issue 被正常送入 `in_review` | 是 | 是 | 这是交付给 reviewer 的明确动作。 |
| reviewer 记录结构化 review decision | 是 | 是 | 只能是结构化 decision。 |
| 用户普通评论 | 否 | 否 | 用户输入本身不等于 agent close-out。 |
| 用户 mention 评论 | 否 | 否 | 仍按现有评论唤醒规则处理。 |

最重要的边界是：

```text
用户评论 != agent close-out
control-plane 显式 close-out == agent close-out
```

## 本次不做的事

- 不新增 `closeout_pending` 表。
- 不新增 closeout-state API。
- 不把“评论是否足够像收尾”做成兜底判定。
- 不把用户评论当成 agent close-out。

## 对实现的含义

如果后续要改代码，重点会在：

- heartbeat 完成时的 close-out 信号识别
- `activity_log.run_id` 归属校验
- reviewer 结构化决策的保留与分流
- `issue_passive_followup` 的现有兜底路径和 cooldown 约束

## 结论

Octopus 应该像上游一样，把显式 close-out 当成第一优先级：

1. 当前 run 里已经发出 `issue done` / `issue block` / `issue comment` 时，立刻结束 close-out。
2. reviewer 继续只认结构化 decision。
3. 只有当前 run 没有留下任何明确 close-out 时，才保留 `issue_passive_followup`。

