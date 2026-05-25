# Step 4 A Constraints

## 1. 目标

Step 4 的目标是固定数据库基础层边界，让 B 可以开始落 `packages/database/`，同时不把数据库细节散进 `server/` 和业务 service。

这一步只做三件事：

- 固定第一批 schema 映射范围
- 固定 database client / session / transaction 入口
- 固定 query 层与 service 层的职责边界

## 2. 本步输入

Step 4 只能基于以下输入推进：

- [docs/DESIGN.md](D:/coding/octopus/docs/DESIGN.md)
- [docs/FEATURE.md](D:/coding/octopus/docs/FEATURE.md)
- [docs/step-03/A-CONSTRAINTS.md](D:/coding/octopus/docs/step-03/A-CONSTRAINTS.md)
- [docs/step-03/SHARED-CONTRACT.md](D:/coding/octopus/docs/step-03/SHARED-CONTRACT.md)
- [docs/step-04/SCHEMA-COMPATIBILITY.md](D:/coding/octopus/docs/step-04/SCHEMA-COMPATIBILITY.md)

输入关系必须明确：

- `4.1 schema` 直接以 `SCHEMA-COMPATIBILITY.md` 为核心输入
- `4.2 clients` 主要受目录职责和事务边界约束，不直接依赖表字段盘点
- `4.3 queries` 同时参考 `SCHEMA-COMPATIBILITY.md` 和 Step 3 已冻结的 shared contract

## 3. 本步范围

本步只覆盖：

- `packages/database/schema/`
- `packages/database/clients/`
- `packages/database/queries/`
- `packages/database/migrations/`

第一批只允许覆盖这些业务表：

- `organizations`
- `issues`
- `approvals`
- `issue_approvals`
- `issue_comments`
- `activity_log`

本步不做：

- 完整 read API
- mutation workflow
- 复杂聚合报表
- 全量表映射
- 多数据库拓扑
- 连接池和性能调优

## 4. 输出要求

Step 4 完成后，B 至少要交付：

- `packages/database/schema/` 下首批表映射文件
- `packages/database/clients/` 下统一数据库入口
- `packages/database/queries/` 下首批 query 入口文件
- `packages/database/migrations/` 下迁移入口位
- 至少一条从 `service -> query -> client/session` 的最小调用链

## 5. 4.1 Schema 约束

### 5.1 A 已冻结的边界

- 数据库表名、字段名、默认值、nullability、主外键语义以 `SCHEMA-COMPATIBILITY.md` 为准
- 不允许借 Python 重写机会改业务表名、业务字段名或状态语义
- 第一批 schema 映射必须先服务 `organizations / issues / approvals` 最小闭环
- 关联表只先落 `issue_approvals / issue_comments / activity_log`
- 业务表与基础设施表必须分开思考，不能把 ownership、idempotency、outbox 这类基础设施表混入业务表映射命名中

### 5.2 B 必须落的最小文件边界

`packages/database/schema/` 下至少应有：

- `__init__.py`
- `organizations.py`
- `issues.py`
- `approvals.py`
- `issue_approvals.py`
- `issue_comments.py`
- `activity_log.py`

文件职责要求：

- 一张表一个文件
- 文件内只定义该表映射和与该表直接相关的局部约束
- 不在 schema 文件里写业务 workflow 逻辑
- 不在 schema 文件里写 route 级别返回结构

### 5.3 B 当前可以做

- 建立首批表映射骨架
- 明确字段类型、nullable、default、索引和外键定义
- 在 `schema/__init__.py` 中导出稳定入口

### 5.4 B 当前不能做

- 先把所有后续表都补齐
- 在 schema 文件里提前混入查询拼装逻辑
- 用聚合对象替代真实表边界
- 自行新增或改名核心业务字段

## 6. 4.2 Clients 约束

### 6.1 A 已冻结的边界

