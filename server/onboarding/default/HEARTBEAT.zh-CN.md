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
- 如果 `RUDDER_WAKE_REASON=issue_passive_followup`，先检查当前 issue 状态，然后留下关闭信号：进展评论、done、带原因的 blocked，或明确交接。如果被审查的 issue 被阻塞，评论要清楚到足以让 reviewer 判断下一步。
- 如果你是 reviewer，包括处理 `blocked` issue，也要用 `control-plane issue review --decision approve|request_changes|needs_followup|blocked --comment ...` 记录结构化审查结论。只在确认存在人工或外部阻塞时使用 `blocked`，并在评论中说明下一个人工动作。
- 如果 `RUDDER_WAKE_REASON=issue_review_closeout_missing`，检查当前状态，并且只记录一个结构化审查结论。

## 6. 退出

- 退出前对 in_progress 工作发表评论。
- reviewer 工作不能通过自由格式的接受或拒绝评论关闭；使用 `control-plane issue review`。
- 一个成功的 `todo` 或 `in_progress` issue run 如果没有关闭信号，可能触发同一智能体的 passive follow-up。
- 如果没有分配任务，干净退出。
