# Step 10: Project 管理

状态：分阶段方案已完成并通过验收

## 目标

实现上游 server 范围内的 project 管理能力，使 project 可以在 organization 作用域内被维护，并成为后续 goal 关系与已存在 `issue.projectId` 关联的合法目标对象。

本步骤只实现已由上游证据确认的行为。当前仓库已经保留 issue 的 `projectId` 兼容字段和筛选入口，但这只能证明 issue 侧需要关联标识，不能反推出 project 的完整 schema、API、状态或副作用。

## 已确认输入

| 输入 | 当前可依赖内容 |
| --- | --- |
| `docs/DESIGN.md` | project 属于已选择实现的 server 控制面能力，必须遵守 organization scope 与契约优先原则 |
| `docs/FEATURE.md` | Step 10 的主体是 Project 管理；Goal、Agent 与 Runtime 属于后续步骤 |
| `docs/step-07-issues/TASK.md` | issue 已暴露 `projectId` 关联字段，但不定义 project 主对象行为 |
| `packages/shared/types/issue.py` | issue response/payload 仅保存 `projectId` 关系标识 |
| `packages/database/schema/issues.py` | issue 表已有 nullable `project_id`，不等同于 projects 表已冻结 |

## 上游证据

对照仓库：`D:\coding\rudder`。对照版本：`rudder@423ac762def58685300308890782ec67b76f9ee0`，提交日期 `2026-05-22`。

| 契约区域 | 上游证据路径 | 已确认结论 |
| --- | --- | --- |
| Schema | `packages/db/src/schema/projects.ts`；`packages/db/src/schema/project_resource_attachments.ts` | 上游存在 `projects` 主表、organization 外键、goal/agent 关系、归档/执行策略字段和 project resource attachment |
| Shared contract | `packages/shared/src/types/project.ts`；`packages/shared/src/validators/project.ts`；`packages/shared/src/constants.ts` | 请求字段、响应字段、project status 与 pause reason 已冻结 |
| HTTP surface | `server/src/routes/projects.ts` | 存在 project 核心 CRUD 与 resource attachment 路由，且均检查 organization access |
| Service behavior | `server/src/services/projects.ts` | 创建分配默认 color、派生 `urlKey`、同步 goal links/resource attachments，并在响应中装载 goals/resources/workspaces |
| Tests | `server/src/__tests__/project-routes.test.ts`；`server/src/__tests__/project-shortname-resolution.test.ts`；`server/src/__tests__/projects-service.test.ts` | 创建忽略 legacy `workspace` 输入、resource attachment、副作用与 shortname 行为可对照验证 |

Rudder 上游与当前 Python 仓库均使用 `organization` / `org_id` 和 `/api/orgs/{orgId}/...` 表达业务作用域。Step 10 不存在 `company` 到 `organization` 的额外改名适配；API path、字段和访问语义直接按 Rudder 对齐。

## 上游数据模型

| 上游列/输出字段 | 约束或行为 | Step 10 处理 |
| --- | --- | --- |
| `id` | UUID primary key | 实现 |
| `org_id` / `orgId` | 必填 organization scope | 实现 |
| `goal_id` / `goalId` | nullable，已标记为 legacy，首个 `goalIds` 的兼容列 | 数据列保留；关系行为归入 Step 11 |
| `name` | 必填；service 确保组织内派生 shortname 唯一 | 实现 |
| `urlKey` | 由 `name` 与 `id` 派生的响应字段 | 实现 |
| `description` | nullable text | 实现 |
| `status` | 必填，默认 `backlog` | 实现 |
| `lead_agent_id` / `leadAgentId` | nullable agent 外键 | 数据列保留；Agent 行为归入 Step 12 |
| `target_date` / `targetDate` | nullable date | 实现 |
| `color` | nullable；创建时未提供则由 palette 自动选择 | 实现 |
| `pause_reason` / `pauseReason` | nullable `manual` / `budget` / `system` | 字段已确认；暂停触发流程不在本步自创 |
| `paused_at` / `pausedAt` | nullable timestamp | 字段已确认；暂停触发流程不在本步自创 |
| `execution_workspace_policy` / `executionWorkspacePolicy` | nullable JSON policy | 数据字段已确认；执行 workspace 行为归入 Step 15 |
| `archived_at` / `archivedAt` | nullable timestamp，可由 update payload 修改 | 实现字段和 mutation |
| `created_at`、`updated_at` | 必填 timestamp，创建时默认当前时间 | 实现 |

