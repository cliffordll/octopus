# Step 7 A Constraints

## 1. 目标

Step 7 的目标是把 `organization management` 从 Step 5/6 的基础可读能力推进到可直接交给 B 连续开发的组织管理模块，确保：

- organization 的读写边界独立成立，不再继续混在 issue / approval 主线里
- 组织更新能力继续建立在 Step 5 ownership 和 Step 6 read contract 之上
- organization 字段、默认值、拒绝语义和最小配置行为可以被测试明确验证
- Step 8 任务管理和 Step 9 审批管理都以稳定的 organization 对象和 organization 配置为前提

这一步只做六件事：

- 固定第一批 organization management 接口范围
- 固定 organization response / payload 的最小字段边界
- 固定 organization ownership、board access 与错误语义
- 固定 organization update 的最小写语义
- 固定 organization 配置字段更新与最小 activity / audit 记录语义
- 固定 organization contract / workflow tests 的最小覆盖口径

## 2. 本步输入

Step 7 只能基于以下输入推进：

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

输入关系必须明确：

- `7.1 routes` 直接以 Step 3 已冻结的 organization path 常量为准
- `7.2 response / payload` 直接以 Step 3 organization shared types / validators 为准
- `7.3 ownership` 继续直接消费 Step 5 已落地的 ownership service / dependency
- `7.4 reads` 直接继承 Step 6 已落地的 organization list / detail 行为
- `7.5 writes` 不能绕过 Step 4 database query / session 边界自行发明新链路

## 3. 本步范围

本步只覆盖 `organization management`：

- `GET /api/orgs`
- `GET /api/orgs/{orgId}`
- `PATCH /api/orgs/{orgId}` 或等价 update 入口
- organization shared payload / response 的继续消费
- organization ownership / board access / update rejection 语义
- 对应 contract / workflow / integration-style assertions

本步允许覆盖的第一批写能力只限：

- organization 基础字段更新
- organization 配置相关字段更新
- organization update 成功后的最小 activity / audit 记录

第一批允许更新的字段只限：

- `name`
- `description`
- `budgetMonthlyCents`
- `defaultChatIssueCreationMode`
- `brandColor`
- `requireBoardApprovalForNewAgents`

本步不做：

- organization create
- organization delete / archive / suspend 全量生命周期
- organization workspace_config 全量编辑
- organization 统计 / dashboard / 报表类接口
- organizations 下挂 `issues / approvals / projects / goals / agents` 的聚合入口扩展

## 4. 输出要求

Step 7 完成后，B 至少要交付：

- organization route 更新
- organization update service 入口
- organization update query 入口
- organization 配置字段更新链路
- organization update 成功后的最小 activity / audit 记录位
- 至少一条 organization update 经过 board / ownership 守卫的真实调用链
- 至少一组 response / payload assertion tests，明确字段、默认值和拒绝语义
- 至少一组 organization module demo，能展示 list / detail / update / rejection

## 5. 7.1 Route Scope 约束

### 5.1 A 已冻结的边界

- Step 7 只围绕 `orgs`
- 所有 path 常量必须复用 Step 3 已冻结的 `packages.shared.api_paths.organizations`
- `GET /api/orgs` 继续作为 board-scoped list 入口
- `GET /api/orgs/{orgId}` 继续作为 organization detail 入口
- `PATCH /api/orgs/{orgId}` 或等价 update 入口是本步唯一新增 mutation 入口
- 本步不新增 organization delete / archive / suspend 路由

### 5.2 B 必须落的最小文件边界

`server/routes/` 下至少继续由：

- `orgs.py`

承载本步接口。

命名可以微调，但职责不能漂：

- organization route 仍按资源边界独立维护
- route 只做参数接线、validator 接线、dependency 接线和 response 返回
- 不把 organization update 混进 issue / approval route

### 5.3 B 当前可以做

- 在现有 `orgs.py` 上补 organization update 入口
- 在现有 org service / dependency 上补 update 调用链
- 为 update route 增加最小 403 / 404 / 422 语义

