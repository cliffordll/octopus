# Step 17: Organization Resources、Organization Skills 与 Agent Instructions

状态：待开发

## 范围边界

本步骤只做 server 端能力，不修改 UI 或 CLI。UI 中“智能体技能标签不显示描述信息”的问题，在本步骤通过稳定服务端 skill entry response 解决数据供给边界；是否在标签上渲染描述由后续 UI 任务决定。

Step 14 已负责本地 runtime agent 的默认 instructions bundle 初始化、路径配置和运行时读取。本步骤补齐缺口：在上游存在 server 契约证据时，提供可管理的智能体说明文件 API；如果上游只存在 materialization 行为而没有完整管理 API，则本步骤只记录兼容边界，不自造无证据业务模型。

## 目标

- 补齐 organization-scoped resources CRUD。
- 补齐 organization skills 管理 API 与持久化/文件来源。
- 让 runtime skills snapshot/sync/enable 能消费 organization skills。
- 保证 agent skills API 返回足够展示的信息，包括 description 和来源元数据。
- 补齐智能体说明文件管理的服务端规划：在不改变 Step 14 runtime materialization 的前提下，明确 instructions 文件的读取、更新、权限、审计和路径安全边界。

## 上游证据

开发前必须先确认上游是否存在对应 server 契约，至少核对：

- organization resources 相关 schema、routes、services、shared types、validators 和 tests。
- organization skills 相关 schema、routes、services、shared types、validators 和 tests。
- agent/runtime skills snapshot 对 organization skill entry 的字段要求。
- agent instructions 相关 route、service、shared type、validator、测试或 materialization 证据，重点核对上游是否提供完整说明文件管理 API，还是仅在创建 agent 时写入默认 instructions bundle。

无法找到上游证据的字段或副作用，不得凭空新增。

## 任务拆分

### 17A: Organization Resources CRUD

- 新增或补齐 shared path/type/validator。
- 新增或补齐 database schema、migration、query。
- 新增 server service 与 routes。
- 按 organization scope 校验访问。
- 记录 create/update/delete activity。
- 增加 contract/workflow tests。

### 17B: Organization Skills 管理

- 明确 organization skill 的数据库来源与文件来源。
- 实现 create/update/delete/list/detail API。
- 记录 skill 创建、更新、删除 activity。
- 明确与 `agentRuntimeConfig.skillsRootPath`、bundled skills、agent-home skills 的优先级关系。
- 增加 contract/workflow tests。

### 17C: Agent Skills Snapshot 元数据兼容

- 确保 `/api/agents/{id}/skills` 的每个可展示 entry 稳定返回：
  - `key`
  - `selectionKey`
  - `runtimeName`
  - `description`
  - `sourceClass`
  - `origin`
  - `originLabel`
  - `locationLabel`
  - `state`
  - `desired`
  - `managed`
- 修正服务端字段兼容问题，保证组织技能、外部技能、bundled skill、agent-home skill 都有可解释的来源字段。
- 不修改 UI/CLI；只保证服务端 response 足够支持后续显示。

### 17D: Agent Instructions 文件管理边界

- 对照上游确认是否存在完整的 instructions 文件管理 API。
- 如果上游存在对应契约，补齐 shared path/type/validator、server routes/service、路径安全校验、scope/access 校验和 contract/workflow tests。
- 管理对象只围绕 Step 14 已建立的 `instructionsRootPath`、`instructionsFilePath`、`instructionsEntryFile` 和 managed instructions bundle，不新增独立于 agent runtime config 的说明业务模型。
- 支持读取当前 agent instructions 内容、更新允许编辑的说明文件、恢复或重新 materialize 默认 bundle 的兼容行为；具体操作以确认到的上游 route/service 为准。
- 明确路径安全：相对路径仍解析到 agent `cwd` 或 managed agent home；禁止越界访问任意文件。
- 记录 instructions 更新 activity，保留 actor、agent、文件路径和变更来源，但不记录敏感内容。
- 与 Step 23 的真实 actor/access 解耦：本步骤使用现有开发 actor 结构和 organization scope，真实认证接入后替换数据来源，不改变 API shape。

## 验收

- Organization resource CRUD 有 scope、activity 和错误路径测试。
- Organization skill CRUD 有 scope、activity、重复/非法 slug 和删除影响测试。
- Agent skills snapshot 能返回 organization skill entry，且 description 不丢失。
- Runtime skills sync/enable 可选择 organization skill，并保持 Step 14 已建立的 materialization 行为。
- Agent instructions 文件管理边界已按上游证据落地或明确标记为“仅 materialization，无独立管理 API”；如落地 API，必须覆盖 scope、路径越界、读取、更新和 activity 测试。

## 不包含

- UI 标签渲染调整。
- CLI 命令调整。
- Skills analytics 真实使用统计，该能力仍归 Step 21。
- Runtime adapter materialization 重写；只接入 Step 14 已有消费边界。
- Step 14 已实现的 instructions 初始化和 runtime 读取重写。
- Step 23 的真实 actor/access、secret/env binding。
