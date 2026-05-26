# Step 6 A Constraints

## 1. 目标

Step 6 的目标是先把第一批真实 read API 落成可对照、可验证、可继续扩展的读取链路，确保：

- route -> service -> query -> shared contract 的读取职责清晰
- organization-scoped 读取接口统一经过 Step 5 ownership guard
- 第一批响应字段、nullability、默认值和排序/过滤行为可以被测试明确验证
- Step 7 mutation workflow 建立在已验证的读取契约之上

这一步只做四件事：

- 固定第一批 read API 路径与资源边界
- 固定第一批 response shape / nullability / 最小读语义
- 固定 ownership guard 在 read API 中的接入规则
- 固定 read contract tests 的最小覆盖口径

## 2. 本步输入

Step 6 只能基于以下输入推进：

- [docs/DESIGN.md](D:/coding/octopus/docs/DESIGN.md)
- [docs/FEATURE.md](D:/coding/octopus/docs/FEATURE.md)
- [docs/step-03/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-03/A-CONSTRAINTS.md)
- [docs/step-03/SHARED-CONTRACT.md](D:/coding/octopus/docs/step-03/SHARED-CONTRACT.md)
- [docs/step-04/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-04/A-CONSTRAINTS.md)
- [docs/step-04/SCHEMA-COMPATIBILITY.md](D:/coding/octopus/docs/step-04/SCHEMA-COMPATIBILITY.md)
- [docs/step-04/DATABASE-MAPPING.md](D:/coding/octopus/docs/step-04/DATABASE-MAPPING.md)
- [docs/step-05/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-05/A-CONSTRAINTS.md)
- [docs/step-05/OWNERSHIP.md](D:/coding/octopus/docs/step-05/OWNERSHIP.md)

输入关系必须明确：

- `6.1 routes` 直接以 Step 3 已冻结的 shared path 常量为准
- `6.2 response shapes` 直接以 Step 3 shared types 和 Step 4 schema 映射为准
- `6.3 ownership guard` 直接消费 Step 5 已落地的 ownership service / dependency
- `6.4 tests` 同时参考 `FEATURE.md` 的 read API 验收要求和 Step 3 / Step 5 已有 contract 测试风格

## 3. 本步范围

本步只覆盖：

- 第一批 organizations / issues / approvals 的只读 route
- 对应 service 读取链路
- 对应 query 追加或细化
- 对应 shared response types 的消费
- 对应 contract / integration-style response assertions

第一批允许覆盖的读取接口只限：

- `GET /api/orgs/{orgId}`
- `GET /api/orgs/{orgId}/issues`
- `GET /api/orgs/{orgId}/approvals`
- `GET /api/issues/{id}`
- `GET /api/approvals/{id}`

本步不做：

- chat 读取接口
- dashboard / metrics / 聚合统计接口
- mutation 逻辑
- runtime orchestration 读取接口
- 搜索型、全文检索型或复杂筛选接口
- `GET /api/issues` 正常列表化实现

## 4. 输出要求

Step 6 完成后，B 至少要交付：

- 第一批 read route 文件或 route 扩展
- 对应 service 读取入口
- 对应 query 读取入口
- 至少一条 organization-scoped read API 经过 ownership guard 的真实调用链
- 至少一组 response assertion tests，明确字段、nullability 和默认行为

## 5. 6.1 Route Scope 约束

### 5.1 A 已冻结的边界

- Step 6 第一批 route 只围绕 `orgs / issues / approvals`
- 所有 path 常量必须复用 Step 3 已冻结的 shared api paths
- `GET /api/orgs/{orgId}` 作为 organization detail read API 继续保留并细化
- `GET /api/orgs/{orgId}/issues` 和 `GET /api/orgs/{orgId}/approvals` 是第一批 organization-scoped 列表入口
- `GET /api/issues/{id}` 与 `GET /api/approvals/{id}` 是第一批全局 detail 入口
- `GET /api/issues` 在 Step 6 继续视为兼容错误入口，不得被实现成正常列表接口

