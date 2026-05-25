# Step 3 A Constraints

## 目标

本文件定义 A 在 `Step 3. Shared Contract 层` 需要先冻结的约束边界，供 B 在 `packages/shared/` 落地时直接消费。

目标是先把共享契约层的职责和收口边界固定下来，避免 API path、枚举、请求模型和校验逻辑散落在 `server/`、`packages/database/` 和测试中。

## 约束范围

- `packages/shared/constants/`
- `packages/shared/types/`
- `packages/shared/validators/`
- `packages/shared/api_paths/`
- 第一批 `orgs` / `issues` / `approvals` 契约常量归位
- `server/` 对共享契约的第一批接入点

## Step 3 交付目标

Step 3 不是实现业务接口，而是把后续步骤会反复使用的共享契约先冻结出来。

本步骤结束后，B 必须已经具备以下输入：

- 一套统一的 API path 常量定义
- 一套统一的第一批枚举和状态值定义
- 一套统一的第一批请求 payload / 响应对象类型定义
- 一套统一的第一批 validator 入口
- 一套明确的 route / service / shared 三层依赖方向

## 本步骤必须产出的文件边界

以下是 Step 3 结束时应存在的最小文件边界。B 可以按实际拆成多文件，但不能突破这些职责边界。

### `packages/shared/api_paths/`

- `organizations.py`
- `issues.py`
- `approvals.py`
- 如有目录汇总文件，只允许做 re-export，不允许再次声明 path 字面量

### `packages/shared/constants/`

- `organization.py`
- `issue.py`
- `approval.py`
- 如有跨资源共享常量，可单独放 `common.py`

### `packages/shared/types/`

- `organization.py`
- `issue.py`
- `approval.py`
- 如有跨资源公共类型，可单独放 `common.py`

### `packages/shared/validators/`

- `organization.py`
- `issue.py`
- `approval.py`
- validator 可以按资源拆分多个函数，但不允许把业务流程判断混入 validator

## A 线必须先冻结的内容

- 第一批 API path 常量命名
- 第一批共享枚举与状态值
- 第一批请求 payload / 响应对象的共享类型边界
- validator 放置边界和复用方式
- 共享类型与 validator 的命名方式
- 第一批允许接入 shared contract 的 route 范围

## 第一批资源范围

Step 3 只冻结第一批范围，不扩写全量资源。

第一批资源：

- organizations
- issues
- approvals

第一批优先覆盖对象：

- organization list / detail / create / update
- issue list / detail / create / update
- approval list / detail / create / resolve

当前不进入 Step 3 的对象：

- chats
- runtime transcripts / results
- documents
- work-products
- read-state
- follow / attachment / export-import 等外围能力

## 第一批接口范围

Step 3 只冻结第一批需要进入 shared contract 的接口，不在本步骤穷举全量接口面。

### Organizations

- `GET /api/orgs`
- `GET /api/orgs/:orgId`
- `POST /api/orgs`
- `PATCH /api/orgs/:orgId`

约束：

- `GET /api/orgs` 无业务 query 参数
- `GET /api/orgs` 仅 board 可访问
- `GET /api/orgs/:orgId` 使用 `orgId` path 参数
- `PATCH /api/orgs/:orgId` 需要保留 board 更新与 agent branding 子集更新的边界

### Issues

- `GET /api/orgs/:orgId/issues`
- `GET /api/issues/:id`
- `POST /api/orgs/:orgId/issues`
- `PATCH /api/issues/:id`

约束：

- `GET /api/issues` 在兼容语义上保留错误入口角色，不作为 Step 3 必须落地的 shared path 常量
- `GET /api/orgs/:orgId/issues` 使用 `orgId` path 参数
- 第一批 issue list query 只先冻结：
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
- `GET /api/issues/:id` 需要保留 identifier 解析语义入口

### Approvals