### 5.4 B 当前不能做

- 为了方便先引入新的 `/api/organizations/...` 路径
- 在 route 中直接拼 SQL 或 ORM 查询
- 在 route 中直接写 activity 或副作用逻辑
- 在没有 A 明确冻结前扩到 organization 删除 / 停用语义

## 6. 7.2 Payload / Response 约束

### 6.1 A 已冻结的边界

- `GET /api/orgs` 继续返回 `list[OrganizationSummary]`
- `GET /api/orgs/{orgId}` 继续返回 `OrganizationDetail`
- `PATCH /api/orgs/{orgId}` 的 request payload 必须复用 Step 3 的 `UpdateOrganizationPayload`
- 更新成功后的 response 继续返回 `OrganizationDetail`
- route / service 不得返回 ORM 模型对象
- 数据库字段保持 snake_case，response 层继续输出 shared contract 的 camelCase

### 6.2 第一批字段冻结范围

本步至少必须稳定这些 detail 字段：

- `id`
- `urlKey`
- `name`
- `status`
- `description`
- `issuePrefix`
- `issueCounter`
- `budgetMonthlyCents`
- `spentMonthlyCents`
- `brandColor`
- `createdAt`
- `updatedAt`

本步 request payload 只冻结这些更新字段：

- `name`
- `description`
- `budgetMonthlyCents`
- `defaultChatIssueCreationMode`
- `brandColor`
- `requireBoardApprovalForNewAgents`

说明：

- `defaultChatIssueCreationMode` 与 `requireBoardApprovalForNewAgents` 当前已经在 shared types / validators 中存在，但尚未进入 `OrganizationDetail` response；本步先把它们冻结为可写字段，不强制要求同一步补进 detail response
- `workspace_config`、`pause_reason`、`paused_at` 本步不进入可写边界

### 6.3 B 必须满足的行为

- update payload 必须先走 shared validator
- validator 抛 `ValueError` 时 route 转 `422`
- update 成功返回最新 organization detail
- 资源不存在时返回 `404`
- foreign / missing / expired ownership 继续沿用 Step 5 拒绝语义

### 6.4 B 当前不能做

- 直接把 schema 字段原样透传给 HTTP response
- 为了方便先回 `dict[str, Any]`
- 在 service 层发明 Step 3 未冻结的新 payload 字段名
- 在 query 层返回 response DTO

## 7. 7.3 Access And Write Semantics 约束

### 7.1 A 已冻结的边界

- `GET /api/orgs` 继续是 board-scoped 入口
- `GET /api/orgs/{orgId}` 继续是 ownership-scoped 入口
- `PATCH /api/orgs/{orgId}` 同时要求：
  - organization ownership
  - board-level actor access

### 7.2 第一批 update 语义

Step 7 第一批 update 只冻结以下行为：

- 允许部分字段 patch
- 不传字段不更新
- `name` 为空字符串时拒绝
- `budgetMonthlyCents` 小于 0 时拒绝
- `brandColor` 允许 `null`
- `description` 允许 `null`
- `requireBoardApprovalForNewAgents` 必须是布尔值
- `defaultChatIssueCreationMode` 必须是非空字符串
- update 只改变 payload 中显式提供的字段
- update 成功后必须返回最新 organization detail

### 7.3 最小 activity / audit 语义

Step 7 第一批只冻结最小记录义务，不一次冻结全量 activity payload：

- organization 更新成功后，必须有一条可追踪的 activity / audit 记录位
- 该记录至少要能关联：
  - `org_id`
  - 动作名称
  - 变更时间
- 动作名称本步先冻结为一条最小兼容语义：
  - `organization.updated`
- 如果当前仓库的 activity service / workflow 尚未成型，B 可以先落最小 record writer 或预留集中调用位
- 但不得把“后续再补 activity”作为完全不接记录位的理由

### 7.4 错误语义

第一批必须明确：