上游 `PROJECT_STATUSES` 为 `backlog`、`planned`、`in_progress`、`completed`、`cancelled`；`PAUSE_REASONS` 为 `manual`、`budget`、`system`。

## 上游 HTTP 契约

| Method / upstream path | 行为 | 已确认副作用 |
| --- | --- | --- |
| `GET /api/orgs/{orgId}/projects` | scope 内 project 列表 | 检查 organization access |
| `GET /api/projects/{id}` | project 详情；不存在返回 `404` | 检查所属 organization access |
| `GET /api/projects/{id}/resources` | project resource attachment 列表 | 检查所属 organization access |
| `POST /api/orgs/{orgId}/projects` | 创建 project；成功返回 `201` | `project.created` activity；legacy `workspace` 输入被忽略 |
| `PATCH /api/projects/{id}` | 更新 project；不存在返回 `404` | `project.updated` activity |
| `DELETE /api/projects/{id}` | 删除 project；不存在返回 `404` | `project.deleted` activity |
| `POST /api/projects/{id}/resources` | 添加 resource attachment；成功返回 `201` | `project.resource.attached` activity |
| `PATCH /api/projects/{id}/resources/{attachmentId}` | 更新 resource attachment | `project.resource.updated` activity |
| `DELETE /api/projects/{id}/resources/{attachmentId}` | 移除 resource attachment | `project.resource.detached` activity |

Rudder 的 Project route 不提供 workspace mutation endpoint；但 Project service 在 list/detail/create/update 返回中装载 workspace 和 runtime service 信息。Workspace 的独立写入与运行行为仍需按 Step 15 核对相应上游入口。

路由还支持在 organization context 内使用 project `urlKey`/shortname 解析 `:id`；重名解析为歧义时返回冲突错误。此行为属于 project 核心 lookup 契约，应纳入 Step 10 的 route/service 测试。

## 上游 Payload 与 Response

| 类型 | 已确认字段 |
| --- | --- |
| Create payload | `goalId`、`goalIds`、`name`、`description`、`status`、`leadAgentId`、`targetDate`、`color`、`executionWorkspacePolicy`、`resourceAttachments`、`newResources`、`archivedAt` |
| Update payload | Create 中 project 字段的 partial |
| Project response | `id`、`orgId`、`urlKey`、`goalId`、`goalIds`、`goals`、`name`、`description`、`status`、`leadAgentId`、`targetDate`、`color`、`pauseReason`、`pausedAt`、`executionWorkspacePolicy`、`codebase`、`resources`、`workspaces`、`primaryWorkspace`、`archivedAt`、`createdAt`、`updatedAt` |

## 阶段切分决策

Rudder 的 Project 主响应已经聚合 `goalIds` / `goals`、`resources`、`codebase`、`workspaces` 与 `primaryWorkspace`。当前开发计划将 Goal 放在 Step 11、Workspace 放在 Step 15，且尚未为 organization resource / project resource attachment 指定独立步骤。Step 10 若只实现基础 CRUD，将不能完整匹配上游 Project response。

推荐采用分阶段兼容方案：

- Step 10 实现 project 主表、状态/基础字段、组织作用域、核心 CRUD、`urlKey` lookup、activity 和已存在 issue `projectId` 的主对象边界。
- Step 10 同时纳入 resource attachment contract 与 API，因为该能力由 Rudder 的 Project route 直接暴露，且 `resources` 是 Project response 的正式字段。
- Step 10 在 contract 文档和测试中明确标记 goal/workspace 聚合字段尚未启用，不用本地替代结构伪装完整上游 response。
- Step 11 接入 `goalId` / `goalIds` / `goals` 关系行为。
- Step 15 接入 `codebase`、`workspaces`、`primaryWorkspace`、execution workspace policy 的执行行为。

若要求 Step 10 首次交付即完整匹配 Rudder 的 Project response，则必须把 Goal 关联和 Workspace 响应装载前移到 Step 10，并同步重写 `docs/FEATURE.md` 的阶段安排。代码开发前需确认采用哪一种方案。

## 本步范围

按已冻结的 Rudder 契约，Step 10 只实现以下类别中被上游确认存在的能力：

