# Step 9 A Constraints

## 1. 目标

Step 9 的目标是把 `approval management` 从 Step 6 的首批读取与基础写入能力推进到可连续开发的完整审批管理模块，确保：

- approval 的读写与决策边界独立成立，不混入 chat / storage / plugin 等后续主线
- approve / reject / request revision / resubmit 的语义、权限和副作用可以被测试明确验证
- payload 脱敏、decision note、关联 issue 恢复规则和 activity action 名称可以稳定复用
- Step 10 及后续主对象管理、执行链路都能在稳定 approval 语义上继续推进

这一步只做八件事：

- 固定第一批 approval management 接口范围
- 固定 approval response / payload 的最小字段边界
- 固定 approval 第一批状态值与决策动作语义
- 固定 board 身份守卫与 requester 相关边界
- 固定 blocked issue 在审批后的恢复规则
- 固定 approval activity / audit action 名称和最小记录义务
- 固定 payload 脱敏与 decision note 语义
- 固定 contract / workflow tests 的最小覆盖口径

## 2. 本步输入

Step 9 只能基于以下输入推进：

- [docs/DESIGN.md](D:/coding/octopus/docs/DESIGN.md)
- [docs/FEATURE.md](D:/coding/octopus/docs/FEATURE.md)
- [docs/step-03/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-03/A-CONSTRAINTS.md)
- [docs/step-03/SHARED-CONTRACT.md](D:/coding/octopus/docs/step-03/SHARED-CONTRACT.md)
- [docs/step-04/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-04/A-CONSTRAINTS.md)
- [docs/step-04/SCHEMA-COMPATIBILITY.md](D:/coding/octopus/docs/step-04/SCHEMA-COMPATIBILITY.md)
- [docs/step-04/DATABASE-MAPPING.md](D:/coding/octopus/docs/step-04/DATABASE-MAPPING.md)
- [docs/step-05/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-05/A-CONSTRAINTS.md)
- [docs/step-05/OWNERSHIP.md](D:/coding/octopus/docs/step-05/OWNERSHIP.md)
- [docs/step-06/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-06/A-CONSTRAINTS.md)
- [docs/step-06/READ-API.md](D:/coding/octopus/docs/step-06/READ-API.md)
- [docs/step-07/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-07/A-CONSTRAINTS.md)
- [docs/step-08/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-08/A-CONSTRAINTS.md)

输入关系必须明确：

- `9.1 organizations` 继续直接继承 Step 7 已冻结的 ownership / board access / organization detail 语义
- `9.2 issues` 继续直接继承 Step 8 已冻结的 issue status、activity 和 reopen/恢复相关语义
- `9.3 routes` 继续复用 Step 3 已冻结的 approval path 常量
- `9.4 payload / response` 继续以 Step 3 approval shared types / validators 为准；缺口只能在 shared 层增量补齐
- `9.5 writes` 不能绕过 Step 4 database query / session 边界自行发明新链路

## 3. 本步范围

本步只覆盖 `approval management`：

- `GET /api/orgs/{orgId}/approvals`
- `GET /api/approvals/{id}`
- `POST /api/orgs/{orgId}/approvals`
- `POST /api/approvals/{id}/approve`
- `POST /api/approvals/{id}/reject`
- request revision / resubmit 相关 workflow
- payload 脱敏与 decision note
- approval 与 `issue / organization / agent` 的第一批关联行为

本步至少要稳定以下能力：

- approval 列表和详情在 Step 6 基线上继续成立
- approval 创建
- approval 批准 / 拒绝 / request revision / resubmit
- payload 脱敏
- decision note 与决策时间字段
- blocked issue 在审批动作后的恢复规则
- approval activity action 名称兼容

本步不做：

- chat / messages / convert-to-issue
- attachment / artifact / storage adapters
- plugin / skill / registry
- project / goal / agent 主对象管理
- runtime / workspace / heartbeat run

## 4. 输出要求

Step 9 完成后，至少要交付：

- approval route 更新
- approval create / resolve service 入口
- approval workflow state transition 入口
- approval 查询层对 create / resolve / link 行为的补齐
- payload 脱敏和 decision note 的固定调用链
- 至少一条 approval create/approve/reject/revision/resubmit 的真实 workflow
- 至少一组 response / payload assertion tests，明确字段、状态和错误语义
- 至少一组 approval module demo，能展示 list / detail / create / approve / reject / revision

