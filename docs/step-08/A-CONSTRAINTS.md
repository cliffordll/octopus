# Step 8 A Constraints

## 1. 目标

Step 8 的目标是把 `issue management` 从 Step 6 的首批读取能力推进到可直接交给 B 连续开发的完整任务管理模块，确保：

- issue 的读写边界独立成立，不再混入 organization management 或后续 runtime / workspace 主线
- issue comment、状态流转、review decision、副作用时机和常见过滤能力可以被测试明确验证
- Step 8 继续建立在 Step 5 ownership、Step 6 read API、Step 7 organization management 的稳定输出之上
- Step 9 approval management、Step 10 project / goal / agent management 都能以稳定的 issue 语义为前提继续推进

这一步只做九件事：

- 固定第一批 issue management 接口范围
- 固定 issue response / payload 的最小字段边界
- 固定 issue comment 的最小读写语义
- 固定 issue status 第一批状态值与状态流转约束
- 固定 reviewer decision 到 issue status 的映射
- 固定 reopen 语义
- 固定 issue 与 project / goal / agent / origin 的第一批关联读取边界
- 固定 issue activity / audit action 名称和最小记录义务
- 固定 contract / workflow tests 的最小覆盖口径

## 2. 本步输入

Step 8 只能基于以下输入推进：

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
- [docs/step-07/B-SPEC.md](D:/coding/octopus/docs/step-07/B-SPEC.md)

输入关系必须明确：

- `8.1 organizations` 直接继承 Step 7 已冻结的 organization detail / ownership / board access 语义
- `8.2 routes` 继续复用 Step 3 已冻结的 issue path 常量
- `8.3 payload / response` 直接以 Step 3 issue shared types / validators 为准；缺口只能增量补，不得平行发明
- `8.4 reads` 直接继承 Step 6 已落地的 issue list / detail 行为
- `8.5 writes` 不能绕过 Step 4 database query / session 边界自行发明新链路

## 3. 本步范围

本步只覆盖 `issue management`：

- `GET /api/issues`
- `GET /api/issues/{issueId}`
- `POST /api/issues`
- `PATCH /api/issues/{issueId}` 或等价 update 入口
- issue comments 的 list / create
- reviewer decision、reopen、comment 相关 workflow
- issue 与 `project / goal / agent / origin` 的第一批关联读取
- 常见过滤条件与对应 contract / workflow assertions

本步至少要稳定以下能力：

- issue 列表和详情在 Step 6 基线上继续成立
- issue 创建与更新
- issue comment 写入与读取
- issue status 第一批状态流转
- reviewer decision 到 issue status 的固定映射
- 已关闭 issue 的 reopen 语义
- issue activity action 名称兼容

本步不做：

- project / goal / agent 主对象管理
- runtime orchestration
- heartbeat run 管理
- workspace allocation / release / recovery
- issue checkout / release / commit 的完整执行链路
- attachment / artifact 存储语义
- chat session / message 细节

## 4. 输出要求

Step 8 完成后，B 至少要交付：

- issue route 更新
- issue create / update service 入口
- issue comment service 入口
- issue workflow state transition 入口
- issue 查询层对 comment / association / filtering 的补齐
- reviewer decision 到 status 的固定调用链
- 至少一条 issue create/update/comment/review 的真实 workflow
- 至少一组 response / payload assertion tests，明确字段、状态和错误语义
- 至少一组 issue module demo，能展示 list / detail / create / update / comment / review

## 5. 5.1 Route Scope 约束

### 5.1 A 已冻结的边界

- Step 8 只围绕 `issues`
- 所有 path 常量必须复用 Step 3 已冻结的 issue 路径常量
- `GET /api/issues` 和 `GET /api/issues/{issueId}` 继续保留 Step 6 读能力
- `POST /api/issues`、`PATCH /api/issues/{issueId}`、comment 入口、review decision 入口是本步允许新增的 mutation surface
- 本步不新增 project / goal / agent / run / workspace route

### 5.2 B 必须落的最小文件边界

`server/routes/` 下至少继续由：

- `issues.py`

承载本步接口。

命名可以微调，但职责不能漂：

- issue route 仍按资源边界独立维护
- route 只做参数接线、validator 接线、dependency 接线和 response 返回
- 不把 issue workflow 混进 org / approval route

## 6. 6.1 Payload / Response 约束

### 6.1 A 已冻结的边界

- issue response shape 继续以 Step 3 / Step 6 已冻结 shared contract 为准
- 新增 mutation payload 必须先走 shared validator；shared contract 缺口只能在 shared 层增量补齐
- route / service 不得返回 ORM 模型对象
- 数据库字段保持 snake_case，response 层继续输出 shared contract 的 camelCase

### 6.2 第一批状态与决策冻结范围

issue 第一批状态值只允许：

- `todo`
- `in_progress`
- `in_review`
- `blocked`
- `done`

reviewer decision 到 issue status 的最小映射固定为：

- `approve` -> `done`
- `request_changes` -> `in_progress`
- `blocked` -> `blocked`
- `needs_followup` -> 不直接改 issue status

reviewer decision 只允许在以下前置状态下发生：

- `in_review`
- `blocked`

### 6.3 reopen 语义

- 已关闭 issue 在 update 时如果显式要求 reopen，且未显式指定新 `status`
- 默认重新打开到 `todo`

## 7. 7.1 Activity / Audit 约束

Step 8 至少保留以下 issue activity action 名称：

- `issue.created`
- `issue.updated`
- `issue.comment_added`
- `issue.review_decision_recorded`
- `issue.human_intervention_required`
- `issue.deleted`
- `issue.checked_out`
- `issue.released`
- `issue.code_committed`

第一批最小记录义务：

- issue create / update / comment / review 成功后，必须有一条可追踪的 activity / audit 记录位
- 记录至少能关联：
  - `org_id`
  - `issue_id`
  - 动作名称
  - 变更时间
- 不得删除或改写上述 action 名称

## 8. 分层硬约束

Step 8 必须满足以下硬约束：

- `server/routes` 不直接查询数据库
- `server/services` 不直接创建 session
- `packages/database/queries` 不承载 HTTP response shape
- ownership 与 board access 必须在 route / dependency 边界显式接入
- query 只负责读取与更新，不负责 HTTP 403 / 404 / 409 / 422 语义
- shared types / validators 仍是 payload / response shape 唯一来源
- activity / audit 记录不得直接写在 route 中
- issue management 不混入 runtime / workspace / heartbeat_run 逻辑

## 9. B 线实现边界

- issue workflow 相关实现时，不得：
  - 自定义修改 issue 状态值命名
  - 自定义改写 reviewer decision 到 status 的映射
  - 删除上述 issue activity action 名称
- issue checkout / release / commit 相关历史约束继续保留为后续收紧方向：
  - project 处于 paused 状态时，checkout 必须拒绝
  - agent 只能以自己的 agent 身份 checkout
  - `commit` 只允许 agent 身份执行
- association 读取只能先补最小只读能力，不在本步提前冻结 project / goal / agent 主对象完整字段语义

## 10. 验收 demo

- Demo 1：演示 issue 创建、更新和状态流转
- Demo 2：演示 issue comment 写入与读取
- Demo 3：演示 issue 与 project / goal / agent / origin 的关联读取
- Demo 4：展示 workflow 测试结果

## 11. 当前不冻结

- project / goal / agent 主对象完整 schema
- runtime orchestration
- heartbeat run 语义
- workspace lifecycle
- attachment / artifact 存储语义
- chat 会话与消息细节
- observability / recovery 的最终收口方案
