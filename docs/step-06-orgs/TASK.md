# Step 6: Organization 管理

状态：已完成

## 目标

实现 organization 作为第一层业务作用域的创建、读取和配置更新，使后续资源可以从一个真实创建的组织开始调试。

## API 范围

| Method | Path | 访问边界 | 行为 |
| --- | --- | --- | --- |
| `GET` | `/api/orgs` | board actor | 返回 organization summaries |
| `POST` | `/api/orgs` | board actor | 创建 organization 并记录活动 |
| `GET` | `/api/orgs/{orgId}` | board actor | 返回 organization detail |
| `PATCH` | `/api/orgs/{orgId}` | board actor | 修改允许字段并记录活动 |

## Request / Response 范围

创建和更新 payload 当前支持：

- `name`
- `description`
- `budgetMonthlyCents`
- `defaultChatIssueCreationMode`
- `brandColor`
- `requireBoardApprovalForNewAgents`

详情 response 包含 `id`、`urlKey`、`name`、`status`、描述、issue prefix/counter、预算字段、品牌色以及 created/updated 时间。

## 实现位置

| 文件 | 行为 |
| --- | --- |
| `packages/shared/types/organization.py` | `OrganizationSummary`、`OrganizationDetail` 与写入 payload |
| `packages/shared/validators/organization.py` | create/update 字段和类型校验 |
| `packages/database/schema/organizations.py` | organization 持久化字段与唯一索引 |
| `packages/database/queries/organizations.py` | list/get/create/update 数据操作 |
| `server/services/orgs.py` | row 到 response 映射及 activity 写入 |
| `server/routes/orgs.py` | board access、validator 调用和 HTTP 错误映射 |

## 业务行为

- 创建 organization 使用持久化默认字段并写入 `organization.created` activity。
- 更新仅修改 payload 显式提供的支持字段；有有效变更时写入 `organization.updated`。
- 空更新不会制造 activity 记录。
- 创建后的 organization 不需要其它业务前置对象，即可用于后续 issue 与 approval 请求。

## 错误语义

| 场景 | HTTP |
| --- | --- |
| 缺少 actor context | `503` |
| actor 非 board | `403` |
| organization 不存在 | `404` |
| payload 非法或含未支持字段 | `422` |

## 验收证据

- `tests/contract/test_step7_org_management.py` 覆盖 list/detail/create/update、actor guard、非法 payload、默认字段、activity 以及空更新行为。
- 测试文件名沿用开发时的原阶段编号；在当前计划中其能力归属 Step 6。

## Curl 验收 Demo

本步骤的正向 API 都要求 board actor。启动服务前启用本地开发 actor：

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
```

正向验收链路为：

```powershell
$org = curl.exe -s -X POST http://127.0.0.1:8000/api/orgs `
  -H "Content-Type: application/json" `
  -d '{"name":"Demo Org","description":"curl acceptance","budgetMonthlyCents":12000}' | ConvertFrom-Json
$env:ORG_ID = $org.id

curl.exe -s "http://127.0.0.1:8000/api/orgs/$env:ORG_ID"

curl.exe -s -X PATCH "http://127.0.0.1:8000/api/orgs/$env:ORG_ID" `
  -H "Content-Type: application/json" `
  -d '{"brandColor":"#0F766E","budgetMonthlyCents":15000}'
```

正向预期：创建返回 `status=active` 与生成的 `id`；更新返回新的 `brandColor` 和 `budgetMonthlyCents`。未启用 `OCTOPUS_LOCAL_TRUSTED` 且无真实 actor 时，相关接口返回 actor context 未配置错误。

## 未纳入

- 真实身份系统和授权策略定义，归 Step 19。
- project、goal、agent 等组织下其它业务资源管理，归其各自步骤。
