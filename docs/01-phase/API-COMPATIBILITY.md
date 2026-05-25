# Octopus API Compatibility

## 1. 文档目标

本文档用于盘点 Octopus 第一阶段需要对齐的 Rudder API 契约。

当前版本只覆盖第一批范围：

- organizations
- issues
- approvals

目标不是一次写完整个 Rudder API 面，而是先固定 A 线需要给 B 线提供的第一批契约边界。

## 2. 契约来源

- Rudder 路由源码：`D:\coding\rudder\server\src\routes`
- 当前对照范围：
  - `orgs.ts`
  - `issues.ts`
  - `issues.mutations.ts`
  - `approvals.ts`

## 3. 总体规则

- Octopus 的接口路径、HTTP method、参数命名、响应结构必须跟 Rudder 保持一致
- 不新增 Octopus 自定义接口命名
- 不新增 `/internal/*` 这类 Rudder 中不存在的新接口名前缀
- 当前阶段优先盘点第一批最小闭环接口，不追求一次覆盖全部路由

## 3.1 第一批共享状态与枚举

当前第一批范围已确认的共享枚举如下，B 线不得自行扩展或改名：

### Organization statuses

- `active`
- `paused`
- `archived`

来源：

- `packages/shared/src/constants.ts`
- `packages/shared/src/validators/organization.ts`

### Issue statuses

- `backlog`
- `todo`
- `in_progress`
- `in_review`
- `done`
- `blocked`
- `cancelled`

默认值：

- create issue 默认 `backlog`

### Issue priorities

- `critical`
- `high`
- `medium`
- `low`

默认值：

- create issue 默认 `medium`

### Issue origin kinds

- `manual`
- `automation_execution`

### Approval types

- `hire_agent`
- `approve_ceo_strategy`
- `budget_override_required`
- `chat_issue_creation`
- `chat_operation`

### Approval statuses

- `pending`
- `revision_requested`
- `approved`
- `rejected`
- `cancelled`

默认值：

- create approval 默认 `pending`

## 4. 第一批接口范围

### 4.1 Organizations

第一批优先接口：

- `GET /api/orgs`
- `GET /api/orgs/:orgId`
- `POST /api/orgs`
- `PATCH /api/orgs/:orgId`

Rudder 路由来源：

- `orgs.ts:75`
- `orgs.ts:107`
- `orgs.ts:553`
- `orgs.ts:584`

当前约束：

- `GET /api/orgs` 作为最小 read API 候选
- `GET /api/orgs/:orgId` 作为单对象读取候选
- `POST /api/orgs`、`PATCH /api/orgs/:orgId` 作为后续 mutation 候选
- 其它 organization 资源、workspace、export/import 相关接口暂不进入第一批实现范围

待盘点内容：

- 请求 query / path 参数
- 响应字段完整结构
- 创建与更新 payload schema
- 错误码与错误消息语义

第一批参数与 payload：

- `GET /api/orgs`
  - 无业务 query 参数
  - 仅 board 可访问
- `GET /api/orgs/:orgId`
  - path: `orgId`
- `POST /api/orgs`
  - 关键 body：
    - `name`
    - `description`
    - `budgetMonthlyCents`
    - `defaultChatIssueCreationMode`
    - `brandColor`
    - `requireBoardApprovalForNewAgents`
- `PATCH /api/orgs/:orgId`
  - board 用户走完整更新
  - agent 用户仅允许 branding 更新子集

当前确认的常见错误语义：

- `GET /api/orgs/:orgId`
  - `404 { error: "Organization not found" }`
- `POST /api/orgs`
  - `403` 非 instance admin 禁止创建
- `PATCH /api/orgs/:orgId`
  - `403` 非 board 或非 CEO agent 禁止更新
  - `404 { error: "Organization not found" }`

当前确认的响应重点：

- organization 响应直接返回 organization 对象
- 不做二次包装
- 第一阶段只要求 B 保持核心字段与 Rudder 一致：
  - `id`
  - `name`
  - `urlKey`
  - `description`
  - `status`
  - `issuePrefix`
  - `issueCounter`
  - `budgetMonthlyCents`
  - `spentMonthlyCents`
  - `defaultChatIssueCreationMode`
  - `brandColor`
  - `createdAt`
  - `updatedAt`
- `workspace`、`logoAssetId`、`logoUrl` 等扩展字段留到实现时按 Rudder 对照补齐

### 4.2 Issues

第一批优先接口：

- `GET /api/issues`
- `GET /api/orgs/:orgId/issues`
- `GET /api/issues/:id`
- `POST /api/orgs/:orgId/issues`
- `PATCH /api/issues/:id`

