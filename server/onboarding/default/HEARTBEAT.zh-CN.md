# HEARTBEAT.md -- 智能体心跳检查清单（中文阅读版）

每次 heartbeat 都执行这份检查清单。

## 1. 身份与上下文

- 确认你的 id、role、budget、chainOfCommand。
- 检查唤醒上下文中的任务触发信息。

## 2. 本地计划检查

1. 从 memory 读取今天的计划。
2. 检查计划项：已完成、被阻塞、即将进行。
3. 解决阻塞或升级处理。
4. 记录进展更新。

## 3. 审批跟进

如果存在审批上下文，检查关联 issue，并关闭或评论。

## 4. 获取收件箱工作

- 检查 `control-plane agent inbox --json`，同时查看 assignee 和 reviewer 行。
- 优先处理 reviewer 的 `in_review` 或 `blocked` 行，其次处理 assignee 的 `in_progress`，再处理 assignee 的 `todo`。

## 5. Checkout 并工作

- 工作前始终先 checkout。
- 执行工作。完成后更新状态并评论。
- 对委派型子任务，不要把委派型子任务分配给自己；如果你会在父任务 run 内完成这部分工作，就不要为它创建子任务。父任务必须等待这些子任务实际运行并回报结果后，才能汇总。不要在父任务 run 中直接完成已委派的子任务内容，然后把这些子任务标记为 `blocked` 或 `cancelled` 当作“不需要执行”。`blocked` 只用于真实阻塞，例如信息缺失、权限不可用、依赖失败，或需要人工/外部动作。
- Close-out gate：退出活跃 issue heartbeat 前，必须先让匹配的控制平面 close-out 命令成功执行。
- 如果 `OCTOPUS_WAKE_REASON=issue_passive_followup`，先检查当前 issue 状态，然后在退出前只执行一个 close-out 命令：`control-plane issue done ...`、`control-plane issue block ...` 或 `control-plane issue comment ...`。如果被审查的 issue 被阻塞，评论要清楚到足以让 reviewer 判断下一步。不要只用最终 assistant 总结结束这次唤醒。
- 如果你是 reviewer，包括处理 `blocked` issue，也要用 `control-plane issue review --decision approve|request_changes|needs_followup|blocked --comment ...` 记录结构化审查结论。只在确认存在人工或外部阻塞时使用 `blocked`，并在评论中说明下一个人工动作。
- 如果 `OCTOPUS_WAKE_REASON=issue_review_closeout_missing`，检查当前状态，并且在退出前执行一个 `control-plane issue review ... --json` 命令。不要用自由格式评论代替 reviewer 结论。

## 6. 退出

- 退出前对 in_progress 工作发表评论。
- reviewer 工作不能通过自由格式的接受或拒绝评论关闭；使用 `control-plane issue review`。
- 一个成功的 `todo` 或 `in_progress` issue run 如果没有关闭信号，可能触发同一智能体的 passive follow-up。
- 不要退出 `issue_passive_followup`，除非 `control-plane issue done`、`control-plane issue block` 或 `control-plane issue comment` 已成功。
- 不要退出 `issue_review_closeout_missing`，除非 `control-plane issue review` 已成功。
- 如果没有分配任务，干净退出。
