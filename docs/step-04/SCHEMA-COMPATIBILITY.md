# Octopus Schema Compatibility

## 1. 文档目标

本文档用于盘点 Step 4 第一批需要对齐的业务表、关键字段和数据库约束，作为 Python 数据库基础层的 schema 输入。

当前版本只覆盖第一批范围：

- organizations
- issues
- approvals
- issue_comments
- issue_approvals
- activity_log

## 2. 本文档在 Step 4 中的作用

本文档不是给整个后续项目平均使用的泛化资料，而是 Step 4 的输入文档。

在 Step 4 中的使用方式固定为：

- `4.1 schema`
  - 直接以本文档为核心输入
  - 用于确定表名、字段名、nullability、默认值、主外键和关键约束
- `4.2 clients`
  - 只弱参考本文档
  - client/session/transaction 入口主要受分层职责约束，不受具体字段盘点驱动
- `4.3 queries`
  - 部分参考本文档
  - 用于判断首批 query 至少需要覆盖哪些表和哪些基础字段

## 3. 契约来源

- 上游 schema 源码：`上游参考仓库路径\packages\db\src\schema`
- 当前对照文件：
  - `organizations.ts`
  - `issues.ts`
  - `approvals.ts`
  - `issue_comments.ts`
  - `issue_approvals.ts`
  - `activity_log.ts`

## 4. 总体规则

- 上游参考实现业务表结构视为固定边界
- Octopus 不借重写机会修改业务表名、字段名、状态语义
- 新增表只允许基础设施表，例如 ownership lease、idempotency、outbox
- Step 4 只优先盘点支撑 org / issue / approval 最小闭环的表

## 4.0.1 同步说明

本文档第一版交付时未列尽每张表的 upstream 索引集合,也未给出字段级 PG 类型规则。Schema 实现按完整 upstream 对照补齐后,在 §4.2 / §4.3 增加类型与行为规则,并把各表「关键索引与约束」列表对齐到 upstream 全集。

执行记录见 `docs/step-04/SCHEMA-UPSTREAM-ALIGN.md`。

## 4.1 第一批共享默认值与状态来源

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

## 4.2 PG 类型映射规则

为消除字段级类型歧义,字段类型按以下规则映射到 PostgreSQL,字段层不再单独标注:

- 所有 UUID 列(`id`、`org_id`、`*_agent_id`、`*_run_id`、`*_workspace_id`、`issue_id`、`approval_id`、`goal_id` 等)使用 PG `uuid` 类型,默认 `defaultRandom()`
- 所有用户标识 ID 列(`*_user_id`、`actor_id`)以及通用字符串内容(`name`、`url_key`、`description`、`status`、`title`、`body`、`action`、`type`、`identifier`、`origin_kind`、`origin_id` 等)使用 PG `text` 类型,**不带长度限制**
- 所有计数与数值列(`*_counter`、`*_cents`、`board_order`、`request_depth`、`issue_number` 等)使用 PG `integer`
- 所有布尔列使用 PG `boolean`
- 所有时间列使用 PG `timestamp(withTimezone: true)`
- 所有 JSON 列(`workspace_config`、`payload`、`*_overrides`、`*_settings`、`details`)使用 PG `jsonb`,不使用 `json`

Python 端(SQLAlchemy)实现细节:

- UUID 列在 Python 端用 `String(36)` 存 UUID 字符串,跨 SQLite/PG 稳定(详见 `docs/step-04/DATABASE-MAPPING.md` §5.2)
- text 列在 Python 端用 `Text()`,不带长度上限,与 PG `text` 等价
- jsonb 列在 Python 端用 `JSON().with_variant(JSONB(), "postgresql")`,SQLite 测试用通用 JSON,PG 部署用 jsonb
- 整数、布尔、时间列直接 SQLAlchemy 原生类型(`Integer`、`Boolean`、`DateTime(timezone=True)`)

## 4.3 updated_at 行为约定

`updated_at` 列在所有表中:

- 数据库 default `now()`(由 `server_default=func.now()` 表达)
- **不**配置 `onupdate` 自动刷新
- 由应用层(service 或 mutation workflow)在更新行时显式设置新时间戳
- 与上游 Drizzle 行为一致(upstream 没有 ORM 级 onupdate)

## 5. 第一批核心表

### 5.1 `organizations`

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

- `organizations_issue_prefix_idx`(**unique**, on `issue_prefix`)
- `organizations_url_key_idx`(**unique**, on `url_key`)

