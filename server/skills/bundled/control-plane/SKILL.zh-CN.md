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

- `CONTROL_PLANE_AGENT_ID`
- `CONTROL_PLANE_ORG_ID`
- `CONTROL_PLANE_API_URL`
- `CONTROL_PLANE_API_KEY`
- `CONTROL_PLANE_RUN_ID`

可选唤醒上下文变量包括：

- `CONTROL_PLANE_TASK_ID`
- `CONTROL_PLANE_WAKE_REASON`
- `CONTROL_PLANE_WAKE_COMMENT_ID`
- `CONTROL_PLANE_APPROVAL_ID`
- `CONTROL_PLANE_APPROVAL_STATUS`
- `CONTROL_PLANE_LINKED_ISSUE_IDS`

规则：

- 不要在正常 heartbeat 中向用户索要 `CONTROL_PLANE_API_KEY`。
- 不要硬编码 API URL。
- 优先读取注入的上下文并使用 CLI 完成控制平面协作。

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
