# Step 8: Comment 与 Review 流程

状态：已完成

## 目标

在 issue 核心资源之上实现讨论记录和 review-driven 状态流转，使 issue 能形成可验证的人工审阅流程。

## API 范围

| Method | Path | 行为 |
| --- | --- | --- |
| `GET` | `/api/issues/{id}/comments` | 返回 issue 评论列表 |
| `POST` | `/api/issues/{id}/comments` | 新增评论 |
| `POST` | `/api/issues/{id}/review-decision` | 提交 review decision 并驱动状态/活动 |

## Review Decision 行为

| Decision | 允许来源状态 | 结果 |
| --- | --- | --- |
| `approve` | `in_review` 或 `blocked` | issue 转为 `done` |
| `request_changes` | `in_review` 或 `blocked` | issue 转为 `in_progress` |
| `blocked` | `in_review` 或 `blocked` | issue 转为 `blocked` |
| `needs_followup` | `in_review` 或 `blocked` | 保持状态并记录人工介入 activity |

不在可审阅状态的 issue 提交 review decision 时，service 拒绝该动作并由 route 返回 `422`。

## Activity 行为

| 动作 | Activity action |
| --- | --- |
| 新增评论 | `issue.comment_added` |
| 记录 review decision | `issue.review_decision_recorded` |
| 需要进一步人工处理 | `issue.human_intervention_required` |

普通 issue 修改使用 Step 7 的 `issue.updated`；审批相关 activity 不在本步骤产生。

## 实现位置

| 文件 | 行为 |
| --- | --- |
| `packages/database/schema/issue_comments.py` | comment 持久化结构和查询索引 |
| `packages/database/queries/issue_comments.py` | 插入与按时间读取 comments |
| `packages/shared/types/issue.py` | comment 与 review decision payload |
| `packages/shared/validators/issue.py` | body/decision 校验 |
| `server/services/issues.py` | comment 写入、review 状态映射和 activity |
| `server/routes/issues.py` | comment 与 review endpoints |

## 补充流程

- `reopen=true` 且未显式给定新 status 时，已完成或取消的 issue 返回 `todo`。
- 评论在持久化时关联其 issue 的 `org_id`，并按 actor 类型写入 author agent/user 字段。

## 当前实现边界

- comment/review route 使用 Step 5 的统一 actor/access 边界记录 activity，并拒绝跨 organization 请求。
- Approval 的创建、决定与 linked issue 恢复不属于 review 流程，归 Step 9。

## 验收证据

- `tests/contract/test_step8_issue_management.py` 覆盖 comment endpoints、review endpoint、状态映射和 activity 结果。
- `tests/workflows/test_step8_issue_workflow.py` 覆盖评论活动、review 三类状态结果、follow-up activity、非法 review 状态与 reopen 行为。

## Curl 验收 Demo

前提：已按 Step 7 创建 `$env:ISSUE_ID`。Review decision 仅接受处于 `in_review` 或 `blocked` 的 issue，先切换状态：

```powershell
curl.exe -s -X PATCH "http://127.0.0.1:8000/api/issues/$env:ISSUE_ID" `
  -H "Content-Type: application/json" `
  -d '{"status":"in_review"}'
```

新增并查询 comment：

```powershell
curl.exe -s -X POST "http://127.0.0.1:8000/api/issues/$env:ISSUE_ID/comments" `
  -H "Content-Type: application/json" `
  -d '{"body":"Review requested from curl demo"}'

curl.exe -s "http://127.0.0.1:8000/api/issues/$env:ISSUE_ID/comments"
```

提交 review decision：

```powershell
curl.exe -s -X POST "http://127.0.0.1:8000/api/issues/$env:ISSUE_ID/review-decision" `
  -H "Content-Type: application/json" `
  -d '{"decision":"approve","note":"accepted"}'
```

预期 response 中 `status` 为 `done`。将 `decision` 替换为 `request_changes` 时，处于可审阅状态的 issue 会转为 `in_progress`。

在 `OCTOPUS_LOCAL_TRUSTED=1` 的本地调试模式下，该 demo 产生的 comment/review activity actor 为 `local-board`。
