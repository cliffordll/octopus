# Phase 3 Draft

## 状态

- Draft
- 待 B 进入 shared contract 实现时收口

## 目标

建立 `packages/shared/` 的最小共享契约层，避免 API path、枚举、请求模型和校验逻辑散落在 `server/` 与 `database/` 之间。

## 本阶段范围

- `packages/shared/src/constants/`
- `packages/shared/src/types/`
- `packages/shared/src/validators/`
- `packages/shared/src/api_paths/`
- 第一批 `orgs` / `issues` / `approvals` 契约常量归位

## A 线需要冻结的内容

- 第一批 API path 常量命名
- 第一批共享枚举与状态值
- 第一批请求 payload / 响应对象的共享类型边界
- validator 放置边界和复用方式

## B 线实现重点

- 在 route 和 service 中直接消费 shared contract
- 避免在 `server/` 内重复声明 path、状态值和 payload shape

## 验收 demo

- Demo 1：展示 `packages/shared/` 目录结构和职责划分
- Demo 2：展示一个路由直接复用 `api_paths`
- Demo 3：展示一个枚举、一个请求模型、一个 validator 的复用链路
- Demo 4：展示契约测试或最小引用示例，证明 shared contract 已经真正被消费

## 待确认项

- Python 实现使用何种 schema / validation 方案
- 共享类型是否需要区分 API DTO 与内部 service DTO
- 哪些字段必须直接对齐 上游参考实现，哪些字段允许后续细化

## 当前不冻结

- 全量 API 类型
- chat 相关共享契约
- runtime transcript/result 全量模型

