# Step 12: Goal 管理

状态：12A-12E 已完成并通过基线验收

## 目标

实现上游 server 范围内的 Goal 管理能力，使 organization 可以显式创建目标层级、将目标分配给既有 Agent、将 Project/Issue 关联至目标，并在删除 Goal 前阻止破坏已实现关系的数据操作。

Step 12 不改变 organization 创建行为。上游 `POST /orgs` 未证明会自动创建 root Goal；onboarding/UI 通过 Goal API 显式创建 organization level Goal。Issue 仅在已有可选 root organization Goal 时应用默认归属行为。

## 前置状态

| 依赖步骤 | 当前可使用能力 | 本步骤使用方式 |
| --- | --- | --- |
| Step 7 | organization CRUD 与 scope access | Goal 全部读写归属一个 organization |
| Step 8 | Issue 已包含 nullable `goalId` 与列表筛选 | 增加默认 Goal 回填和 dependency 读取 |
| Step 10 | Project 已包含 legacy nullable `goalId` | 扩展为 `goalIds` / `goals` 多关联并同步 legacy 字段 |
| Step 11 | Agent CRUD 与 lifecycle | 校验 `ownerAgentId` 必须属于同一 organization |

## 上游证据

对照仓库：本地上游参考仓库。对照版本：`423ac762def58685300308890782ec67b76f9ee0`。

| 契约区域 | 上游证据路径 | 已确认结论 |
| --- | --- | --- |
| Goal schema | `packages/db/src/schema/goals.ts` | `goals` 包含 organization、父级与 owner agent 引用 |
| Project link schema | `packages/db/src/schema/project_goals.ts` | Project 与 Goal 为多对多关系，并保留 organization scope |
| Shared contract | `packages/shared/src/types/goal.ts`；`packages/shared/src/validators/goal.ts`；`packages/shared/src/constants.ts` | Goal 字段、enum、mutation payload 与 dependency response 结构已明确 |
| Goal API | `server/src/routes/goals.ts` | 存在 list/detail/dependencies/create/update/delete API 与 activity 行为 |
| Goal service | `server/src/services/goals.ts` | 存在 parent/owner 校验、默认 root Goal 查询、dependency 汇总与删除阻塞 |
| Project service | `packages/shared/src/validators/project.ts`；`server/src/services/projects.ts` | `goalIds` 优先于 deprecated `goalId`，响应输出 `goalIds` / `goals`，legacy 列同步首个目标 |
| Issue service | `server/src/services/issue-goal-fallback.ts`；`server/src/services/issues.ts`；`server/src/__tests__/issue-goal-fallback.test.ts` | 无 Project/显式 Goal 的 Issue 会采用已有默认 organization Goal；更新可回填 legacy 无归属 Issue |

## 兼容契约

### Goal 字段和枚举

| 字段 | 约束 |
| --- | --- |
| `id` | UUID 主键 |
| `orgId` | 必填，引用 organization |
| `title` | 必填非空 string |
| `description` | nullable string |
| `level` | `organization`、`team`、`agent`、`task`；缺省 `task` |
| `status` | `planned`、`active`、`achieved`、`cancelled`；缺省 `planned` |
| `parentId` | nullable Goal 引用；父级必须属于同 organization，禁止自身或循环 |
| `ownerAgentId` | nullable Agent 引用；Agent 必须属于同 organization |
| `createdAt`、`updatedAt` | 持久化时间字段 |

### API surface

| Method / path | 本步骤行为 |
| --- | --- |
| `GET /api/orgs/{orgId}/goals` | organization 内 Goal 列表 |
| `POST /api/orgs/{orgId}/goals` | 创建 Goal 并写入 `goal.created` activity |
| `GET /api/goals/{id}` | Goal 详情，按其 organization 检查访问 |
| `GET /api/goals/{id}/dependencies` | 读取当前可确认依赖和删除阻塞原因 |
| `PATCH /api/goals/{id}` | 更新 Goal 并写入 `goal.updated` activity |
| `DELETE /api/goals/{id}` | 无 blocker 时删除并写入 `goal.deleted` activity |

### Tables

| Table | 必要列/关系 | 本步骤处理 |
| --- | --- | --- |
| `goals` | `id`、`org_id`、`title`、`description`、`level`、`status`、`parent_id`、`owner_agent_id`、timestamps | 新增 |
| `project_goals` | `(project_id, goal_id)` 复合主键、`org_id`、timestamps；project/goal delete cascade | 新增 |
| `projects` | 已有 nullable `goal_id` legacy 列 | 保留并同步第一个 `goalIds` |
| `issues` | 已有 nullable `goal_id` 列 | 增加 fallback 行为并纳入 dependency 读取，不重建字段 |

## 分段任务

### 12A: Goal contract 与持久化