- `GET /api/orgs/:orgId/approvals`
- `GET /api/approvals/:id`
- `POST /api/orgs/:orgId/approvals`
- `POST /api/approvals/:id/approve`
- `POST /api/approvals/:id/reject`

约束：

- `GET /api/orgs/:orgId/approvals` 使用 `orgId` path 参数
- 第一批 approval list query 只先冻结 `status`
- `POST /api/approvals/:id/approve` 和 `POST /api/approvals/:id/reject` 复用 resolve 类决策 payload 边界

## 第一批共享状态与枚举

以下状态值和枚举必须在 Step 3 冻结到 shared contract，B 不得自行扩展、删减或改名。

### Organization statuses

- `active`
- `paused`
- `archived`

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

## 目录约束

- `constants/` 只放共享枚举、状态值、跨资源常量，不放 route 层临时常量
- `api_paths/` 只放已经冻结的 HTTP path 常量，不在 route 文件里重复拼写路径
- `types/` 只放共享请求 / 响应模型和跨模块都会引用的 DTO
- `validators/` 只放与共享契约直接对应的校验逻辑，不放 service 内部业务判断
- `packages/shared/` 内不放数据库字段映射，不放 ORM 模型，不放事务逻辑

## API Path 约束

- path 常量必须一资源一文件归位，不允许把全部接口路径堆在一个大文件
- path 常量必须保持既有 HTTP 路径语义，不允许为了 Python 实现改名
- route 层不允许继续写裸路径字面量；Step 3 后新增 route 必须优先引用 shared path 常量
- path 常量只表达路径，不表达权限、排序、默认行为

建议至少冻结以下第一批 path 常量：

- `GET /api/orgs`
- `GET /api/orgs/:orgId`
- `POST /api/orgs`
- `PATCH /api/orgs/:orgId`
- `GET /api/orgs/:orgId/issues`
- `GET /api/issues/:id`
- `POST /api/orgs/:orgId/issues`
- `PATCH /api/issues/:id`
- `GET /api/orgs/:orgId/approvals`
- `GET /api/approvals/:id`
- `POST /api/orgs/:orgId/approvals`
- `POST /api/approvals/:id/approve`
- `POST /api/approvals/:id/reject`

## 命名约束

- path 常量命名必须直接贴近资源语义，不引入额外产品化名字
- 枚举值、状态值、错误语义字段名必须与既有契约保持一致
- 共享类型命名优先体现资源对象和用途，例如 `OrganizationSummary`、`IssueListItem`、`CreateIssuePayload`
- 请求模型、响应模型、列表项模型必须显式区分，不能全部叫 `Organization`、`Issue`、`Approval`

## 共享常量约束

Step 3 只冻结共享枚举、状态值和直接被 path / types / validators 消费的常量。

第一批必须先冻结：

- organization statuses
- issue statuses
- issue priorities
- issue origin kinds
- approval types
- approval statuses

以下内容当前不要求在 Step 3 冻结：

- activity action 全量列表
- runtime result 分类
- chat 角色和消息状态
- 数据库默认值和迁移常量

## 共享边界约束

- route 读取 path、payload、response shape 时，优先从 `packages/shared/` 取，不再在 `server/` 内重复声明
- service 可以消费 shared types，但不在 service 内重新发明另一套 API DTO
- validator 和 type 必须成对演进，不能只补类型不补校验，或只补校验不补类型
- 先收口第一批 `orgs` / `issues` / `approvals`，不在 Step 3 扩写 chat / runtime 全量模型
- `packages/database/` 不得反向定义 API DTO；数据库层只能消费 shared 契约中确有必要共享的基础类型

## 类型模型约束

### 请求模型

第一批至少要有以下类型边界：

- `CreateOrganizationPayload`
- `UpdateOrganizationPayload`
- `ListOrgIssuesQuery`
- `CreateIssuePayload`
- `UpdateIssuePayload`
- `ListOrgApprovalsQuery`
- `CreateApprovalPayload`
- `ResolveApprovalPayload`