## 5. Route Scope 约束

### 5.1 已冻结的边界

- Step 9 只围绕 `approvals`
- 所有 path 常量必须复用 Step 3 已冻结的 approval 路径常量
- `GET /api/orgs/{orgId}/approvals` 和 `GET /api/approvals/{id}` 继续保留 Step 6 读能力
- `POST /api/orgs/{orgId}/approvals`、`POST /api/approvals/{id}/approve`、`POST /api/approvals/{id}/reject` 是本步允许新增的 mutation surface
- request revision / resubmit 可作为同一步 workflow 入口补齐
- 本步不新增 chat / storage / plugin route

### 5.2 实现必须落的最小文件边界

`server/routes/` 下至少继续由：

- `approvals.py`

承载本步接口。

命名可以微调，但职责不能漂：

- approval route 仍按资源边界独立维护
- route 只做参数接线、validator 接线、dependency 接线和 response 返回
- 不把 approval workflow 混进 issue / org route

## 6. Payload / Response 约束

### 6.1 已冻结的边界

- approval response shape 继续以 Step 3 / Step 6 已冻结 shared contract 为准
- 新增 mutation payload 必须先走 shared validator；shared contract 缺口只能在 shared 层增量补齐
- route / service 不得返回 ORM 模型对象
- 数据库字段保持 snake_case，response 层继续输出 shared contract 的 camelCase

### 6.2 第一批状态与决策冻结范围

approval 第一批状态值只允许：

- `pending`
- `revision_requested`
- `approved`
- `rejected`

approval 创建默认状态固定为：

- `pending`

approve / reject / request revision 的最小权限边界固定为：

- 只有 board 身份允许执行

### 6.3 blocked issue 恢复规则

approve 后，如果 approval 关联 blocked issue，则恢复规则固定为：

- 有 assignee 时恢复到 `in_progress`
- 无 assignee 时恢复到 `todo`

requester 为 agent 时：

- resubmit 只允许 requester 自己执行

## 7. Activity / Audit 约束

Step 9 至少保留以下 approval activity action 名称：

- `approval.created`
- `approval.approved`
- `approval.rejected`
- `approval.revision_requested`
- `approval.resubmitted`
- `approval.comment_added`
- `issue.approval_linked`
- `approval.linked_issue_assignee_wakeup_queued`
- `approval.linked_issue_assignee_wakeup_failed`
- `approval.requester_wakeup_queued`
- `approval.requester_wakeup_failed`

第一批最小记录义务：

- approval create / approve / reject / request revision / resubmit 成功后，必须有一条可追踪的 activity / audit 记录位
- 记录至少能关联：
  - `org_id`
  - `approval_id`
  - 动作名称
  - 变更时间
- 不得删除或改写上述 action 名称

## 8. 分层硬约束

Step 9 必须满足以下硬约束：

- `server/routes` 不直接查询数据库
- `server/services` 不直接创建 session
- `packages/database/queries` 不承载 HTTP response shape
- ownership 与 board access 必须在 route / dependency 边界显式接入
- query 只负责读取与更新，不负责 HTTP 403 / 404 / 409 / 422 语义
- shared types / validators 仍是 payload / response shape 唯一来源
- activity / audit 记录不得直接写在 route 中
- approval management 不混入 chat / storage / plugin / runtime 逻辑

## 9. 实现边界

- approval workflow 相关实现时，不得：
  - 修改上述 approval 状态值命名
  - 改写 blocked issue 恢复规则
  - 删除上述 approval activity action 名称
  - 删除 board 身份守卫条件
- payload 脱敏必须继续通过集中 helper/mapper 完成，不允许 route 内散落实现
- issue 恢复与 requester wakeup 相关行为本步先冻结最小语义，不扩展成完整消息系统

## 10. 验收 demo

- Demo 1：演示 approval 创建、批准、拒绝
- Demo 2：演示 payload 处理与 decision note
- Demo 3：演示审批相关副作用与错误分支
- Demo 4：展示 workflow 测试结果

## 11. 当前不冻结

- chat / messages / convert-to-issue
- attachment / artifact / storage
- skill / plugin / registry
- 大量历史消息恢复策略
- observability / failover / compatibility diff
