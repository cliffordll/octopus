---
name: control-plane
description: 通过 `control-plane` CLI 与控制平面交互，在 heartbeat 中管理任务、审批、评论、问题文档和组织技能。仅用于控制平面协作，不用于直接完成业务领域工作。
---

# 控制平面技能

你运行在 **heartbeat** 中：这是由控制平面触发的短执行窗口。每次被唤醒时，需要检查分配给自己的工作，完成一个明确且有价值的小步骤，清楚汇报，然后退出。

该技能优先使用 CLI：

- 控制平面操作使用 `control-plane ... --json`。
- 需要发现可用命令时，使用 `control-plane agent capabilities --json`。
- 稳定命令目录参考 `references/cli-reference.md`。
- `references/api-reference.md` 仅作为内部调试或兼容参考，不是常规 agent 接口。
- 只有当 CLI 命令返回非零并给出诊断错误，或 runtime/打包问题导致 CLI 返回 0 但 stdout 为空时，才允许降级到 API，并需要在 issue 评论或 run notes 中记录原因。
- 如果远程 runtime 唤醒文本明确写明 **HTTP compatibility mode**，则本次运行按唤醒文本执行；否则使用 CLI。

## 认证

控制平面会注入 runtime context。常见环境变量包括：

- `OCTOPUS_AGENT_ID`
- `OCTOPUS_ORG_ID`
- `OCTOPUS_API_URL`
- `OCTOPUS_API_KEY`
- `OCTOPUS_RUN_ID`

可选唤醒上下文变量包括：

- `OCTOPUS_TASK_ID`
- `OCTOPUS_WAKE_REASON`
- `OCTOPUS_WAKE_COMMENT_ID`
- `OCTOPUS_APPROVAL_ID`
- `OCTOPUS_APPROVAL_STATUS`
- `OCTOPUS_LINKED_ISSUE_IDS`

规则：

- 不要在正常 heartbeat 中向用户索要 `OCTOPUS_API_KEY`。
- 不要硬编码 API URL。
- 优先读取注入的上下文并使用 CLI 完成控制平面协作。

## Close-out gate（关闭门禁）

退出活跃 issue heartbeat 前，必须先让匹配的 `control-plane` close-out 命令成功执行。最终 assistant 总结不是关闭信号。先执行 CLI 命令，确认命令成功，再退出。

如果 `OCTOPUS_WAKE_REASON=issue_passive_followup`：

- 这次运行只用于补齐上一次成功运行缺失的 close-out 信号，不要先开始新的实现任务。
- 检查 issue 当前状态后，必须执行且只需执行以下一种命令：
  - `control-plane issue done "<issue-id-or-identifier>" --comment "<markdown>" --json`
  - `control-plane issue block "<issue-id-or-identifier>" --comment "<markdown>" --json`
  - `control-plane issue comment "<issue-id-or-identifier>" --body "<markdown>" --json`
- 不要只用最终回复说明“已完成”“需要跟进”或“稍后处理”。在上面任一命令成功前，Do not exit。

如果 `OCTOPUS_WAKE_REASON=issue_review_closeout_missing`：

- 这次运行只用于补齐 reviewer run 缺失的评审结论，不要把它当成新的执行任务。
- 必须执行一次 `control-plane issue review "<issue-id-or-identifier>" --decision approve|request_changes|needs_followup|blocked --comment "<markdown>" --json`。
- 不要用 `control-plane issue comment` 代替 reviewer 结论。在 `control-plane issue review` 成功前，Do not exit。

## 适用场景

- 查看当前 agent 身份、组织、任务和能力。
- 更新 issue 文档、添加评论、记录 run notes。
- 查询或处理审批。
- 管理组织技能。
- 在 heartbeat 中与控制平面保持状态同步。

## 不适用场景

- 不要用该技能替代实际业务开发、代码修改或领域任务执行。
- 不要绕过 CLI 手动写控制平面数据。
- 不要在认证缺失时伪造上下文。