### 响应模型

第一批至少要有以下类型边界：

- `OrganizationSummary`
- `OrganizationDetail`
- `IssueListItem`
- `IssueDetail`
- `ApprovalListItem`
- `ApprovalDetail`

### 通用约束

- list item 和 detail 必须分开，不要先偷懒合成一个全量模型
- create / update payload 必须分开，不要用同一个模型兼容 create 和 patch
- partial update 语义必须在类型层体现，不能靠 route 或 service 临时判断
- 字段名以 HTTP 契约为准，不以数据库列名为准

## Validator 约束

- validator 只负责请求契约层校验，例如必填、类型、枚举值、字符串格式、基础长度边界
- validator 不负责权限、ownership、事务、状态流转和副作用判断
- validator 入口必须能被 route 直接调用，不要求 service 先参与
- validator 的输入输出应尽量贴近共享类型，避免 route 自己再写一次转换逻辑
- Step 3 先要求 validator 文件、函数命名和契约测试落地，不强制 route 在本步骤就完成 validator 接入

第一批至少需要覆盖：

- organization create / update payload
- issue list query
- issue create / update payload
- approval list query
- approval create / resolve payload

## B 线接入要求

- 在 route 和 service 中直接消费 shared contract
- 避免在 `server/` 内重复声明 path、状态值和 payload shape
- B 不主改共享字段名、状态值名、path 常量名
- 如果发现共享契约缺口，先补证据，由 A 收口后再继续实现
- B 在 Step 3 的主要工作不是补业务逻辑，而是让 `server/` 优先接入 shared contract

## B 线具体实现边界

本步骤 B 可以做：

- 创建 `packages/shared/` 下的实际文件和导出结构
- 在 `server/routes/` 中把第一批 path 常量切到 shared
- 为第一批 validator 建立实际文件、函数和契约测试
- 在 `server/services/` 中消费共享请求 / 响应类型

本步骤 B 不应该做：

- 借 Step 3 扩写新的业务接口
- 在 shared contract 中直接加入数据库映射细节
- 在 validator 中加入权限、ownership、状态机规则
- 因为 route 使用不便就改动既有字段名、状态值或 path 语义

## 依赖方向约束

Step 3 结束后必须满足以下依赖方向：

- `server/routes -> packages/shared`
- `server/services -> packages/shared`
- `packages/database` 不反向依赖 `server`
- `packages/shared` 不依赖 `server`
- `packages/shared` 不依赖具体 runtime

## 验收标准

Step 3 验收时，至少需要同时满足：

- 第一批 path 常量已经归位，route 中不再重复写第一批裸路径
- 第一批共享枚举和状态值已经归位
- 第一批 payload / response 类型已经归位
- 第一批 validator 已经存在并有契约测试覆盖
- `server/` 至少有一个第一批 route 已经接到 shared path 和 shared type

## 验收 Demo

- Demo 1：展示 `packages/shared/api_paths/`、`constants/`、`types/`、`validators/` 的实际文件结构
- Demo 2：选一个 route，展示 path 常量和响应类型已改从 shared 引用
- Demo 3：展示一个 create payload validator 的输入、校验成功和校验失败结果
- Demo 4：展示 `server/` 没有再声明同一批 path、状态值和 payload shape 的对照结果

## 与专项盘点文档的关系

- 本文件同时承担 Step 3 的接口范围约束和 shared contract 落地约束
- 字段映射到数据库表的工作不在本步骤处理，进入 Step 4
- workflow 和副作用细节不在本步骤冻结，进入 Step 7

## 当前不冻结

- 全量 API 类型
- chat 相关共享契约
- runtime transcript / result 全量模型
- Step 4 的数据库字段映射细节
- Step 5 的 ownership 规则细节
- Step 7 的状态机、副作用和事务边界
