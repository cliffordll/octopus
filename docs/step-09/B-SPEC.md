# Step 9 Approval Management Design Spec

**Author:** implementation owner
**Date:** 2026-05-26
**Status:** Draft for review

## 1. Motivation

Step 6 已经冻结了 approval 的首批读能力，Step 7 固定了 organization 的 update 边界，Step 8 固定了 issue 的状态流转和 activity 语义。Step 9 需要在这个基础上把 `approval management` 补到可独立演示、可驱动 issue 恢复和后续主对象审批链路的完整审批管理面。

Step 9 的目标不是提前做 chat 或资源装配，而是先把 approval 作为控制面上的决策对象收稳：能创建、批准、拒绝、请求修改、重新提交，并且能在 response 中稳定呈现 payload 脱敏、decision note 和关联 issue 的恢复语义。

## 2. Contract Sources

1. `docs/step-09/A-CONSTRAINTS.md`
2. `docs/FEATURE.md` Step 9
3. `docs/step-06/READ-API.md`
4. `docs/step-07/A-CONSTRAINTS.md`
5. `docs/step-08/A-CONSTRAINTS.md`
6. `docs/DESIGN.md`
7. upstream approval / resolve workflow reference

当 source 1 和其他来源冲突时，以 source 1 为准；如果 source 1 仍留空，只允许从 Step 6 / Step 7 / Step 8 已经存在的语义继续增量补齐，不允许独立发明新的 approval status、activity action、issue 恢复规则。

## 3. Scope

### In Scope

- approval list / detail 延续 Step 6
- approval create
- approval approve / reject
- request revision / resubmit
- payload 脱敏
- decision note / decidedAt / decidedByUserId
- approval 与 issue 的第一批关联行为
- blocked issue 在审批后的恢复规则
- approval activity / audit 最小记录义务

### Out of Scope

- chat / messages / convert-to-issue
- attachment / artifact / storage adapters
- plugin / skill / registry
- project / goal / agent 主对象管理
- runtime / workspace / heartbeat run

## 4. Step 9 需求拆分

Step 9 按八个子需求块拆开，每块都可以独立验证：

### 4.1 Approval Base CRUD

目标：

- 在 Step 6 的 list / detail 基线上补齐 create
- 保持 approval 作为独立资源，不把写入混进 issue 或 org route

至少要稳定：

- `GET /api/orgs/{orgId}/approvals`
- `GET /api/approvals/{id}`
- `POST /api/orgs/{orgId}/approvals`

第一批关注点：

- payload / response 继续复用 shared contract
- 创建默认状态必须是 `pending`
- 不支持的字段必须拒绝，不允许静默丢弃

### 4.2 Approval Resolution

目标：

- 把 approve / reject / request revision / resubmit 固定为集中 workflow

至少要稳定：

- `POST /api/approvals/{id}/approve`
- `POST /api/approvals/{id}/reject`
- request revision 入口
- resubmit 入口

第一批关注点：

- board 身份是 approve / reject / request revision 的固定前置条件
- requester 为 agent 时，resubmit 只允许 requester 自己执行
- 非法状态下的决策动作必须稳定拒绝

### 4.3 Approval Status Workflow

目标：

- 固定 approval 第一批状态机，不允许边实现边改名

冻结状态值：

- `pending`
- `revision_requested`
- `approved`
- `rejected`

第一批关注点：

- create 默认 `pending`
- approve / reject / revision / resubmit 的状态推进必须集中处理
- 非法流转要有稳定拒绝语义

### 4.4 Payload Redaction And Decision Note

目标：

- 固定 approval payload 在 detail/read 场景下的脱敏与备注语义

第一批关注点：

- payload 脱敏 helper 继续复用集中实现
- decision note 是 resolve payload 的固定一部分
- decidedAt / decidedByUserId 只在有决策后出现

### 4.5 Linked Issue Recovery

目标：

- 固定 approval 决策对关联 blocked issue 的影响

冻结规则：

- approve 后关联 blocked issue：
  - 有 assignee 时恢复到 `in_progress`
  - 无 assignee 时恢复到 `todo`

第一批关注点：

- issue 恢复和 approval 状态更新必须在同一事务边界内完成
- 必须记录对应 activity

### 4.6 Activity / Audit

目标：

- approval 主链路里的关键动作都要留下稳定记录位

Step 9 最少要覆盖：

- `approval.created`
- `approval.approved`
- `approval.rejected`
- `approval.revision_requested`
- `approval.resubmitted`
- `issue.approval_linked`

保留但本步只要求最小语义：

- `approval.linked_issue_assignee_wakeup_queued`
- `approval.linked_issue_assignee_wakeup_failed`
- `approval.requester_wakeup_queued`
- `approval.requester_wakeup_failed`

### 4.7 Error Semantics

目标：

- 让 route / service / workflow 的关键错误分支可测试、可演示

第一批关注点：

- validator failure
- resource missing
- foreign ownership
- expired ownership
- 缺失 board 身份
- 非法状态转换

### 4.8 Testing And Demo

目标：

- Step 9 完成后必须能独立演示，不依赖 Step 10 以后对象先落地

最小验收：

- approval 创建、批准、拒绝可演示
- payload 脱敏与 decision note 可演示
- issue 恢复和关键 activity 可演示
- workflow / contract tests 能覆盖关键错误分支

## 5. Dependency On Step 8

Step 9 明确依赖 Step 8 已经成立的几件事：

- issue status / activity 语义已稳定
- issue blocked / in_progress / todo 状态可复用
- request-scoped transaction 边界已可复用
- activity_log 已有最小可用写入路径

Step 9 不再重新设计这些基础能力，只在 approval 主线上消费并驱动 issue。

## 6. Implementation Shape

虽然本文件不是计划文档，但先锁定实现轮廓，避免后面 plan 发散：

- route 层：`server/routes/approvals.py`
- dependency 层：ownership / board access / session 继续复用现有边界
- service 层：approval create / resolve / resubmit workflow 入口
- query 层：approval create / update / issue-link 查询补齐
- shared 层：只在存在 contract 缺口时补 validator / types
- tests：contract tests + workflow tests

## 7. Open Points To Confirm In Plan

这些问题可以进入 `C-PLAN.md` 再拆，不阻塞 Step 9 需求拆分：

- request revision / resubmit 的精确 route 形状
- approval 和 issue 的关联是只给 issueIds 还是内联 summary
- wakeup queued / failed 是否本步只验证 activity 记录
- request revision 和 reject 是否共用 resolve payload

## 8. Proposed Execution Order

后续写 `C-PLAN.md` 时，建议按这个顺序：

1. 先补 shared contract / validator 缺口
2. 再补 approval query / linked-issue query
3. 再补 service 层 workflow
4. 再补 route
5. 最后补 contract / workflow tests
