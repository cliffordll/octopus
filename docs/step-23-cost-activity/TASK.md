# Step 23: Cost Summary 与 Activity Query

状态：待开发

## 目标

先实现不阻塞主链路的成本摘要和 activity 查询能力，让用户能看见 agent/run/chat 做了什么、消耗了多少。

本步骤只做 cost event 归集、summary/query 和 activity query；budget hard-stop、incident、quota、skills analytics 归 Step 24。

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

## 边界

- 不做 budget policy、budget incident、hard-stop、approval 副作用，归 Step 24。
- 不做 provider quota 真实读取，归 Step 24。
- 不做 skills analytics 真实归集，归 Step 24。
- 不改变 runtime adapter 执行协议；adapter 继续只产出 usage/cost 原始证据。

## 验收

- Tests 覆盖 cost event 创建、summary、by-agent、by-provider、by-biller、by-project 和日期过滤。
- Tests 覆盖 cost 创建后的 `cost.reported` activity。
- Tests 覆盖 activity filters、issue activity、issue runs 和 run issues。
- Tests 覆盖跨 organization 拒绝和 agent 只能上报自己 cost。