- organization 范围内的 project 列表和详情读取。
- project 创建和可更新字段的 mutation 行为。
- project shared contract、持久化模型、query、service 和 route。
- project resource attachment 的 shared contract、持久化关系和 HTTP 行为。
- project 相关 activity 与 organization access/scope 校验。
- issue 已存在 `projectId` 关系在 project 对象落地后的有效性约束；仅在上游要求时实现写入校验或详情扩展。
- 为 Step 11 Goal 管理提供 project 主键和 organization 关系边界，不在本步骤实现 goal 行为。

## 不包含

- Goal CRUD、goal 状态机或 goal/project 联合工作流。
- Agent、runtime、heartbeat run、workspace 或执行编排。
- 没有上游证据的 project 状态、归档行为、成员权限或统计接口。
- 为便利本地调试而新增的非兼容 API。

## 实施分层

下列文件边界在契约核对后按实际需要新增或修改；命名遵循现有 organization/issue/approval 模块布局。

| 层级 | 预期落点 | 职责 |
| --- | --- | --- |
| Shared paths/constants | `packages/shared/api_paths/projects.py`、`packages/shared/constants/project.py` | 保存经上游确认的路径与枚举，不承载业务逻辑 |
| Shared types/validators | `packages/shared/types/project.py`、`packages/shared/validators/project.py`；如当前代码尚无 resource contract，则新增对应 resource 模块 | project 与 resource attachment 请求响应 shape、payload/query 校验 |
| Database schema/query | `packages/database/schema/projects.py`、`packages/database/queries/projects.py`；resource attachment 关系模块 | projects 与 project resource attachment 持久化映射和 organization-scoped 数据操作 |
| Migration | `packages/database/migrations/versions/<new_revision>.py` | 仅新增 Step 10 证据确认的数据库变更，不修改 baseline 历史文件 |
| Dependency/service/route | `server/dependencies/projects.py`、`server/services/projects.py`、`server/routes/projects.py` | scope 注入、流程副作用和 HTTP surface |
| Contract tests | `tests/contract/test_step10_project_management.py` | API shape、validator、错误语义和跨 organization 拒绝 |
| Workflow tests | `tests/workflows/test_step10_project_workflow.py` | 创建/更新/activity/关系副作用行为 |

## 开发任务

### Task 1: 冻结上游 Project 契约（已完成）

- 获取上游项目源码或可核对的正式引用。
- 定位 project schema、shared types、route、service 和 tests。
- 在本文件补入已确认的 API 表、字段表、枚举/状态表、activity 表与证据来源路径。
- 已确认 `issue.projectId` 是现有 relation 字段；写入时是否强制存在性与同组织校验，须在读取上游 issue mutation 行为后随 Task 5 落定，不由 Project schema 单独推断。

完成条件：本文件可以明确回答“请求哪些 API、传入哪些字段、返回哪些字段、写入哪些表、产生哪些副作用”。

### Task 2: Shared Contract 与 Contract Tests

- 先新增 `tests/contract/test_step10_project_management.py`，覆盖经证据确认的路径常量、payload/query 校验、response 字段和非法请求。
- 运行该测试并确认由于 project shared contract 尚未实现而失败。
- 新增或修改 `packages/shared/api_paths/`、`packages/shared/constants/`、`packages/shared/types/` 与 `packages/shared/validators/` 中的 project 模块。
- 重跑 contract 测试，确认 shared contract 行为通过。

完成条件：route/service 后续只消费 shared project contract，不在各层重复发明字段或枚举。

### Task 3: Schema、Migration 与 Query

- 在数据库 contract 测试中先覆盖 projects 表、关键字段、组织索引、resource attachment 关系和 query 行为。
- 新增 projects SQLAlchemy schema，并在 schema 导出边界注册。
- 新增 Alembic revision 建立 projects 表和本步纳入的 resource attachment 关系结构；baseline migration 保持冻结。
- 新增 organization-scoped project query 与 resource attachment query，并验证 list/get/create/update/attach/detach 及跨 organization 不返回错误对象。

完成条件：空库从当前 revision 升级到新 head 成功，query 层只返回数据库对象且不表达 HTTP 错误语义。

### Task 4: Service、Route 与 Scope