### 5.2 B 必须落的最小文件边界

`server/routes/` 下至少应有：

- `orgs.py`
- `issues.py`
- `approvals.py`

命名可以微调，但职责不能漂：

- route 文件按资源边界拆开
- 不把 org / issue / approval 的读取接口堆进一个大 route 文件
- route 只做参数接线、validator 接线、dependency 接线和 response 返回

### 5.3 B 当前可以做

- 在现有 `orgs.py` 上扩 detail / list read API
- 新增 `issues.py` / `approvals.py` 只读路由
- 为 detail route 增加最小 404 语义

### 5.4 B 当前不能做

- 把 `GET /api/issues` 实现成正常 org list 替代入口
- 在 route 中直接拼 SQL 或 ORM 查询
- 在 route 中做复杂字段聚合或业务推导

## 6. 6.2 Response Shape 约束

### 6.1 A 已冻结的边界

- response shape 必须优先复用 Step 3 已冻结的 shared types
- route / service 不得返回 ORM 模型对象
- 数据库字段名保持 snake_case 语义，response 层继续输出 shared contract 的 camelCase
- 第一批接口优先保证字段名、nullability、默认值、空列表行为稳定
- 详情接口允许先返回 shared types 里当前已冻结的最小字段集，不要求一步补全所有未来字段

### 6.2 第一批 response shape 冻结范围

第一批至少必须对齐这些 shared types：

- `OrganizationDetail`
- `OrganizationSummary`
- `IssueSummary` 或等价 issue list type
- `ApprovalSummary` 或等价 approval list type
- 若 Step 3 当前尚未冻结 issue / approval detail type，则 Step 6 可以先返回最小 detail shape，但必须由 A 先补 shared type 再让 B 接入

### 6.3 B 必须满足的行为

- organization list 返回 `list[OrganizationSummary]`
- organization detail 返回 `OrganizationDetail`
- org issues list 返回 issue summary 列表
- org approvals list 返回 approval summary 列表
- issue / approval detail 返回对应 detail shape 或 A 先冻结后的最小 detail shape
- 资源不存在时返回 `404`
- organization-scoped 列表空结果返回 `200 []`

### 6.4 B 当前不能做

- 直接把 schema 字段原样透传给 HTTP response
- 为了方便先回 `dict[str, Any]`
- 在 query 层返回 route response DTO
- 在 service 层发明 Step 3 未冻结的新 response 字段名

## 7. 6.3 Read Semantics 约束

### 7.1 A 已冻结的边界

- `GET /api/orgs/{orgId}/issues` 先以 `orgId` 过滤为第一语义
- `GET /api/orgs/{orgId}/approvals` 先以 `orgId` 过滤为第一语义
- 第一批 issue list 排序先沿用 Step 4 query 的 `board_order`, `created_at`
- 第一批 approval list 排序先沿用 Step 4 query 的 `created_at`
- detail 读取先按主键 / 资源 id 命中，不在 Step 6 引入复杂 identifier 解析扩展
- `GET /api/issues/{id}` 的 identifier 兼容扩展若未实现，必须在文档和测试里明确尚未覆盖

### 7.2 查询参数范围

Step 6 第一批只允许接入 Step 3 已有 validator 能覆盖的最小查询参数：

- issue list: `status`, `assigneeAgentId`
- approvals list: `status`

若要继续扩字段，必须先由 A 冻结 shared validator / type，再由 B 落实现。

### 7.3 B 当前不能做

- 先跳过 validator，直接放开任意 query string
- 把复杂搜索、全文检索、排序切换一次做进来
- 在没有 shared contract 冻结的前提下私自新增 filter 字段

## 8. 6.4 Ownership 接入约束

### 8.1 A 已冻结的边界

- 所有 organization-scoped read API 必须先经过 `require_organization_ownership`
- `GET /api/orgs/{orgId}`
- `GET /api/orgs/{orgId}/issues`
- `GET /api/orgs/{orgId}/approvals`

