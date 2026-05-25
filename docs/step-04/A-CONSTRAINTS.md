# Step 4 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先给出 Step 4 的目标和范围，不作为当前阶段的冻结实现约束。等 B 完成 Step 3 后，再按实际 shared contract 落地结果收紧本文件。

## 目标

建立 Python 版数据库映射边界，先固定 schema、client、query、migration 的职责，不在 service 层直接散写数据库细节。

## 本阶段范围

- `packages/database/src/schema/`
- `packages/database/src/clients/`
- `packages/database/src/queries/`
- `packages/database/src/migrations/`
- 第一批 `organizations` / `issues` / `approvals` 相关表映射
- 以 `SCHEMA-COMPATIBILITY.md` 作为字段、默认值、外键和约束的盘点输入

## A 线必须先冻结的内容

- 以下内容暂不视为已冻结，只是后续收口方向：
- 第一批表的字段命名、nullability、默认值
- 外键关系与关键唯一约束
- query 层和 service 层的边界
- 哪些字段直接服务于 read API，哪些字段服务于 workflow

## B 线实现边界

- 提供统一数据库 client / session 入口
- 让 query 层成为 route / service 的唯一数据库读取入口
- 避免在 route 中直接写 SQL 或 ORM 拼接逻辑

## 验收 demo

- Demo 1：展示 `packages/database/` 目录职责
- Demo 2：展示 1 到 2 个 上游参考实现 业务表的 Python 映射
- Demo 3：展示数据库 client 初始化与 transaction 入口
- Demo 4：展示一条从 query 到 service 的最小调用路径

## 待确认项

- ORM / SQL toolkit 的最终选型
- migration 与 schema 定义是否同源维护
- API 层需要的聚合字段由 query 层还是 service 层拼装

## Step 3 完成后再补

- 第一批真实落地的 shared types 与数据库字段映射关系
- read API 首批会实际消费哪些查询入口
- query 层最小聚合边界
- migration 基线如何初始化

## 当前不冻结

- 全量表映射
- 复杂统计查询
- 大批量导入导出语义