- 新增 Goal constants、types、validators 与 API paths，保持上游 field naming 和默认枚举语义。
- 新增 `Goal`、`ProjectGoal` schema/query 和 Alembic revision；migration 接续当前 `20260527_000006_chats.py` head。
- 注册 schema 与 route，落地 organization-scoped list、create、detail、patch、delete 的基础 HTTP contract。
- 实现基础序列化、404 与 organization access 行为，不在此分段混入后续 dependency 逻辑。

预期涉及位置：

- `packages/shared/constants/goal.py`
- `packages/shared/api_paths/goals.py`
- `packages/shared/types/goal.py`
- `packages/shared/validators/goal.py`
- `packages/database/schema/goals.py`
- `packages/database/queries/goals.py`
- `packages/database/migrations/versions/20260527_000007_goals.py`
- `server/dependencies/goals.py`
- `server/routes/goals.py`
- `server/services/goals.py`

实施记录：

- Shared contract 已实现 Goal enum、request/response/dependency 类型、validator 和 API path。
- Database 已实现 `goals`、`project_goals` schema/query 及 `20260527_000007_goals.py` migration。
- Server 已注册 Goal route 与 dependency，提供 organization 列表、创建、详情、更新、删除和 dependency 查询入口。

### 12B: 层级、Owner Agent 与 Goal activity

- 创建和更新 Goal 时校验 `ownerAgentId` 指向同 organization 的 Agent；空值解除关系。
- 创建和更新 Goal 时校验 `parentId` 指向同 organization 的 Goal，并拒绝 self-parent 和 ancestor cycle。
- 实现 `goal.created`、`goal.updated`、`goal.deleted` activity，actor 信息继续使用当前统一 actor context。
- 实现默认 organization Goal 选择函数：优先 active root organization Goal，其次任意 root organization Goal，最后任意 organization-level Goal；仅查询既存数据，不在 organization 创建时隐式插入 Goal。

实施记录：

- `GoalService` 已实现 owner agent 同 organization 校验、parent 同 organization 校验、自引用/循环拒绝与默认 organization Goal 解析。
- Goal 创建、更新和删除已写入 `goal.created`、`goal.updated`、`goal.deleted` activity。

### 12C: Project 多 Goal 关联

- 扩展 Project request 支持 deprecated `goalId` 与新字段 `goalIds`；若同时存在，以 `goalIds` 为准。
- 扩展 Project response 输出 `goalIds` 和 `goals` 引用列表，并保留 `goalId` 兼容字段。
- 创建/更新 Project 时同步 `project_goals`；legacy `projects.goal_id` 写入第一个目标，清空关系时置空。
- 本分段按上游已确认的同步与聚合行为实施；上游未证明 Project 写入时存在额外的跨 organization Goal 拒绝规则，不在兼容实现中自行新增。
- 不修改 Step 10 已实现的 resource/workspace 行为。

实施记录：

- Project validator/types 已支持 `goalId` 与 `goalIds`，Project detail 已输出 `goalIds` 与 `goals`。
- Project 创建/更新已同步 `project_goals`，并继续将首个关联 Goal 写入 legacy `projects.goal_id`。

### 12D: Issue Goal 归属与 dependencies

- Issue 创建/更新显式携带 `goalId` 时保留该关系字段；上游已确认行为重点是 fallback，不在本步骤凭推断增加写入拒绝规则。
- 当 Issue 未指定 `projectId` 且未指定 `goalId` 时，按上游 fallback 使用既存默认 organization Goal；存在 Project 时不强行补 Goal。
- 实现 `GET /api/goals/{id}/dependencies`，本步骤实际统计并预览 `childGoals`、`linkedProjects`、`linkedIssues`。
- 删除 blocker 至少包含 `last_root_organization_goal`、`child_goals`、`linked_projects`、`linked_issues`，冲突响应携带 dependency 结果。
- response 结构保留上游 `automations`、`costEvents`、`financeEvents` 计数/预览键时，只允许返回本步骤明确约定的未实现空值，并在测试与文档标记为后续扩展边界；不得创建伪业务表。

实施记录：

- Issue 创建和更新已在无 Project/显式 Goal 时回填既存默认 organization Goal，未改变显式关系字段的兼容语义。
- Goal dependency 已统计 child Goal、Project join/legacy link 与 Issue link，并以 blocker 阻止删除；未实现 dependency 分类按约定返回空计数/预览。

### 12E: 验收与对照记录

- 新增 contract tests，覆盖 path、enum、payload validator、schema/migration、CRUD API 与 scope access。
- 新增 workflow tests，覆盖 parent cycle、owner/parent 跨 organization 拒绝、activity、Project 多 Goal 同步、Issue fallback 和 dependency/delete blocker。
- 更新本任务文档实施记录与已实现/延后清单；开发完成后提供可复制执行的 `curl.exe` 验收 demo。
- 执行项目质量门禁：`uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest`、`uv run pyright .`。

