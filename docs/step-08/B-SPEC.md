# Step 8 Issue Management Design Spec

**Author:** A side planning
**Date:** 2026-05-26
**Status:** Draft for review

## 1. Motivation

Step 6 只冻结了 issue / approval / organization 的首批读取能力。Step 7 又把 organization management 的写语义和 activity 记录收紧了。Step 8 需要在这个基础上把 `issue management` 补到可独立演示、可继续承接 approval / project / goal / agent 关系的完整任务管理面。

Step 8 的目标不是提前做执行链路，而是先把 issue 作为控制面主对象收稳：能创建、更新、评论、流转、被 review decision 驱动，并且能在 response 中读取到与 project / goal / agent / origin 的第一批关系。

## 2. Contract Sources

1. `docs/step-08/A-CONSTRAINTS.md`
2. `docs/FEATURE.md` Step 8
3. `docs/step-06/READ-API.md`
4. `docs/step-07/B-SPEC.md`
5. `docs/DESIGN.md`
6. upstream issue / comment / review workflow reference

当 source 1 和其他来源冲突时，以 source 1 为准；如果 source 1 仍留空，只允许从 Step 6 / Step 7 已经存在的语义继续增量补齐，不允许独立发明新的 status、decision、action 名称。

## 3. Scope

### In Scope

- issue list / detail 延续 Step 6 并补充常见过滤能力
- issue create
- issue update
- issue comments list / create
- issue status 第一批流转
- reviewer decision 到 issue status 的最小映射
- issue reopen 语义
- issue activity / audit 最小记录义务
- issue 与 `project / goal / agent / origin` 的第一批关联读取

### Out of Scope

- approval 批准 / 拒绝主链路
- project / goal / agent 主对象管理
- runtime / heartbeat_run / workspace
- issue checkout / release / commit 的完整执行链路
- attachment / artifact 存储
- chat session / message 细节

## 4. Step 8 需求拆分

Step 8 按九个子需求块拆开，每块都可以独立验证：

### 4.1 Issue Base CRUD

目标：

- 在 Step 6 的 list / detail 基线上补齐 create 和 update
- 保持 issue 作为独立资源，不把写入混进 approval 或 org route

至少要稳定：

- `GET /api/issues`
- `GET /api/issues/{issueId}`
- `POST /api/issues`
- `PATCH /api/issues/{issueId}`

第一批关注点：

- payload / response 继续复用 shared contract
- update 允许 partial patch
- 不支持的字段必须拒绝，不允许静默丢弃
- 资源不存在、ownership 失败、validator 失败的错误语义要固定

### 4.2 Issue Comments

目标：

- 把 comment 从“数据库里有结构”推进到真实可读可写的任务讨论面

至少要稳定：

- issue comments list
- issue comment create

第一批关注点：

- comment 必须绑定到已有 issue
- comment 创建成功后要有 activity / audit 记录位
- comment response 必须带最小作者和时间字段

### 4.3 Issue Status Workflow

目标：

- 固定 issue 第一批状态机，不允许在 Step 8 里边实现边改名

冻结状态值：

- `todo`
- `in_progress`
- `in_review`
- `blocked`
- `done`

第一批关注点：

- update 触发的 status change 必须在 service / workflow 层集中处理
- 非法状态值和非法流转必须有稳定拒绝语义
- 状态流转成功后必须有 activity 记录位

### 4.4 Review Decision Mapping

目标：

- 把 reviewer decision 对 issue 的影响收成固定兼容行为

固定映射：

- `approve` -> `done`
- `request_changes` -> `in_progress`
- `blocked` -> `blocked`
- `needs_followup` -> 不直接改 issue status

第一批关注点：

- reviewer decision 只允许在 `in_review` / `blocked` 两个前置状态下发生
- review decision 写入和 status 更新的事务边界要一致
- decision 被记录后必须有 `issue.review_decision_recorded`

### 4.5 Reopen Semantics

目标：

- 固定关闭后 issue 再打开的最小兼容语义

冻结行为：

- 已关闭 issue 在 update 时如果显式要求 reopen，且未显式指定新 `status`
- 默认重新打开到 `todo`

第一批关注点：

- reopen 是 update 语义的一部分，不单独再发明第二套 route
- reopen 后 activity / audit 要能区分是 update 带来的 reopen

### 4.6 Associations

目标：

- 先补 issue 对其他控制面对象的只读关联，不提前冻结对方主对象管理语义

第一批关联范围：

- `project`
- `goal`
- `agent`
- `origin`

第一批关注点：

- 只要求在 issue list / detail response 中能稳定读取这些关联
- 不要求本步完成 project / goal / agent 的完整详情 shape
- association 缺失时的空值语义要稳定

### 4.7 Filtering

目标：

- 让 issue list 至少具备常用过滤能力，支撑独立演示和 workflow 测试

建议第一批过滤项：

- `status`
- `projectId`
- `goalId`
- `agentId`
- `origin`

第一批关注点：

- 过滤能力必须可测试验证
- 本步不引入复杂搜索 DSL

### 4.8 Activity / Audit

目标：

- issue 主链路里的关键动作都要留下稳定记录位

Step 8 最少要覆盖：

- `issue.created`
- `issue.updated`
- `issue.comment_added`
- `issue.review_decision_recorded`
- `issue.human_intervention_required`

保留但不要求本步完整实现：

- `issue.deleted`
- `issue.checked_out`
- `issue.released`
- `issue.code_committed`

### 4.9 Testing And Demo

目标：

- Step 8 完成后必须能独立演示，不依赖 Step 9 以后的对象先落地

最小验收：

- issue 创建、更新、流转可演示
- issue comment 写入与读取可演示
- issue 与 project / goal / agent / origin 的关联读取可演示
- workflow / contract tests 能覆盖关键错误分支

## 5. Dependency On Step 7

Step 8 明确依赖 Step 7 已经成立的几件事：

- organization detail 读写语义已稳定
- ownership rejection 语义已稳定
- board access 语义已稳定
- request-scoped transaction 边界已经可复用
- activity_log 已经有最小可用写入路径

Step 8 不再重新设计这些基础能力，只在 issue 主线上继续消费。

## 6. Implementation Shape

虽然本文件不是计划文档，但先锁定实现轮廓，避免后面 plan 发散：

- route 层：`server/routes/issues.py`
- dependency 层：ownership / actor / session 继续复用现有边界
- service 层：issue create / update / comment / workflow 入口
- query 层：issue / issue_comment / association / filtering 查询补齐
- shared 层：只在存在 contract 缺口时补 validator / types
- tests：contract tests + workflow tests

## 7. Open Points To Confirm In Plan

这些问题可以进入 `C-PLAN.md` 再拆，不阻塞 Step 8 需求拆分：

- issue create 和 update 的第一批字段白名单
- comment payload 的最小 shape
- review decision 是走 issue route 子入口还是 workflow service 入口
- list filters 的精确 query 参数命名
- association response 是内联 summary 还是只给 id

## 8. Proposed Execution Order

后续写 `C-PLAN.md` 时，建议按这个顺序：

1. 先补 shared contract / validator 缺口
2. 再补 issue query / comment query / filtering query
3. 再补 service 层 workflow
4. 再补 route
5. 最后补 contract / workflow tests