- 先新增 route/workflow 失败测试，覆盖经上游确认的 project CRUD、resource attachment HTTP surface、actor/access 前置条件、activity 与不存在资源错误。
- 新增 project dependency、service 和 route，并在 `server/routes/__init__.py` 注册路由。
- service 负责字段映射、事务内副作用与 response 转换；route 只负责输入校验、dependency 接线和 HTTP 错误映射。
- 所有 organization-scoped 访问复用 Step 5 的 actor/access 边界，并覆盖跨 organization 拒绝。

完成条件：project 与 resource attachment 的正向流程和 scope 拒绝流程均由 contract/workflow tests 覆盖。

### Task 5: 关系边界与后续阶段接口

- 对照上游确认 project 与 issue 的关联约束，并补相应 tests；如果上游只允许 nullable ID 读取，则不得额外增加写入前置条件。
- 记录 Step 11 可复用的 project organization 关系和 response 标识，但不新增 goal endpoint 或 goal 状态逻辑。
- 更新本文件的实现位置、已完成行为、验收证据和未纳入事项。

完成条件：Project 能独立使用，且不会把 Goal 或 Runtime 的业务提前混入 Step 10。

## 验收流程

当前实现落点：

- Shared contract：`packages/shared/api_paths/projects.py`、`packages/shared/constants/project.py`、`packages/shared/types/project.py`、`packages/shared/validators/project.py`。
- Persistence：`packages/database/schema/projects.py`、`packages/database/schema/resources.py`、`packages/database/queries/projects.py`、`packages/database/queries/resources.py` 和 revision `20260527_000002`。
- Server：`server/services/projects.py`、`server/dependencies/projects.py`、`server/routes/projects.py`。
- Tests：`tests/contract/test_step10_project_management.py`、`tests/workflows/test_step10_project_workflow.py`。

启动已配置本地调试 actor 的服务后，以下 PowerShell 示例覆盖本步核心流程：

```powershell
$org = curl.exe -s -X POST http://127.0.0.1:8000/api/orgs `
  -H "Content-Type: application/json" `
  -d '{"name":"Project Demo"}' | ConvertFrom-Json
$env:ORG_ID = $org.id

$project = curl.exe -s -X POST "http://127.0.0.1:8000/api/orgs/$env:ORG_ID/projects" `
  -H "Content-Type: application/json" `
  -d '{"name":"Control Plane","status":"planned","newResources":[{"name":"Repository","kind":"directory","locator":"D:/coding/octopus","role":"working_set"}]}' | ConvertFrom-Json
$env:PROJECT_ID = $project.id
$env:PROJECT_KEY = $project.urlKey
$env:ATTACHMENT_ID = $project.resources[0].id

curl.exe -s "http://127.0.0.1:8000/api/orgs/$env:ORG_ID/projects"
curl.exe -s "http://127.0.0.1:8000/api/projects/$env:PROJECT_KEY/resources?orgId=$env:ORG_ID"
curl.exe -s -X PATCH "http://127.0.0.1:8000/api/projects/$env:PROJECT_ID" `
  -H "Content-Type: application/json" `
  -d '{"status":"in_progress"}'
curl.exe -s -X PATCH "http://127.0.0.1:8000/api/projects/$env:PROJECT_ID/resources/$env:ATTACHMENT_ID" `
  -H "Content-Type: application/json" `
  -d '{"role":"reference","note":"Read before changes"}'
curl.exe -s -X DELETE "http://127.0.0.1:8000/api/projects/$env:PROJECT_ID/resources/$env:ATTACHMENT_ID"
```

以另一个 organization 绑定的 agent actor 调用 `GET /api/orgs/{orgId}/projects` 时，预期返回 `403`；contract 测试覆盖该拒绝路径。

代码完成后必须执行：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run pyright .
```

若当前环境因运行中的 server 进程导致 `uv` 无法同步安装脚本，可在说明原因后使用 `uv run --no-sync ...` 对已安装环境执行同等验证；不得跳过任一检查项。

本次验收记录：

- 标准 `uv run ...` 在验证时因运行中的 `.venv\Scripts\server.exe` 被占用而无法完成脚本同步。
- 按上述允许方式执行 `uv run --no-sync ruff check .`：通过。
- 执行 `uv run --no-sync ruff format --check .`：`86 files already formatted`。
- 执行 `uv run --no-sync pytest`：`164 passed`。
- 执行 `uv run --no-sync pyright .`：`0 errors, 0 warnings`。

## 提交规则

- 契约核对和实现过程中保持工作区变更可审查。
- 只有用户明确要求提交后，才创建 commit 或推送分支。