第二批紧随接口：

- `POST /api/issues/:id/checkout`
- `POST /api/issues/:id/release`
- `POST /api/issues/:id/commit`
- `GET /api/issues/:id/approvals`
- `POST /api/issues/:id/approvals`

Rudder 路由来源：

- `issues.ts:311`
- `issues.ts:317`
- `issues.ts:512`
- `issues.mutations.ts:84`
- `issues.mutations.ts:143`
- `issues.mutations.ts:613`
- `issues.mutations.ts:681`
- `issues.mutations.ts:718`
- `issues.ts:968`
- `issues.ts:980`

当前约束：

- 第一阶段优先做 read surface 和 create / update 基础 mutation
- checkout / release / commit 属于后续 workflow 范围，但接口名必须在设计阶段先固定
- labels、documents、work-products、follow、read-state 等接口暂不进入第一批实现范围

待盘点内容：

- issue 列表接口的 query 参数
- issue 返回字段、状态字段、排序和过滤行为
- create / update payload schema
- checkout / release / commit 的请求与副作用语义

第一批参数与 payload：

- `GET /api/orgs/:orgId/issues`
  - path: `orgId`
  - 第一阶段优先支持的 query：
    - `status`
    - `assigneeAgentId`
    - `assigneeUserId`
    - `reviewerAgentId`
    - `reviewerUserId`
    - `projectId`
    - `parentId`
    - `originKind`
    - `originId`
    - `q`
- `GET /api/issues/:id`
  - path: `id`
  - Rudder 支持把类似 `PAP-39` 的 identifier 解析到内部 UUID
- `POST /api/orgs/:orgId/issues`
  - 关键 body：
    - `title`
    - `description`
    - `status`
    - `priority`
    - `projectId`
    - `goalId`
    - `parentId`
    - `assigneeAgentId`
    - `assigneeUserId`
    - `reviewerAgentId`
    - `reviewerUserId`
    - `requestDepth`
    - `labelIds`
- `PATCH /api/issues/:id`
  - 关键 body：
    - create issue 字段的 partial 版本
    - `comment`
    - `reopen`
    - `hiddenAt`
    - `reviewDecision`

当前确认的常见错误语义：

- `GET /api/issues`
  - `400 { error: "Missing orgId in path. Use /api/orgs/{orgId}/issues." }`
- `GET /api/orgs/:orgId/issues`
  - `403` 当 `assigneeUserId=me`、`reviewerUserId=me`、`touchedByUserId=me`、`unreadForUserId=me` 但缺少 board 身份
- `GET /api/issues/:id`
  - `404 { error: "Issue not found" }`
- `POST /api/orgs/:orgId/issues`
  - `403` 当请求里包含 assignee / reviewer 变更但无 `tasks:assign` 权限
- `PATCH /api/issues/:id`
  - `404 { error: "Issue not found" }`
  - `403 { error: "Only the checked-out assignee or reviewer can complete issue" }`
  - `422` 当 reviewer decision 或 update payload 不合法
- `POST /api/issues/:id/checkout`
  - `404 { error: "Issue not found" }`
  - `409` 当 expected status 与当前状态不匹配
  - `403 { error: "Agent can only checkout as itself" }`
- `POST /api/issues/:id/commit`
  - `403 { error: "Agent authentication required" }`

当前确认的响应重点：

- `GET /api/orgs/:orgId/issues` 返回 issue 列表，不做额外包装
- 第一阶段只要求 B 保持 issue 核心字段一致：
  - `id`
  - `orgId`
  - `projectId`
  - `goalId`
  - `parentId`
  - `title`
  - `description`
  - `status`
  - `priority`
  - `boardOrder`
  - `assigneeAgentId`
  - `assigneeUserId`
  - `reviewerAgentId`
  - `reviewerUserId`
  - `issueNumber`
  - `identifier`
  - `originKind`
  - `originId`
  - `requestDepth`
  - `createdAt`
  - `updatedAt`
- `GET /api/issues/:id` 需要在核心字段基础上支持详情聚合能力，但第一步只要求先保留接口位和核心字段
- `POST /api/orgs/:orgId/issues` 返回 `201` 和新建 issue 对象
- `PATCH /api/issues/:id` 返回更新后的 issue 对象
- `POST /api/issues/:id/commit` 返回 `IssueCommitReport`，第一阶段只需记住它不是直接返回 issue

### 4.3 Approvals

第一批优先接口：

