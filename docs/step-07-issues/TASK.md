# Step 7: Issue 基础管理

状态：已完成

## 目标

实现 organization 下 issue 核心资源的创建、读取、更新和过滤能力；comment/review 流程在 Step 8 单独解释。

## API 范围

| Method | Path | 行为 |
| --- | --- | --- |
| `GET` | `/api/orgs/{orgId}/issues` | 列表并支持首批过滤 |
| `POST` | `/api/orgs/{orgId}/issues` | 创建 issue |
| `GET` | `/api/issues/{id}` | 返回 issue detail |
| `PATCH` | `/api/issues/{id}` | 更新 issue 核心字段或触发已支持扩展动作 |
| `GET` | `/api/issues` | 返回缺少组织作用域的 `400` 提示 |

## 数据与 Contract

Issue 核心状态值：

- `backlog`、`todo`、`in_progress`、`in_review`、`done`、`blocked`、`cancelled`

默认值：

- `status=backlog`
- `priority=medium`
- `originKind=manual`

列表过滤当前接入 `status`、`assigneeAgentId`、`projectId`、`goalId`、`originKind` 和 `originId`。详情 response 已保留 assignee/reviewer、project/goal/parent、origin、request depth 及时间字段，供后续模块接入。

## 实现位置

| 文件 | 行为 |
| --- | --- |
| `packages/shared/types/issue.py` | list/detail/create/update 和 review/comment 关联 payload |
| `packages/shared/validators/issue.py` | 列表过滤与写入 payload 校验 |
| `packages/database/schema/issues.py` | issue 字段、组织关联及查询索引 |
| `packages/database/queries/issues.py` | create/list/get/update 与审批恢复所需数据操作 |
| `server/services/issues.py` | 默认值、字段映射、activity 与 workflow 协调 |
| `server/routes/issues.py` | issue HTTP surface 和 validator/error 映射 |

## 核心行为

- `IssueService.create_issue()` 持久化 organization 关系和默认值，并写入 `issue.created`。
- 普通 update 只处理已支持字段并写入 `issue.updated`。
- unknown payload field 由 shared validator 拒绝，route 映射为 `422`。
- Issue 表已包含后续 project/goal/agent/run/workspace 关系所需的兼容字段，但相关模块行为不在本步骤实现。

## 当前实现边界

- comment 与 review decision 的入口和活动语义归 Step 8。
- approval 关联和审批后的 issue 恢复归 Step 9。
- issue 读取与 mutation 使用 Step 5 的统一 actor/access 边界；activity 记录实际请求 actor。

## 验收证据

- `tests/contract/test_step8_issue_management.py` 中 create、update、列表过滤、详情关联字段和 payload 拒绝断言。
- `tests/workflows/test_step8_issue_workflow.py` 中 create/update activity 与 reopen 基础流程断言。
- 测试文件名来自原合并实现阶段，当前按职责分别为 Step 7 与 Step 8 提供证据。

## Curl 验收 Demo

前提：按 Step 5 设置 `$env:OCTOPUS_LOCAL_TRUSTED = "1"` 并创建 organization，使 `$env:ORG_ID` 指向该记录。

创建 issue：

```powershell
$issue = curl.exe -s -X POST "http://127.0.0.1:8000/api/orgs/$env:ORG_ID/issues" `
  -H "Content-Type: application/json" `
  -d '{"title":"Curl issue","description":"created from acceptance demo","status":"todo","priority":"high","originKind":"manual"}' | ConvertFrom-Json
$env:ISSUE_ID = $issue.id
```

查询与更新：

```powershell
curl.exe -s "http://127.0.0.1:8000/api/issues/$env:ISSUE_ID"

curl.exe -s -X PATCH "http://127.0.0.1:8000/api/issues/$env:ISSUE_ID" `
  -H "Content-Type: application/json" `
  -d '{"title":"Curl issue updated","status":"in_progress"}'

curl.exe -s "http://127.0.0.1:8000/api/orgs/$env:ORG_ID/issues?status=in_progress"
```

错误入口验收：

```powershell
curl.exe -i http://127.0.0.1:8000/api/issues
```

预期返回 `400`，并提示使用 `/api/orgs/{orgId}/issues`。

在本地可信模式下，该链路的 activity actor 为 `local-board`；未启用本地可信模式且未提供真实 actor 时，scoped 请求按契约拒绝访问。
