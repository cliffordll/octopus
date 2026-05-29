# Step 9: Approval 管理

状态：已完成

## 目标

实现 approval 作为独立决策对象的读取、创建、决策、修改请求与重新提交，并与相关 issue 形成已验证的恢复副作用。

## API 范围

| Method | Path | 访问/行为 |
| --- | --- | --- |
| `GET` | `/api/orgs/{orgId}/approvals` | 组织范围列表，可按 status 过滤 |
| `GET` | `/api/approvals/{id}` | 详情，并对敏感 payload 字段脱敏 |
| `POST` | `/api/orgs/{orgId}/approvals` | board actor 创建 approval |
| `POST` | `/api/approvals/{id}/approve` | board actor 批准 |
| `POST` | `/api/approvals/{id}/reject` | board actor 拒绝 |
| `POST` | `/api/approvals/{id}/request-revision` | board actor 请求修改 |
| `POST` | `/api/approvals/{id}/resubmit` | requester 重新提交 |

## 数据与状态

Approval status 包括 `pending`、`revision_requested`、`approved`、`rejected`、`cancelled`，默认状态为 `pending`。

创建 payload 可包含：

- `type`
- `payload`
- `requestedByAgentId`
- `issueIds`，用于建立 issue 与 approval 关系

详情包含 decision note、decider、decision time 和 redacted payload。

## 实现位置

| 文件 | 行为 |
| --- | --- |
| `packages/shared/types/approval.py` | list/detail/create/resolve/revision/resubmit payload |
| `packages/shared/validators/approval.py` | type/status/issueIds 及决策 payload 校验 |
| `packages/database/schema/approvals.py` | approval 主表 |
| `packages/database/schema/issue_approvals.py` | approval 与 issue 关系 |
| `packages/database/queries/approvals.py` | create/list/get/update/link 数据操作 |
| `packages/database/queries/issues.py` | 审批通过后的 linked blocked issue 恢复 |
| `server/services/approvals.py` | 决策流程、脱敏、activity 和 issue 恢复 |
| `server/routes/approvals.py` | HTTP surface、board guard 和错误映射 |

## 工作流行为

| 动作 | 结果状态 | Activity action |
| --- | --- | --- |
| 创建 approval | `pending` | `approval.created` |
| 关联 issue | 不改变 approval 状态 | `issue.approval_linked` |
| 批准 | `approved` | `approval.approved` |
| 拒绝 | `rejected` | `approval.rejected` |
| 请求修改 | `revision_requested` | `approval.revision_requested` |
| 重新提交 | `pending` | `approval.resubmitted` |

批准 linked blocked issue 时：

- 有 assignee 的 issue 恢复为可继续处理的状态，并记录 `approval.linked_issue_assignee_wakeup_queued`。
- 无 assignee 的 issue 恢复到待处理状态。

## 安全与访问边界

- 创建、approve、reject 与 request revision 要求 board actor；缺少 context 或 actor 不匹配沿用 `503` / `403` 语义。
- Resubmit 校验 requesting agent，一旦不是原请求 agent，返回 `403`。
- list/detail/resubmit 经过 organization access 校验；创建关联 `issueIds` 时拒绝不存在或跨 organization 的 issue。
- Approval detail 的 payload 会递归脱敏包含 `secret`、`token`、`password`、`apiKey`、`accessKey`、`privateKey` 或 `credential` 语义的字段。

## 验收证据

- `tests/contract/test_step9_approval_management.py` 覆盖 API、payload 验证、actor guard、decision、resubmit、linked issue 与 activity。
- `tests/workflows/test_step9_approval_workflow.py` 覆盖各类 activity、payload 脱敏、跨组织关联拒绝以及关联 blocked issue 恢复分支。

## Curl 验收 Demo

Approval 的创建与 board decision 依赖统一 actor。按 Step 5 启用本地开发 actor：

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
```

随后可执行正向验收脚本：

```powershell
$approval = curl.exe -s -X POST "http://127.0.0.1:8000/api/orgs/$env:ORG_ID/approvals" `
  -H "Content-Type: application/json" `
  -d ('{"type":"hire_agent","payload":{"accessToken":"secret-token"},"issueIds":["' + $env:ISSUE_ID + '"]}') | ConvertFrom-Json
$env:APPROVAL_ID = $approval.id

curl.exe -s "http://127.0.0.1:8000/api/approvals/$env:APPROVAL_ID"

curl.exe -s -X POST "http://127.0.0.1:8000/api/approvals/$env:APPROVAL_ID/approve" `
  -H "Content-Type: application/json" `
  -d '{"decisionNote":"approved from curl demo","decidedByUserId":"local-board"}'
```

正向预期：创建 response 中 `status=pending` 且 `payload.accessToken=[REDACTED]`；approve response 中 `status=approved`。若关联 issue 预先为 `blocked`，批准后 issue 按是否有 assignee 恢复为 `in_progress` 或 `todo`。

若未设置 `OCTOPUS_LOCAL_TRUSTED=1` 且没有后续真实 actor 来源，board decision 请求返回 `503`。

## 未纳入

- 审批触发真实 wakeup/run 执行的后续处理，需在 Step 13 以后按运行流程接入。
- 真实认证与授权数据来源，归 Step 22；其复用当前统一 actor/access 边界。