- validator 失败：`422`
- 资源不存在：`404`
- foreign ownership：`403`
- missing ownership：`403`
- expired ownership：`409`
- 缺失 board actor：`503`
- 非 board actor 尝试更新：`403`

### 7.5 B 当前不能做

- 默认把任意 organization owner 都视为可以更新 organization
- 跳过 validator 直接允许任意 patch 字段
- 在没有 A 冻结前引入 organization delete / archive / suspend 状态机
- 把 organization update activity 写成散落在 route 层的临时日志

## 8. 分层硬约束

Step 7 必须满足以下硬约束：

- `server/routes` 不直接查询数据库
- `server/services` 不直接创建 session
- `packages/database/queries` 不承载 HTTP response shape
- ownership 与 board access 必须在 route / dependency 边界显式接入
- query 只负责读取与更新，不负责 HTTP 403 / 409 语义
- shared types / validators 仍是 payload / response shape 唯一来源
- activity / audit 记录不得直接写在 route 中
- organization update 阶段不混入 issue / approval / chat / runtime 逻辑

## 9. B 的实现顺序

B 在 Step 7 的建议顺序固定为：

1. `7.1 org update payload / validator wiring`
2. `7.2 org service update`
3. `7.3 org query update`
4. `7.4 route guard wiring`
5. `7.5 organization activity / audit hook`
6. `7.6 response / workflow tests`

原因：

- Step 6 已有 org list / detail，可以先在最小增量上补 update
- payload 和 guard 先定下来，B 不需要猜权限或字段口径
- activity / audit 记录位必须和真实 update 链路一起落，避免后面补写时改动 update 语义
- tests 必须和真实 route 一起落，避免再次出现“能力存在但真实入口没接上”

## 10. 验收标准

Step 7 验收时必须同时满足：

- organization update route 已落地
- board access 与 ownership guard 都已接入真实入口
- request payload 与 shared validator 对齐
- response shape 与 shared contract 对齐
- organization 配置字段更新已真实可用
- organization update 成功后的最小 activity / audit 记录位已落地
- 404 / 403 / 409 / 422 / 503 等基础行为已明确
- 至少一组 tests 能逐字段断言字段名、默认值和拒绝语义

## 11. 验收 Demo

- Demo 1：调用 `GET /api/orgs`，展示 board success 与 non-board reject
- Demo 2：调用 `GET /api/orgs/{orgId}`，展示 owned success 与 foreign / missing / expired reject
- Demo 3：调用 `PATCH /api/orgs/{orgId}`，展示基础字段与配置字段更新 success
- Demo 4：展示 organization update 产生的最小 activity / audit 记录
- Demo 5：展示 response / workflow tests，证明 organization management 不是人工口头说明

## 12. 测试冻结口径

Step 7 最少必须冻结以下测试断言：

- organization list board request success
- organization list missing actor returns `503`
- organization list non-board request rejected with `403`
- organization detail owned request success
- organization detail missing resource returns `404`
- organization update owned + board request success
- organization update can change config fields
- organization update foreign ownership rejected
- organization update expired ownership rejected
- organization update non-board rejected
- organization update invalid payload returns `422`
- organization update writes minimal activity / audit record
- response 字段名继续使用 shared contract 命名

测试目录建议至少包括：

- `tests/contract/`
- `tests/workflows/`

但无论放哪里，都必须覆盖上面 13 类断言。

## 13. 本步后的衔接关系

Step 7 完成后：

- Step 8 的任务管理会继续复用 organization ownership、board access 和 organization 配置字段
- Step 9 的审批管理会继续复用 organization 对象和 organization-scoped 拒绝语义
- Step 10 之后的 project / goal / agent / run 模块都会依赖 Step 7 已经稳定的 organization 管理边界

所以 Step 7 的目标不是把 organization 做成全量平台治理对象，而是先把 organization 作为独立业务模块稳定下来，让 B 后续开发不再需要反复猜 organization 规则。
