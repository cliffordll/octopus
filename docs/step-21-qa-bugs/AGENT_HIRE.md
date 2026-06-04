# Step 21E: Agent Hire 流程补强

本文档记录 Step 21 中新增的非 Bug 补强任务：支持上游式雇佣智能体流程。该任务不写入 `BUGS.md`，因为它不是缺陷登记，而是已确认的 agent 管理能力缺口。

## 背景

当前 server 已支持普通 agent 创建：

```text
POST /api/orgs/{orgId}/agents
```

但普通创建会直接生成可用 agent，无法表达“新智能体进入组织需要审批”的治理语义。上游式雇佣流程应使用独立入口：

```text
POST /api/orgs/{orgId}/agent-hires
```

该入口根据 organization 的 `requireBoardApprovalForNewAgents` 决定直接创建，还是创建待审批 agent 和 `hire_agent` approval。

## 产品语义

雇佣智能体不是“先创建一个 agent 再审批”。它本身就是创建 agent 的 canonical flow：

```text
提交 hire request
-> server 创建 agent
-> 若组织要求审批，agent 处于 pending_approval
-> 同时创建 hire_agent approval
-> board 批准后 agent 变为可运行状态
```

普通创建适合本地调试或 board 直接管理；雇佣流程适合组织治理、CEO 请求扩充团队、从 issue 派生新角色等场景。

发起者允许两类：

- `board` actor：组织控制台或本地 `local-board`。
- 同组织内 `permissions.canCreateAgents=true` 的 `agent` actor。默认 CEO role 拥有该权限，普通 engineer 等角色默认没有。

审批者仍是 board。CEO agent 发起 hire request 后，如果组织要求审批，server 只创建 `pending_approval` agent 和 `hire_agent` approval；最终是否激活由 board 审批决定。

## 契约目标

新增 API：

```text
POST /api/orgs/{orgId}/agent-hires
```

请求 payload 复用 create agent 的核心字段，并允许携带来源 issue：

```json
{
  "name": "code-reviewer",
  "role": "engineer",
  "title": "代码审查智能体",
  "reportsTo": "agent-ceo-id",
  "capabilities": ["review python server code"],
  "agentRuntimeType": "opencode_local",
  "agentRuntimeConfig": {
    "model": "provider/model"
  },
  "budgetMonthlyCents": 1000,
  "desiredSkills": ["skills/control-plane"],
  "sourceIssueId": "issue-id",
  "sourceIssueIds": ["issue-id"]
}
```

响应：

```json
{
  "agent": {},
  "approval": null
}
```

或：

```json
{
  "agent": {},
  "approval": {}
}
```

## 状态流转

组织不要求审批：

```text
agent-hires
-> create agent
-> status = idle/default runnable status
-> approval = null
```

组织要求审批：

```text
agent-hires by board or canCreateAgents agent
-> create agent
-> status = pending_approval
-> create approval type = hire_agent
-> approval.payload 包含 agentId、hire payload、sourceIssueIds
-> approval.requestedByAgentId 记录发起 hire 的 agent，或 requestedByUserId 记录 board
```

审批通过：

```text
hire_agent approval approved
-> linked agent pending_approval -> idle
-> 记录 agent.hire_approved / approval.approved activity
```

审批拒绝：

```text
hire_agent approval rejected
-> linked agent 保持不可运行或 terminated
-> 记录 agent.hire_rejected / approval.rejected activity
```

## 与已有能力的关系

- Step 6 已有 `requireBoardApprovalForNewAgents` organization 配置。
- Step 9 已有 `hire_agent` approval 类型和审批决策流程。
- Step 11 已有 agent 创建、`pending_approval` 状态和 heartbeat 阻断。
- Step 21E 负责把这些能力串成 canonical hire flow。
- CEO agent 发起 hire 时只代表请求创建，不代表自动批准；模拟 board 可在本地通过 approval API 执行审批。

## 非目标

- 不实现真实 cost 统计、预算消耗归集或 budget hard-stop；这些归 Step 22/23。
- 不实现真实认证和细粒度授权；开发 actor 仍沿用当前 Step 5/24 边界。
- 不允许任意同组织 agent 创建智能体；必须具备 `canCreateAgents=true`。
- 不把手动 `POST /api/orgs/{orgId}/approvals` 当作雇佣流程替代品。
- 不要求 UI/CLI 在本任务中同步实现；server 先提供稳定契约。

## 验收

- `POST /api/orgs/{orgId}/agent-hires` 在组织不要求审批时返回可用 agent，且不创建 approval。
- `POST /api/orgs/{orgId}/agent-hires` 在组织要求审批时返回 `pending_approval` agent 和 `hire_agent` approval。
- 同组织 CEO agent 可以发起 hire request，审批记录 `requestedByAgentId`。
- 无 `canCreateAgents` 权限的普通 agent 调用 hire request 返回 `403`。
- `pending_approval` agent 不能被 heartbeat/run 执行。
- 批准 hire approval 后 linked agent 变为可运行状态。
- 拒绝 hire approval 后 linked agent 不可运行。
- activity 能追踪 hire request、approval 创建、approval 决策和 agent 状态变化。