都属于 organization-scoped route，必须挂 ownership guard。

- `GET /api/issues/{id}` 和 `GET /api/approvals/{id}` 若当前无法只靠 path id 直接判断 ownership，可以先由 service 内部解析出 `org_id` 后复用同一 ownership service 判断
- 但无论入口形态如何，wrong pod / missing / expired 的拒绝语义必须仍沿用 Step 5

### 8.2 B 必须落的最小文件边界

至少需要：

- 在 organization-scoped route 上直接挂 Step 5 guard
- 在 id-based detail route 上有显式 ownership 校验调用位

### 8.3 B 当前不能做

- 让 Step 6 route 绕过 Step 5 ownership
- 在 query 层直接做 HTTP 403 / 409 语义
- 让 issue / approval detail 在未校验 org ownership 时直接返回数据

## 9. 分层硬约束

Step 6 必须满足以下硬约束：

- `server/routes` 不直接查询数据库
- `server/services` 不直接创建 session
- `packages/database/queries` 不承载 HTTP response shape
- organization-scoped route 必须显式接 ownership guard
- query 只负责读取与过滤，不负责业务拒绝语义
- shared types 仍是 response shape 唯一来源
- read API 阶段不混入 mutation 行为、状态机推进或副作用写入

## 10. B 的实现顺序

B 在 Step 6 的建议顺序固定为：

1. `6.1 organizations read`
2. `6.2 issues read`
3. `6.3 approvals read`
4. `6.4 response tests`

原因：

- organizations detail 已有最小基础，可先验证 ownership + response 链路
- issues / approvals 都依赖 Step 4 已有 query 和 Step 5 ownership 规则
- tests 必须在第一批 route 落完后统一对照 shared contract 收口

## 11. 验收标准

Step 6 验收时必须同时满足：

- 第一批 read route 已落地
- organization-scoped route 已接 ownership guard
- response shape 与 shared contract 对齐
- 空列表、404、403、409 等基础行为已明确
- 至少一组 read contract tests 能逐字段断言字段名、nullability、默认行为
- 没有把 `GET /api/issues` 偷偷做成正常列表入口

## 12. 验收 Demo

- Demo 1：调用 `GET /api/orgs/{orgId}`，展示 owned success 与 foreign reject
- Demo 2：调用 `GET /api/orgs/{orgId}/issues`，展示空列表与有数据列表
- Demo 3：调用 `GET /api/orgs/{orgId}/approvals`，展示 response shape 与排序行为
- Demo 4：调用 `GET /api/issues/{id}` 或 `GET /api/approvals/{id}`，展示 detail 返回与不存在时的 404
- Demo 5：展示 response assertion tests，证明字段对齐不是人工口头说明

## 13. 测试冻结口径

Step 6 最少必须冻结以下测试断言：

- organization detail owned request success
- organization detail foreign request rejected with `403`
- org issues list owned request success
- org approvals list owned request success
- org issues / approvals 空结果返回 `200 []`
- issue / approval detail missing 返回 `404`
- response 字段名使用 shared contract 命名
- issue / approval list query 参数非法时返回 validator 对应拒绝结果

测试目录建议至少包括：

- `tests/contract/`
- 如需要更贴近真实 app，可补 `tests/read_api/`

但无论放哪里，都必须覆盖上面 8 类断言。

## 14. 本步后的衔接关系

Step 6 完成后：

- Step 7 会在同一批资源上继续补 mutation workflow
- Step 7 的写接口可以直接复用 Step 6 已验证过的 shared types、ownership 入口和查询边界
- Step 10 会继续补强 wrong-route、failover 和 ownership 保护，但不应推翻 Step 6 的读取边界

所以 Step 6 的目标不是一次做完整控制面 API，而是先把第一批真实读路径对齐 shared contract、ownership 和数据库边界，让后续写路径建立在已验证的 read contract 之上。
