# Step 3: Shared Contract

状态：已完成

## 目标

在业务路由和持久化实现之前，集中固定首批资源的外部 API 路径、类型、枚举和校验规则，使服务端不在各层重复定义契约。

## 实施范围

首批资源覆盖：

- organizations：列表、详情、创建与更新所需契约。
- issues：organization 内列表、详情、创建、更新、comments 与 review decision 所需契约。
- approvals：列表、详情、创建及决策流程所需契约。

## 文件结构

| 目录 | 已落内容 |
| --- | --- |
| `packages/shared/api_paths/` | `organizations.py`、`issues.py`、`approvals.py` 中的路由常量 |
| `packages/shared/constants/` | organization status、issue status/priority/origin、approval type/status 及默认值 |
| `packages/shared/types/` | request/response `TypedDict` 类型 |
| `packages/shared/validators/` | payload 与查询过滤校验函数 |

## API Path 契约

| 资源 | Path |
| --- | --- |
| Organizations | `/api/orgs`、`/api/orgs/{orgId}` |
| Issues | `/api/orgs/{orgId}/issues`、`/api/issues/{id}`、`/api/issues/{id}/comments`、`/api/issues/{id}/review-decision` |
| Approvals | `/api/orgs/{orgId}/approvals`、`/api/approvals/{id}` 及 `approve`、`reject`、`request-revision`、`resubmit` 动作路径 |

`GET /api/issues` 保留为缺少 `orgId` 的错误入口，用于提示使用 organization-scoped 列表路径。

## 已固定的关键值

| 类型 | 值 |
| --- | --- |
| Issue status | `backlog`、`todo`、`in_progress`、`in_review`、`done`、`blocked`、`cancelled` |
| Issue priority | `critical`、`high`、`medium`、`low` |
| Issue origin | `manual`、`automation_execution` |
| Approval status | `pending`、`revision_requested`、`approved`、`rejected`、`cancelled` |
| Approval type | `hire_agent`、`approve_ceo_strategy`、`budget_override_required`、`chat_issue_creation`、`chat_operation` |

默认值包括 issue `backlog` / `medium` / `manual` 以及 approval `pending`。

## 分层规则

- validator 检查字段集合、必填字段和枚举值，不执行权限、organization scope、事务或 workflow 判断。
- API 对外使用 camelCase 类型；数据库 snake_case 到响应结构的转换由 service 完成。
- route 注册必须引用 shared paths，避免路径字面量漂移。
- 后续资源可扩展 shared contract，但不得修改已存在的兼容字面值而不提供证据。

## 实际接入

- `server/routes/orgs.py` 引用 `ORG_LIST_PATH` 与 `ORG_DETAIL_PATH`。
- `server/services/orgs.py` 使用 `OrganizationSummary` / `OrganizationDetail`。
- Step 6-9 已继续消费 issue 与 approval 的 types、validators 和 paths。

## 验收证据

- `tests/contract/test_step3_shared_contract.py` 覆盖 path 常量、枚举/默认值以及 validator 成功与失败路径。
- 当前业务路由文件中的 paths 均从 `packages/shared/api_paths` 引入。

## 未纳入

- project、goal、agent、run、runtime、workspace、chat 与 storage 的共享契约将在对应步骤按上游证据增加。
