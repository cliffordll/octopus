# Step 4 A Constraints

## 当前状态

当前文件是草稿版本。

用途是给出 Step 4 的并行设计入口，不要求等 Step 3 全部收尾后再一次性展开全步实现。

当前策略不是整步串行，而是把 Step 4 拆成可以并行推进的三个子块，由 A 先冻结最小边界，B 在不突破边界的前提下提前开始准备实现。

## 目标

建立 Python 版数据库映射边界，先固定 schema、client、query、migration 的职责，不在 service 层直接散写数据库细节。

## 本阶段范围

- `packages/database/src/schema/`
- `packages/database/src/clients/`
- `packages/database/src/queries/`
- `packages/database/src/migrations/`
- 第一批 `organizations` / `issues` / `approvals` 相关表映射
- 以 `SCHEMA-COMPATIBILITY.md` 作为字段、默认值、外键和约束的盘点输入

## 并行推进策略

Step 4 先拆成以下三个子块：

- `4.1 schema`
- `4.2 clients`
- `4.3 queries`

并行原则：

- A 不一次写满整步细节，只先冻结 B 当前不能猜的边界
- B 可以在 `4.1` 冻结后先建 schema 目录和首批映射入口
- B 可以在 `4.2` 冻结后先建 client / session 入口
- `4.3` 只先冻结 query 层职责，不提前展开复杂聚合查询

## 4.1 Schema

### A 线先冻结

- 第一批表范围：
  - `organizations`
  - `issues`
  - `approvals`
- 首批必须对齐的字段类型边界、nullability、默认值
- 主键、外键、关键唯一约束
- 数据库字段命名保持与既有表一致

### B 线可以先做

- 创建 `packages/database/src/schema/` 目录和资源文件
- 建立首批表映射骨架
- 为后续 query 层暴露稳定的 schema 入口

### 当前不展开

- 全量业务表
- 宽表聚合
- 历史遗留辅助表

## 4.2 Clients

### A 线先冻结

- `packages/database/src/clients/` 是唯一数据库 client 入口
- session / transaction 入口由 client 层统一暴露
- route 不得直接拿数据库连接
- service 只通过 query 或明确约束的 persistence 入口接数据库

### B 线可以先做

- client 初始化骨架
- session factory / transaction wrapper 骨架
- 测试环境和应用环境的最小接入点

### 当前不展开

- 连接池调优
- 读写分离
- 多数据库拓扑

## 4.3 Queries

### A 线先冻结

- `packages/database/src/queries/` 是 route / service 的唯一数据库读取入口
- query 层负责查询与持久化细节，不负责业务状态机
- service 负责业务语义和聚合编排，不在 route 中直接写查询拼装
- 先冻结第一批最小读取入口，不提前展开复杂统计和跨资源报表

### B 线可以先做

- 首批 query 模块目录和命名
- 与 `organizations` / `issues` / `approvals` 对应的最小查询入口位
- service 到 query 的调用链骨架

### 当前不展开

- 复杂搜索
- 批处理查询
- 大量统计和 dashboard 查询

## B 线实现边界

- 提供统一数据库 client / session 入口
- 让 query 层成为 route / service 的唯一数据库读取入口
- 避免在 route 中直接写 SQL 或 ORM 拼接逻辑
- 允许先搭目录、入口和最小调用链，不要求现在把全部查询细节实现完

## 验收 demo

- Demo 1：展示 `packages/database/` 目录职责
- Demo 2：展示 1 到 2 个 上游参考实现 业务表的 Python 映射
- Demo 3：展示数据库 client 初始化与 transaction 入口
- Demo 4：展示一条从 query 到 service 的最小调用路径

## 待确认项

- ORM / SQL toolkit 的最终选型
- migration 与 schema 定义是否同源维护
- API 层需要的聚合字段由 query 层还是 service 层拼装

## 等 B 完成 Step 3 后再补

- 第一批真实落地的 shared types 与数据库字段映射关系
- read API 首批会实际消费哪些查询入口
- query 层最小聚合边界
- migration 基线如何初始化

## 当前不冻结

- 全量表映射
- 复杂统计查询
- 大批量导入导出语义
