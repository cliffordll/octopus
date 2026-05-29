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

- organization resources 相关 schema、routes、services、shared types、validators 和 tests：
  - `packages/db/src/schema/organization_resources.ts`
  - `packages/shared/src/types/resource.ts`
  - `packages/shared/src/validators/resource.ts`
  - `packages/shared/src/constants.ts` 中 `ORGANIZATION_RESOURCE_KINDS`
  - `server/src/routes/orgs.ts`
  - `server/src/services/resource-catalog.ts`
  - `server/resources/bundled-skills/rudder/references/api-reference.md`
- organization skills 相关 schema、routes、services、shared types、validators 和 tests。
- agent/runtime skills snapshot 对 organization skill entry 的字段要求。
- agent instructions 相关 route、service、shared type、validator、测试或 materialization 证据，重点核对上游是否提供完整说明文件管理 API，还是仅在创建 agent 时写入默认 instructions bundle。

无法找到上游证据的字段或副作用，不得凭空新增。

已确认的 Step 17A organization resources 上游证据：

- `D:\coding\rudder\packages\db\src\schema\organization_resources.ts`：定义 `organization_resources` 表，字段为 `id`、`orgId`、`name`、`kind`、`locator`、`description`、`metadata`、`createdAt`、`updatedAt`。
- `D:\coding\rudder\packages\shared\src\constants.ts`：定义 `ORGANIZATION_RESOURCE_KINDS`。
- `D:\coding\rudder\packages\shared\src\types\resource.ts`：定义 `OrganizationResource`、create/update request 和 project attachment types。
- `D:\coding\rudder\packages\shared\src\validators\resource.ts`：定义 create/update validator，create 要求 `name/kind/locator`，update strict 且字段可选。
- `D:\coding\rudder\server\src\services\resource-catalog.ts`：实现 org-scoped list/get/create/update/delete，并对 `name/locator/description/metadata` 做归一化。
- `D:\coding\rudder\server\src\routes\orgs.ts`：在 org route 下暴露 `/resources` 子资源，并记录 `organization.resource.*` activity。
- `D:\coding\rudder\server\resources\bundled-skills\control-plane\references\api-reference.md`：作为 API 参考，不作为新增字段的唯一来源。

Step 17B/17C/17D 开发前仍必须先补齐对应上游证据。没有证据时只记录兼容边界，不实现自定义业务模型。

## 任务拆分

### 17A: Organization Resources CRUD

作用：补齐 organization resource catalog 的服务端 CRUD。Org resources 是可复用资源目录；Project resources 只是 project 到 org resource 的 attachment。运行时只自动注入 project 已附加资源，不默认把整个 org catalog 注入 prompt。

本地现状：

- `organization_resources` 与 `project_resource_attachments` schema/migration 已在 Step 10/15 相关资源能力中存在。
- `packages/shared/types/project.py` 已有 `OrganizationResource` shape，但还没有独立 `types/resource.py`。
- `packages/database/queries/resources.py` 已有 create/get 基础函数和 project attachment 查询，缺 org-scoped list/update/delete。
- `server/routes/projects.py` 已覆盖 project resource attachments，缺 `/api/orgs/{orgId}/resources` catalog routes。

执行顺序：

1. 先补 shared contract：path、type、validator，保证接口形状和字段归一化先稳定。
2. 再补 database query：只复用现有 schema/migration，不新增重复表。
3. 再补 service：集中处理 org scope、归一化、response 转换和 activity details，避免 route 变厚。
4. 再补 org routes：挂到现有 organization route 下，复用现有 actor 与 organization access dependency。
5. 最后补 contract/workflow tests：先覆盖接口契约，再覆盖完整 create/list/update/delete 链路。

具体实现：

- `packages/shared/api_paths/organizations.py`：新增：
  - `ORG_RESOURCE_LIST_PATH = "/api/orgs/{orgId}/resources"`
  - `ORG_RESOURCE_DETAIL_PATH = "/api/orgs/{orgId}/resources/{resourceId}"`
- `packages/shared/types/resource.py`：独立承载 `OrganizationResource`、`CreateOrganizationResourcePayload`、`UpdateOrganizationResourcePayload`；`types/project.py` 可继续复用或转引，避免重复 shape 漂移。
- `packages/shared/validators/resources.py`：实现 create/update validator，对齐上游：
  - `name` 必填非空，写入前 trim
  - `kind` 必须属于 `ORGANIZATION_RESOURCE_KINDS`
  - `locator` 必填非空，写入前 trim
  - `description` 可选/nullable，空白归一为 `None`
  - `metadata` 可选/nullable，必须是 object
  - update 使用 strict 字段集合，拒绝未知字段
- `packages/database/queries/resources.py`：补齐：
  - `list_organization_resources(session, org_id)`
  - `get_organization_resource_by_org(session, org_id, resource_id)`
  - `update_organization_resource(session, org_id, resource_id, fields)`
  - `delete_organization_resource(session, org_id, resource_id)`
- `server/services/resources.py` 或在现有内聚位置新增 `ResourceService`：实现 org-scoped CRUD、response 转换、activity details。
- `server/routes/orgs.py`：新增并注册：
  - `GET /api/orgs/{orgId}/resources`
  - `POST /api/orgs/{orgId}/resources`
  - `PATCH /api/orgs/{orgId}/resources/{resourceId}`
  - `DELETE /api/orgs/{orgId}/resources/{resourceId}`
- 按 organization scope 校验访问。
- 记录 activity：
  - `organization.resource.created`
  - `organization.resource.updated`
  - `organization.resource.deleted`
- 404 行为：resource 不存在或不属于当前 org 时统一返回 `Organization resource not found`，避免泄露跨组织资源存在性。
- 增加 contract/workflow tests：
  - contract 覆盖 path、validator、CRUD response、404 scope guard、activity action
  - workflow 覆盖 create/list/update/delete 和 project attachment 不被本步骤破坏

不做：

- 不新增新的 organization resource 表或迁移，除非发现本地 schema 与上游字段缺口。
- 不做 project resource attachment API；已属于 Step 10/15。
- 不把 org catalog 资源默认注入 agent prompt；只有 project attachment 资源进入运行上下文。
- 不修改 UI/CLI。

### 17B: Organization Skills 管理

开发前先确认上游 schema/routes/services/shared types/validators/tests，再落地。不能直接把 Step 14 runtime home skills 当成 organization skills 数据库模型。

- 明确 organization skill 的数据库来源与文件来源。
- 实现 create/update/delete/list/detail API。
- 记录 skill 创建、更新、删除 activity。
- 明确与 `agentRuntimeConfig.skillsRootPath`、bundled skills、agent-home skills 的优先级关系。
- 增加 contract/workflow tests。

### 17C: Agent Skills Snapshot 元数据兼容

本节只修 server response 的字段稳定性，不改 UI/CLI 展示逻辑。

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

本节必须先判定上游是否真的有独立 management API。若没有，只把“Step 14 已有 materialization + runtime 读取”写成兼容边界，不新增管理 API。

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

## 执行暂停点

- 完成 17A 文档与实现后暂停，说明改动内容、接口作用和测试结果，等待确认后再进入 17B。
- 完成 17B 后暂停，说明 organization skills 的来源、持久化和 runtime 消费边界，等待确认后再进入 17C。
- 完成 17C 后暂停，说明 skill entry response 字段变化和 UI 可消费能力，等待确认后再进入 17D。
- 完成 17D 证据审查后暂停；只有上游存在独立 management API 时才继续实现，否则只提交边界文档。