- `GET /api/orgs/:orgId/approvals`
- `GET /api/approvals/:id`
- `POST /api/orgs/:orgId/approvals`
- `POST /api/approvals/:id/approve`
- `POST /api/approvals/:id/reject`

第二批紧随接口：

- `POST /api/approvals/:id/resubmit`
- `GET /api/approvals/:id/comments`
- `POST /api/approvals/:id/comments`
- `GET /api/approvals/:id/issues`

Rudder 路由来源：

- `approvals.ts:218`
- `approvals.ts:226`
- `approvals.ts:237`
- `approvals.ts:318`
- `approvals.ts:557`
- `approvals.ts:607`
- `approvals.ts:645`
- `approvals.ts:657`
- `approvals.ts:306`

当前约束：

- 第一阶段优先支持审批列表、审批详情、创建审批、审批通过、审批拒绝
- comments、issues 关联、resubmit 可作为第二批 approval workflow 扩展

待盘点内容：

- create approval payload
- resolve approval payload
- approval status 字段与决策语义
- approval 与 issue 的关联行为

第一批参数与 payload：

- `GET /api/orgs/:orgId/approvals`
  - path: `orgId`
  - query:
    - `status`
- `GET /api/approvals/:id`
  - path: `id`
- `POST /api/orgs/:orgId/approvals`
  - 关键 body：
    - `type`
    - `requestedByAgentId`
    - `payload`
    - `issueIds`
- `POST /api/approvals/:id/approve`
  - 关键 body：
    - `decisionNote`
    - `decidedByUserId`
    - `payload`
- `POST /api/approvals/:id/reject`
  - 复用 resolve approval payload

当前确认的常见错误语义：

- `GET /api/approvals/:id`
  - `404 { error: "Approval not found" }`
- `POST /api/orgs/:orgId/approvals`
  - `201` 成功创建
- `GET /api/approvals/:id/issues`
  - `404 { error: "Approval not found" }`
- `POST /api/approvals/:id/approve`
  - board 身份必需
  - 若 approval 不存在，返回 `404`
- `POST /api/approvals/:id/reject`
  - 若 approval 不存在，返回 `404`
- `POST /api/approvals/:id/resubmit`
  - `404 { error: "Approval not found" }`
  - `403 { error: "Only requesting agent can resubmit this approval" }`
- `GET /api/approvals/:id/comments`
  - `404 { error: "Approval not found" }`
- `POST /api/approvals/:id/comments`
  - `404 { error: "Approval not found" }`

当前确认的响应重点：

- approval 读取响应会经过 payload redact
- 第一阶段只要求 B 保持 approval 核心字段一致：
  - `id`
  - `orgId`
  - `type`
  - `requestedByAgentId`
  - `requestedByUserId`
  - `status`
  - `payload`
  - `decisionNote`
  - `decidedByUserId`
  - `decidedAt`
  - `createdAt`
  - `updatedAt`
- `GET /api/orgs/:orgId/approvals` 返回 approval 列表
- `GET /api/approvals/:id` 返回单个 approval
- `POST /api/orgs/:orgId/approvals` 返回 `201` 和新建 approval
- `GET /api/approvals/:id/issues`、`GET /api/approvals/:id/comments` 属于第一步记录在案，但不要求在第一步把返回字段穷举到底

## 5. 第一批验收接口

为了给 B 线提供最小可执行范围，第一批建议先以以下接口作为验收目标：

- `GET /api/orgs`
- `GET /api/orgs/:orgId`
- `GET /api/orgs/:orgId/issues`
- `GET /api/issues/:id`
- `POST /api/orgs/:orgId/issues`
- `GET /api/orgs/:orgId/approvals`
- `POST /api/orgs/:orgId/approvals`

这些接口覆盖了：

- organization 读取
- issue 读取
- issue 创建
- approval 读取
- approval 创建

足够支撑第一批 shared contract、database mapping 和 server 骨架协同推进。

## 6. A 线下一步盘点清单

下一步需要继续补齐以下内容：

- 在 B 开始实现后，按实际需要补具体响应字段
- 跟随 B 的 read API 实现补 detail 聚合字段
- 在进入 mutation 阶段前补 checkout / release / approve / reject 的副作用语义
- 在进入 workflow 阶段前补 activity 写入时机和 action 名称

## 7. 当前结论

第一阶段不应试图一次复刻整个 Rudder 路由面。

A 线当前应先做的事情是：

- 固定第一批接口清单
- 固定第一批路径和 method
- 固定第一批 payload / response / status 盘点范围
- 给 B 线提供可直接实现的最小契约面
