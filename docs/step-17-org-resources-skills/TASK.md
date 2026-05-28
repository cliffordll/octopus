# Step 17: Organization Resources 与 Organization Skills

状态：待开发

## 范围边界

本步骤只做 server 端能力，不修改 UI 或 CLI。UI 中“智能体技能标签不显示描述信息”的问题，在本步骤通过稳定服务端 skill entry response 解决数据供给边界；是否在标签上渲染描述由后续 UI 任务决定。

## 目标

- 补齐 organization-scoped resources CRUD。
- 补齐 organization skills 管理 API 与持久化/文件来源。
- 让 runtime skills snapshot/sync/enable 能消费 organization skills。
- 保证 agent skills API 返回足够展示的信息，包括 description 和来源元数据。

## 上游证据

开发前必须先确认上游是否存在对应 server 契约，至少核对：

- organization resources 相关 schema、routes、services、shared types、validators 和 tests。
- organization skills 相关 schema、routes、services、shared types、validators 和 tests。
- agent/runtime skills snapshot 对 organization skill entry 的字段要求。

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

## 验收

- Organization resource CRUD 有 scope、activity 和错误路径测试。
- Organization skill CRUD 有 scope、activity、重复/非法 slug 和删除影响测试。
- Agent skills snapshot 能返回 organization skill entry，且 description 不丢失。
- Runtime skills sync/enable 可选择 organization skill，并保持 Step 14 已建立的 materialization 行为。

## 不包含

- UI 标签渲染调整。
- CLI 命令调整。
- Skills analytics 真实使用统计，该能力仍归 Step 21。
- Runtime adapter materialization 重写；只接入 Step 14 已有消费边界。
