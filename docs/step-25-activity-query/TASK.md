# Step 25: Activity Query

状态：已完成

## 已提前完成

- `activity_log` 表、query helper 和大量业务 service 的 activity 写入已经在 Step 5-21 中提前落地，包括 organization、agent、issue、approval、project、chat、heartbeat、organization skill、runtime provider 等动作。
- Step 20/21 已实现基础 run observability：run log、run stream、workspace operation log、run-intelligence list/detail/events/log、issue -> heartbeat runs 查询。

这些提前完成项只作为本步骤的输入基础，不代表 Step 25 已完成。

## 目标

先实现不阻塞主链路的 activity 查询能力，让用户和后端能看见 organization、issue、run、agent、chat 等对象发生了什么。

本步骤只做 activity query、filter、脱敏和 issue/run 聚合查询；cost event、cost summary 和 monthly spend 回写拆到 Step 27；budget hard-stop、incident、quota、skills analytics 归 Step 28。

## 上游证据

- `D:\coding\upstream-reference\server\src\routes\activity.ts`
- `D:\coding\upstream-reference\server\src\services\activity.ts`
- `D:\coding\upstream-reference\packages\shared\src\types\activity.ts`

## 任务

- 复用已有 `activity_log` 写入基础，补齐上游式 activity 查询 route/service/filter/response；不要重复创建第二套 activity 表。
- 实现 activity query：
  - `GET /api/orgs/{orgId}/activity`
  - `POST /api/orgs/{orgId}/activity`
  - `GET /api/issues/{id}/activity`
  - `GET /api/issues/{id}/runs`
  - `GET /api/heartbeat-runs/{runId}/issues`
- 支持 organization scope、entity filter、actor filter、action filter、时间窗口、分页或 limit。
- 保持 details 脱敏，不把 token、apiKey、authorization、cookie、secret、password 等敏感字段返回给前端。
- 复用已有 issue/run/workspace 记录补齐 issue runs 和 run issues 的聚合查询契约。

## 已实现记录

- 已新增 `server/routes/activity.py` 并注册 activity route。
- 已新增 organization activity 查询和写入入口，支持 entity、actor、action、时间窗口和 limit 过滤。
- 已实现 issue activity、issue runs、heartbeat run issues 聚合查询。
- Issue lookup 同时支持真实 issue id 和上游式 issue identifier，避免 UUID 被误判为 identifier 后导致 `/api/issues/{id}/runs` 返回 404。
- 已实现 activity details 脱敏，递归隐藏 token、apiKey、authorization、cookie、secret、password 等敏感字段。
- 已覆盖 organization scope 和跨 organization 拒绝行为。

## 剩余边界

- 本步骤只提供 activity query 和聚合视图，不创建 cost event，也不回写 monthly spend。
- Run intelligence、workspace operation log 和 runtime observability 的完整恢复矩阵归 Step 26。

## 边界

- 不新增 `cost_events` 表，不实现 cost summary/query；这些归 Step 27。
- 不做 budget policy、budget incident、hard-stop、approval 副作用，归 Step 28。
- 不做 provider quota 真实读取，归 Step 28。
- 不做 skills analytics 真实归集，归 Step 28。
- 不改变 runtime adapter 执行协议。

## 验收

- Tests 覆盖 activity filters、issue activity、issue runs 和 run issues。
- Tests 覆盖 details 脱敏和 organization scope。
- Tests 覆盖跨 organization 拒绝。

## 本地验证记录

- `uv run pytest tests/contract/test_step25_activity_query.py -q`：5 passed。覆盖 activity paths、filters、details 脱敏、issue/run 聚合、issue id/identifier lookup 和跨组织拒绝。
