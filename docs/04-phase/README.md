# Phase 4 Draft

## 状态

- Draft
- 待 B 进入 database 基础层实现时收口

## 目标

建立 Python 版数据库映射边界，先固定 schema、client、query、migration 的职责，不在 service 层直接散写数据库细节。

## 本阶段范围

- `packages/database/src/schema/`
- `packages/database/src/clients/`
- `packages/database/src/queries/`
- `packages/database/src/migrations/`
- 第一批 `organizations` / `issues` / `approvals` 相关表映射

## A 线需要冻结的内容

- 第一批表的字段命名、nullability、默认值
- 外键关系与关键唯一约束
- query 层和 service 层的边界
- 哪些字段直接服务于 read API，哪些字段服务于 workflow

## B 线实现重点

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

## 当前不冻结

- 全量表映射
- 复杂统计查询
- 大批量导入导出语义

