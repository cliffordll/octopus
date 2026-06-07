# Step 24: Cost Summary 与 Activity Query

状态：待开发

## 已提前完成

- `activity_log` 表、query helper 和大量业务 service 的 activity 写入已经在 Step 5-21 中提前落地，包括 organization、agent、issue、approval、project、chat、heartbeat、organization skill、runtime provider 等动作。
- Runtime adapter 已经能从部分本地 CLI 输出中归一化 `usage_json`、`costUsd`、provider、biller 等原始证据，但这些仍只停留在 run/result 或 adapter response 中。
- `runtime_providers` / `runtime_models` 的 CRUD 与 activity 写入已在 Step 21 提前完成；这为后续 cost by provider/model 提供配置维度，但不等同于 cost event 归集。

这些提前完成项只作为本步骤的输入基础，不代表 Step 24 已完成。

## 目标

先实现不阻塞主链路的成本摘要和 activity 查询能力，让用户能看见 agent/run/chat 做了什么、消耗了多少。

本步骤只做 cost event 归集、summary/query 和 activity query；budget hard-stop、incident、quota、skills analytics 归 Step 25。

## 上游证据

- `D:\coding\rudder\packages\db\src\schema\cost_events.ts`
- `D:\coding\rudder\server\src\routes\costs.ts`
- `D:\coding\rudder\server\src\routes\activity.ts`
- `D:\coding\rudder\server\src\services\costs.ts`
- `D:\coding\rudder\server\src\services\activity.ts`
- `D:\coding\rudder\packages\shared\src\types\cost.ts`
- `D:\coding\rudder\packages\shared\src\types\activity.ts`
- `D:\coding\rudder\packages\shared\src\validators\cost.ts`

## 任务

- 复用已有 `activity_log` 写入基础，补齐上游式 activity 查询 route/service/filter/response；不要重复创建第二套 activity 表。
- 增加 `cost_events` schema、migration、query 和 shared type/validator。
- 实现 `POST /api/orgs/{orgId}/cost-events`，支持 agent 自报自己的 cost，board 上报 organization 内 agent cost。
- 实现 cost summary/query：
  - `GET /api/orgs/{orgId}/costs/summary`
  - `GET /api/orgs/{orgId}/costs/by-agent`
  - `GET /api/orgs/{orgId}/costs/trend`
  - `GET /api/orgs/{orgId}/costs/by-agent-model`
  - `GET /api/orgs/{orgId}/costs/by-provider`
  - `GET /api/orgs/{orgId}/costs/by-biller`
  - `GET /api/orgs/{orgId}/costs/window-spend`
  - `GET /api/orgs/{orgId}/costs/by-project`
- 创建 cost event 后回写 organization/agent monthly spend 字段。
- 实现 activity query：
  - `GET /api/orgs/{orgId}/activity`
  - `POST /api/orgs/{orgId}/activity`
  - `GET /api/issues/{id}/activity`
  - `GET /api/issues/{id}/runs`
  - `GET /api/heartbeat-runs/{runId}/issues`
- 保持 details 脱敏和 organization scope。

## 剩余待开发

- 当前没有 `server/routes/costs.py` 和 `server/routes/activity.py`，也没有 cost summary/query API。
- 当前没有 `cost_events` 表、cost event validator、cost event 写入后 monthly spend 回写逻辑。
- 当前 activity 只有写入，没有统一查询 API、过滤器、details 脱敏和 issue/run 聚合查询契约。

## 边界

- 不做 budget policy、budget incident、hard-stop、approval 副作用，归 Step 25。
- 不做 provider quota 真实读取，归 Step 25。
- 不做 skills analytics 真实归集，归 Step 25。
- 不改变 runtime adapter 执行协议；adapter 继续只产出 usage/cost 原始证据。

## 验收

- Tests 覆盖 cost event 创建、summary、by-agent、by-provider、by-biller、by-project 和日期过滤。
- Tests 覆盖 cost 创建后的 `cost.reported` activity。
- Tests 覆盖 activity filters、issue activity、issue runs 和 run issues。
- Tests 覆盖跨 organization 拒绝和 agent 只能上报自己 cost。