实施记录：

- 新增 `tests/contract/test_step12_goal_management.py`，覆盖 contract、schema/migration、HTTP CRUD、Project/Issue 关联、dependency 与 scope access。
- 新增 `tests/workflows/test_step12_goal_workflow.py`，覆盖 hierarchy/owner 校验、activity、fallback、多 Goal 关联与删除 blocker。
- 最终门禁已通过：`uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest`（`198 passed`）、`uv run pyright .`。

## Dependency 返回边界

上游 `GoalDependencies` 完整响应包含：

| 分类 | 上游 blocker key | Step 12 状态 |
| --- | --- | --- |
| 最后一个 root organization Goal | `last_root_organization_goal` | 实现 |
| 子 Goal | `child_goals` | 实现 |
| Project 关联 | `linked_projects` | 实现，兼容 join 和 legacy `project.goalId` |
| Issue 关联 | `linked_issues` | 实现 |
| Automation | `automations` | 延后，当前主线无 Automation 表/服务 |
| Cost events | `cost_events` | 延后至 Step 19 Cost Summary 与 Activity Query |
| Finance events | `finance_events` | 延后至 Step 19/20 核对是否纳入实现范围 |

## 不在本步骤实施

- 不在 `POST /api/orgs` 中隐式创建 organization Goal 或 CEO Agent；此行为未由当前上游 server 契约证明。
- 不提前实现 Goal UI、onboarding wizard 或 CLI 交互；本步骤交付 server contract 和可验收 API。
- 不引入额外归属或新的业务聚合模型。
- 不提前实现 Automation、Cost、Finance 持久化，只在后续对应步骤补齐已确认 dependency blocker。

## 验收场景

1. 创建 organization 与两个 Agent；创建 root organization Goal 并指定同 organization owner，读取详情与 activity。
2. 使用另一 organization Agent 作为 owner，或另一 organization Goal 作为 parent 创建/更新 Goal，请求返回校验失败。
3. 创建子 Goal，验证 cycle 更新被拒绝，且 root Goal dependency 中包含 `child_goals`。
4. 创建携带 `goalIds` 的 Project，验证响应包含 `goalIds` / `goals`，legacy `goalId` 同步首个目标，Goal dependency 包含 `linked_projects`。
5. 创建不携带 Project/Goal 的 Issue，验证回填默认 root organization Goal；创建携带 Project 的 Issue，验证不强制回填。
6. 在子 Goal、Project 或 Issue 仍关联时删除 Goal，验证冲突与 blockers；清理依赖后允许删除并记录 `goal.deleted`。

## 本地验收流程

启动本地开发 actor 服务：

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
uv run alembic upgrade head
uv run server
```

在另一个 PowerShell 终端执行 Goal、Project 和 Issue 关联流程：

```powershell
$base = "http://127.0.0.1:8000"

$org = curl.exe -s -X POST "$base/api/orgs" `
  -H "Content-Type: application/json" `
  -d '{"name":"Goal Demo"}' | ConvertFrom-Json

$agent = curl.exe -s -X POST "$base/api/orgs/$($org.id)/agents" `
  -H "Content-Type: application/json" `
  -d '{"name":"Goal Owner"}' | ConvertFrom-Json

$goalBody = @{
  title = "Deliver compatible server"
  level = "organization"
  status = "active"
  ownerAgentId = $agent.id
} | ConvertTo-Json -Compress

$goal = curl.exe -s -X POST "$base/api/orgs/$($org.id)/goals" `
  -H "Content-Type: application/json" `
  -d $goalBody | ConvertFrom-Json

$projectBody = @{
  name = "Goal-linked project"
  goalIds = @($goal.id)
} | ConvertTo-Json -Compress

curl.exe -s -X POST "$base/api/orgs/$($org.id)/projects" `
  -H "Content-Type: application/json" `
  -d $projectBody

curl.exe -s -X POST "$base/api/orgs/$($org.id)/issues" `
  -H "Content-Type: application/json" `
  -d '{"title":"Uses default organization goal"}'

curl.exe -s "$base/api/goals/$($goal.id)/dependencies"
```

预期结果：Project 响应包含 `$goal.id` 的 `goalId` 和 `goalIds`，未显式指定 Goal 的 Issue 响应回填 `$goal.id`，dependency 响应包含 `linked_projects`、`linked_issues` 与 `last_root_organization_goal` blockers。

## 开发后记录要求

- 每个分段完成后将本文件相应小节补充“实施记录”，记录已落地文件、API、migration 和测试。
- 若上游证据与当前规划冲突，先更新本文件和 `docs/FEATURE.md`，再调整实现。
- 本步骤完成标准是 12A-12E 的 server 范围全部通过验收，不以仅创建 `goals` 表或 CRUD endpoint 视为完成。
