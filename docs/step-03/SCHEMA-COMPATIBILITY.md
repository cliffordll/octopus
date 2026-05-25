# Octopus Schema Compatibility

## 1. 文档目标

本文档用于盘点 Octopus 第一阶段需要对齐的 上游参考实现 数据库表与关键字段。

当前版本只覆盖第一批范围：

- organizations
- issues
- approvals
- issue_comments
- issue_approvals
- activity_log

## 2. 契约来源

- 上游 schema 源码：`上游参考仓库路径\packages\db\src\schema`
- 当前对照文件：
  - `organizations.ts`
  - `issues.ts`
  - `approvals.ts`
  - `issue_comments.ts`
  - `issue_approvals.ts`
  - `activity_log.ts`

## 3. 总体规则

- 上游参考实现 业务表结构视为固定边界
- Octopus 不借重写机会修改业务表名、字段名、状态语义
- 新增表只允许基础设施表，例如 ownership lease、idempotency、outbox
- 第一阶段优先盘点支撑 org / issue / approval 最小闭环的表

## 3.1 第一批共享默认值与状态来源

共享默认值来源：

- `organizations.status` 默认 `active`
- `issues.status` 默认 `backlog`
- `issues.priority` 默认 `medium`
- `issues.origin_kind` 默认 `manual`
- `approvals.status` 默认 `pending`

共享状态来源：

- `ORGANIZATION_STATUSES = ["active", "paused", "archived"]`
- `ISSUE_STATUSES = ["backlog", "todo", "in_progress", "in_review", "done", "blocked", "cancelled"]`
- `ISSUE_PRIORITIES = ["critical", "high", "medium", "low"]`
- `ISSUE_ORIGIN_KINDS = ["manual", "automation_execution"]`
- `APPROVAL_STATUSES = ["pending", "revision_requested", "approved", "rejected", "cancelled"]`

## 4. 第一批核心表

### 4.1 `organizations`

主要角色：

- organization 根对象
- issue、approval、activity 等业务对象的上层归属

关键字段：

- `id`
- `url_key`
- `name`
- `description`
- `status`
- `pause_reason`
- `paused_at`
- `issue_prefix`
- `issue_counter`
- `budget_monthly_cents`
- `spent_monthly_cents`
- `default_chat_issue_creation_mode`
- `workspace_config`
- `brand_color`
- `created_at`
- `updated_at`

字段 nullability / 默认值：

- `id` 非空，默认随机 UUID
- `url_key` 非空
- `name` 非空
- `description` 可空
- `status` 非空，默认 `active`
- `pause_reason` 可空
- `paused_at` 可空
- `issue_prefix` 非空，默认 `PAP`
- `issue_counter` 非空，默认 `0`
- `budget_monthly_cents` 非空，默认 `0`
- `spent_monthly_cents` 非空，默认 `0`
- `require_board_approval_for_new_agents` 非空，默认 `true`
- `default_chat_issue_creation_mode` 非空，默认 `manual_approval`
- `workspace_config` 可空
- `brand_color` 可空
- `created_at` 非空，默认 now
- `updated_at` 非空，默认 now

关键约束：

- `organizations_issue_prefix_idx`
- `organizations_url_key_idx`

第一阶段关注点：

- organization 唯一标识和 URL key 语义
- status 与 pause 相关字段语义
- issue 编号相关字段语义

字段到响应映射重点：

- `url_key -> urlKey`
- `pause_reason -> pauseReason`
- `paused_at -> pausedAt`
- `issue_prefix -> issuePrefix`
- `issue_counter -> issueCounter`
- `budget_monthly_cents -> budgetMonthlyCents`
- `spent_monthly_cents -> spentMonthlyCents`
- `require_board_approval_for_new_agents -> requireBoardApprovalForNewAgents`
- `default_chat_issue_creation_mode -> defaultChatIssueCreationMode`
- `brand_color -> brandColor`
- `created_at -> createdAt`
- `updated_at -> updatedAt`

附加说明：

- `Organization` 响应里还存在 `workspace`、`logoAssetId`、`logoUrl`，这些不直接来自当前 `organizations` 单表字段
- 第一阶段只要求记住这类字段属于聚合字段，不要求此时把组装逻辑盘尽

### 4.2 `issues`

主要角色：

- 核心控制面对象
- 承载 issue 生命周期、分配、执行、来源和工作流状态

关键字段：

- `id`
- `org_id`
- `project_id`
- `goal_id`
- `parent_id`
- `title`
- `description`
- `status`
- `priority`
- `board_order`
- `assignee_agent_id`
- `assignee_user_id`
- `reviewer_agent_id`
- `reviewer_user_id`
- `checkout_run_id`
- `execution_run_id`
- `created_by_agent_id`
- `created_by_user_id`
- `issue_number`
- `identifier`
- `origin_kind`
- `origin_id`
- `origin_run_id`
- `request_depth`
- `started_at`
- `completed_at`
- `cancelled_at`
- `hidden_at`
- `created_at`
- `updated_at`