- `packages/database/clients/` 是唯一数据库连接入口
- session 与 transaction 入口只能在 client 层统一暴露
- route 不得直接拿数据库连接
- service 不得直接创建 session
- query 只能消费 client 层给出的受控 session / transaction 入口

### 6.2 B 必须落的最小文件边界

`packages/database/clients/` 下至少应有：

- `__init__.py`
- `base.py`
- `session.py`
- `transaction.py`

命名可以微调，但职责不能漂：

- `base` 承载 engine / client 初始化
- `session` 承载 session factory 或等价入口
- `transaction` 承载事务包装或事务上下文入口

### 6.3 B 当前可以做

- 建 client 初始化骨架
- 建 session factory 骨架
- 建事务上下文骨架
- 提供测试环境和应用环境共用的最小入口

### 6.4 B 当前不能做

- 提前做读写分离
- 提前做多租户连接拓扑
- 让 `server/` 或 `service/` 各自持有数据库初始化逻辑

## 7. 4.3 Queries 约束

### 7.1 A 已冻结的边界

- `packages/database/queries/` 是 route / service 的唯一数据库读取入口
- query 层负责查询与持久化细节
- service 层负责业务语义、聚合编排和工作流判断
- route 层只调 service，不直接拼 query
- query 层不负责状态机和审批语义裁定

### 7.2 B 必须落的最小文件边界

`packages/database/queries/` 下至少应有：

- `__init__.py`
- `organizations.py`
- `issues.py`
- `approvals.py`

如果当前只做最小入口，也必须保证：

- 文件名与资源边界一致
- 不把所有查询入口堆进一个 `queries.py`
- 不把 query 结果类型直接写成 route response shape

### 7.3 B 当前可以做

- 建首批 query 模块和函数入口
- 打通 `service -> query` 最小调用链
- 先做只服务当前阶段演示和下一步 read API 的基础读取入口

### 7.4 B 当前不能做

- 复杂搜索
- 跨资源 dashboard 查询
- 为了未来场景先写大而全 query 工具层
- 在 query 层返回混合业务语义的 API response DTO

## 8. 分层硬约束

Step 4 必须满足以下硬约束：

- `server/routes` 不直接接数据库
- `server/services` 不直接创建连接或 session
- `packages/database/schema` 不承载业务流程逻辑
- `packages/database/queries` 不承载 route response 组装
- `packages/database/clients` 不承载业务语义
- 数据库字段名保持数据库语义，shared/API 命名转换留给更上层处理

## 9. B 的实现顺序

B 在 Step 4 的建议顺序固定为：

1. `4.1 schema`
2. `4.2 clients`
3. `4.3 queries`

原因：

- schema 不稳定，query 就会漂
- client 入口不稳定，query 和 service 的依赖方向就会乱
- query 要建立在 schema 和 client 已经有稳定入口的前提下

## 10. 验收标准

Step 4 验收时必须同时满足：

- `packages/database/` 四层职责已经分开
- 第一批表映射已落地且命名稳定
- 有统一 client / session / transaction 入口
- 有首批 query 文件和最小 service 调用链
- 没有在 route 中直接拿数据库
- 没有在 service 中直接创建 session

## 11. 验收 Demo

- Demo 1：展示 `packages/database/` 目录结构，说明 `schema / clients / queries / migrations` 的职责
- Demo 2：展示 `organizations`、`issues` 或 `approvals` 中 1 到 2 个表的映射文件，说明字段、默认值、外键如何对应 `SCHEMA-COMPATIBILITY.md`
- Demo 3：展示数据库 client 初始化、session factory 和 transaction 入口
- Demo 4：展示一条从 `service -> query -> client/session` 的最小调用路径

## 12. 本步后的衔接关系

Step 4 完成后：

- Step 5 会消费 organization 边界和数据库访问入口
- Step 6 会消费首批 query 入口和 schema 映射

所以 Step 4 的目标不是把所有数据库能力一次做完，而是给 Step 5 和 Step 6 提供稳定、可扩展、不返工的基础层。