Step 4 关注点：

- organization 唯一标识和 URL key 语义
- status 与 pause 相关字段语义
- issue 编号相关字段语义

### 5.2 `issues`

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

- `issues_company_status_idx`(普通, on `org_id`, `status`)
- `issues_company_status_board_order_idx`(普通, on `org_id`, `status`, `board_order`)
- `issues_company_assignee_status_idx`(普通, on `org_id`, `assignee_agent_id`, `status`)
- `issues_company_assignee_user_status_idx`(普通, on `org_id`, `assignee_user_id`, `status`)
- `issues_company_reviewer_agent_status_idx`(普通, on `org_id`, `reviewer_agent_id`, `status`)
- `issues_company_reviewer_user_status_idx`(普通, on `org_id`, `reviewer_user_id`, `status`)
- `issues_company_parent_idx`(普通, on `org_id`, `parent_id`)
- `issues_company_project_idx`(普通, on `org_id`, `project_id`)
- `issues_company_origin_idx`(普通, on `org_id`, `origin_kind`, `origin_id`)
- `issues_company_project_workspace_idx`(普通, on `org_id`, `project_workspace_id`)
- `issues_company_execution_workspace_idx`(普通, on `org_id`, `execution_workspace_id`)
- `issues_identifier_idx`(**unique**, on `identifier`)
- `issues_open_automation_execution_uq`(**unique 部分索引**, on `org_id`, `origin_kind`, `origin_id`, WHERE `origin_kind = 'automation_execution' and origin_id is not null and hidden_at is null and execution_run_id is not null and status in ('backlog', 'todo', 'in_progress', 'in_review', 'blocked')`)

Step 4 关注点：

- `org_id` 是第一层隔离边界
- `status`、`priority`、`board_order` 决定列表与流转语义
- `identifier`、`issue_number` 影响前端和业务引用
- assignee / reviewer / run 相关字段影响后续 workflow

### 5.3 `approvals`

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

- `approvals_company_status_type_idx`(普通, on `org_id`, `status`, `type`)

Step 4 关注点：

- `status` 的流转语义
- `payload` 结构是审批类型行为的核心输入
- request / decision 字段影响审计和副作用

## 6. 第一批关联表

### 6.1 `issue_comments`

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

关键索引与约束：

- `issue_comments_issue_idx`(普通, on `issue_id`)
- `issue_comments_company_idx`(普通, on `org_id`)
- `issue_comments_company_issue_created_at_idx`(普通, on `org_id`, `issue_id`, `created_at`)
- `issue_comments_company_author_issue_created_at_idx`(普通, on `org_id`, `author_user_id`, `issue_id`, `created_at`)

Step 4 关注点：

- comment 与 issue 的 organization 一致性
- author 字段在 activity 与审计中的语义

### 6.2 `issue_approvals`

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

- 复合主键：`issue_approvals_pk`(`issue_id`, `approval_id`)
- `issue_approvals_issue_idx`(普通, on `issue_id`)
- `issue_approvals_approval_idx`(普通, on `approval_id`)
- `issue_approvals_company_idx`(普通, on `org_id`)
- 外键级联:`issue_id → issues.id` **ON DELETE CASCADE**
- 外键级联:`approval_id → approvals.id` **ON DELETE CASCADE**
- 外键:`linked_by_agent_id → agents.id` ON DELETE SET NULL(`agents` 表不在 Step 4 第一批,FK 暂不在 Python schema 加约束)

Step 4 关注点：

- issue / approval 关联关系
- 级联删除语义

### 6.3 `activity_log`

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

关键索引与约束：

- `activity_log_company_created_idx`(普通, on `org_id`, `created_at`)
- `activity_log_run_id_idx`(普通, on `run_id`)
- `activity_log_entity_type_id_idx`(普通, on `entity_type`, `entity_id`)

Step 4 关注点：

- action / entity_type / entity_id 的记录语义
- issue / approval 关键副作用后续是否需要稳定写入 activity

## 7. Step 4 建议映射顺序

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

## 8. 当前结论

Step 4 不需要一次映射所有表。

A 在这一步已经固定的重点只有：

- 第一批核心表
- 第一批关联表
- 关键字段
- 默认值、主外键和关键约束

B 应该基于这些稳定边界先把 database 基础层搭出来，再把更复杂的聚合和 workflow 需求留给 Step 5 之后继续收紧。