字段 nullability / 默认值：

- `id` 非空，默认随机 UUID
- `org_id` 非空，外键到 `organizations.id`
- `project_id` 可空
- `project_workspace_id` 可空
- `goal_id` 可空
- `parent_id` 可空，自引用
- `title` 非空
- `description` 可空
- `status` 非空，默认 `backlog`
- `priority` 非空，默认 `medium`
- `board_order` 非空，默认 `0`
- `assignee_agent_id` 可空
- `assignee_user_id` 可空
- `reviewer_agent_id` 可空
- `reviewer_user_id` 可空
- `checkout_run_id` 可空
- `execution_run_id` 可空
- `execution_agent_name_key` 可空
- `execution_locked_at` 可空
- `created_by_agent_id` 可空
- `created_by_user_id` 可空
- `issue_number` 可空
- `identifier` 可空，但存在唯一索引
- `origin_kind` 非空，默认 `manual`
- `origin_id` 可空
- `origin_run_id` 可空
- `request_depth` 非空，默认 `0`
- `billing_code` 可空
- `assignee_agent_runtime_overrides` 可空
- `execution_workspace_id` 可空
- `execution_workspace_preference` 可空
- `execution_workspace_settings` 可空
- `started_at` 可空
- `completed_at` 可空
- `cancelled_at` 可空
- `hidden_at` 可空
- `created_at` 非空，默认 now
- `updated_at` 非空，默认 now

关键外键：

- `org_id -> organizations.id`
- `project_id -> projects.id`
- `goal_id -> goals.id`
- `parent_id -> issues.id`
- `assignee_agent_id -> agents.id`
- `reviewer_agent_id -> agents.id`
- `checkout_run_id -> heartbeat_runs.id`
- `execution_run_id -> heartbeat_runs.id`

关键索引与约束：

- `issues_company_status_idx`
- `issues_company_status_board_order_idx`
- `issues_identifier_idx`
- `issues_open_automation_execution_uq`

第一阶段关注点：

- `org_id` 是第一层隔离边界
- `status`、`priority`、`board_order` 决定列表与流转语义
- `identifier`、`issue_number` 影响前端和业务引用
- assignee / reviewer / run 相关字段影响 workflow

字段到响应映射重点：

- `org_id -> orgId`
- `project_id -> projectId`
- `project_workspace_id -> projectWorkspaceId`
- `goal_id -> goalId`
- `parent_id -> parentId`
- `board_order -> boardOrder`
- `assignee_agent_id -> assigneeAgentId`
- `assignee_user_id -> assigneeUserId`
- `reviewer_agent_id -> reviewerAgentId`
- `reviewer_user_id -> reviewerUserId`
- `checkout_run_id -> checkoutRunId`
- `execution_run_id -> executionRunId`
- `execution_agent_name_key -> executionAgentNameKey`
- `execution_locked_at -> executionLockedAt`
- `created_by_agent_id -> createdByAgentId`
- `created_by_user_id -> createdByUserId`
- `issue_number -> issueNumber`
- `origin_kind -> originKind`
- `origin_id -> originId`
- `origin_run_id -> originRunId`
- `request_depth -> requestDepth`
- `billing_code -> billingCode`
- `assignee_agent_runtime_overrides -> assigneeAgentRuntimeOverrides`
- `execution_workspace_id -> executionWorkspaceId`
- `execution_workspace_preference -> executionWorkspacePreference`
- `execution_workspace_settings -> executionWorkspaceSettings`
- `started_at -> startedAt`
- `completed_at -> completedAt`
- `cancelled_at -> cancelledAt`
- `hidden_at -> hiddenAt`
- `created_at -> createdAt`
- `updated_at -> updatedAt`

附加说明：

- `Issue` 响应中的 `ancestors`、`labels`、`project`、`goal`、`currentExecutionWorkspace`、`workProducts`、`mentionedProjects`、document 相关字段不直接来自 `issues` 单表
- 第一阶段只要求区分“单表字段”和“聚合字段”，不要求此时把所有详情聚合结构拆到底

### 4.3 `approvals`

主要角色：

- 审批工作流根对象
- 承载审批类型、请求者、决策结果与 payload

关键字段：

- `id`
- `org_id`
- `type`
- `requested_by_agent_id`
- `requested_by_user_id`
- `status`
- `payload`
- `decision_note`
- `decided_by_user_id`
- `decided_at`
- `created_at`
- `updated_at`

字段 nullability / 默认值：

- `id` 非空，默认随机 UUID
- `org_id` 非空，外键到 `organizations.id`
- `type` 非空
- `requested_by_agent_id` 可空
- `requested_by_user_id` 可空
- `status` 非空，默认 `pending`
- `payload` 非空
- `decision_note` 可空
- `decided_by_user_id` 可空
- `decided_at` 可空
- `created_at` 非空，默认 now
- `updated_at` 非空，默认 now

关键索引与约束：

- `approvals_company_status_type_idx`

第一阶段关注点：

- `status` 的流转语义
- `payload` 结构是审批类型行为的核心输入
- request / decision 字段影响审计和副作用

字段到响应映射重点：

- `org_id -> orgId`
- `requested_by_agent_id -> requestedByAgentId`
- `requested_by_user_id -> requestedByUserId`
- `decision_note -> decisionNote`
- `decided_by_user_id -> decidedByUserId`
- `decided_at -> decidedAt`
- `created_at -> createdAt`
- `updated_at -> updatedAt`

附加说明：

- approval 响应的 `payload` 在 route 层返回前会做 redact
- 第一阶段只要求记住这条行为约束，具体 redact 细节可在 approval 实现前再补

## 5. 第一批关联表

### 5.1 `issue_comments`

主要角色：

- issue 评论流

关键字段：

- `id`
- `org_id`
- `issue_id`
- `author_agent_id`
- `author_user_id`
- `body`
- `created_at`
- `updated_at`

字段 nullability / 默认值：

- `id` 非空，默认随机 UUID
- `org_id` 非空
- `issue_id` 非空
- `author_agent_id` 可空
- `author_user_id` 可空
- `body` 非空
- `created_at` 非空，默认 now
- `updated_at` 非空，默认 now

第一阶段关注点：

- comment 与 issue 的 organization 一致性
- author 字段在 activity 与审计中的语义

字段到响应映射重点：

- `org_id -> orgId`
- `issue_id -> issueId`
- `author_agent_id -> authorAgentId`
- `author_user_id -> authorUserId`
- `created_at -> createdAt`
- `updated_at -> updatedAt`

### 5.2 `issue_approvals`

主要角色：

- issue 与 approval 的关联表

关键字段：

- `org_id`
- `issue_id`
- `approval_id`
- `linked_by_agent_id`
- `linked_by_user_id`
- `created_at`

字段 nullability / 默认值：

- `org_id` 非空
- `issue_id` 非空
- `approval_id` 非空
- `linked_by_agent_id` 可空
- `linked_by_user_id` 可空
- `created_at` 非空，默认 now

关键约束：

- 复合主键：`issue_approvals_pk`

第一阶段关注点：

- issue / approval 关联关系
- 级联删除语义

字段到响应映射重点：

- `org_id -> orgId`
- `issue_id -> issueId`
- `approval_id -> approvalId`
- `linked_by_agent_id -> linkedByAgentId`
- `linked_by_user_id -> linkedByUserId`
- `created_at -> createdAt`

附加说明：

- 在 `IssueLinkedApproval` 这类响应里，关联表字段通常表现为嵌套 `link` 对象
- 第一阶段先记录这种结构特征，不要求此时把所有关联响应细节盘尽

### 5.3 `activity_log`

主要角色：

- 核心审计与可见性日志

关键字段：

- `id`
- `org_id`
- `actor_type`
- `actor_id`
- `action`
- `entity_type`
- `entity_id`
- `agent_id`
- `run_id`
- `details`
- `created_at`

字段 nullability / 默认值：

- `id` 非空，默认随机 UUID
- `org_id` 非空
- `actor_type` 非空，默认 `system`
- `actor_id` 非空
- `action` 非空
- `entity_type` 非空
- `entity_id` 非空
- `agent_id` 可空
- `run_id` 可空
- `details` 可空
- `created_at` 非空，默认 now

第一阶段关注点：

- action / entity_type / entity_id 的记录语义
- issue / approval 关键副作用是否需要稳定写入 activity

字段到响应映射重点：

- `org_id -> orgId`
- `actor_type -> actorType`
- `actor_id -> actorId`
- `entity_type -> entityType`
- `entity_id -> entityId`
- `run_id -> runId`
- `created_at -> createdAt`

## 6. 第一阶段建议映射顺序

建议按以下顺序建立 Python 映射：

1. `organizations`
2. `issues`
3. `approvals`
4. `issue_approvals`
5. `issue_comments`
6. `activity_log`

原因：

- 先建根对象
- 再建核心 workflow 对象
- 最后补评论、关联和审计

## 7. A 线下一步盘点清单

下一步需要继续补齐：

- 在 B 实现 read API 时，按实际需要补聚合字段明细
- 在进入 mutation workflow 前，补 activity_log 的 action 清单与副作用触发点
- 在扩展 read / mutation 范围时，再补更多关联表

## 8. 当前结论

第一阶段不需要一次映射 上游参考实现 的所有表。

A 线当前应该先把：

- 第一批核心表
- 第一批关联表
- 关键字段
- 关键索引和约束

固定下来，给 B 线提供清晰的 database 边界和映射优先级。

