# Step 27: Cost Events / Cost Summary

状态：待开发

## 已提前完成

- Runtime adapter 已经能从部分本地 CLI 输出中归一化 `usage_json`、`costUsd`、provider、biller 等原始证据，但这些仍只停留在 run/result 或 adapter response 中。
- `runtime_providers` / `runtime_models` 的 CRUD 与 activity 写入已在 Step 21 提前完成；这为后续 cost by provider/model 提供配置维度，但不等同于 cost event 归集。
- Step 25 负责 activity query；本步骤可以复用 activity 写入能力记录 `cost.reported`。

## 目标

实现不阻塞主链路的 cost event 归集和成本摘要查询，让用户能看见 agent/run/chat 消耗了多少，并为 Step 28 budget/governance 提供成本事实来源。

本步骤只做 cost event、summary/query 和 monthly spend 回写；budget hard-stop、incident、quota、skills analytics 归 Step 28。

## 上游证据

- `D:\coding\rudder\packages\db\src\schema\cost_events.ts`
- `D:\coding\rudder\server\src\routes\costs.ts`
- `D:\coding\rudder\server\src\services\costs.ts`
- `D:\coding\rudder\packages\shared\src\types\cost.ts`
- `D:\coding\rudder\packages\shared\src\validators\cost.ts`

## 任务

- 增加 `cost_events` schema、migration、query 和 shared type/validator。
- 实现 `POST /api/orgs/{orgId}/cost-events`，支持 agent 自报自己的 cost，board 上报 organization 内 agent cost。
- 创建 cost event 后写入 `cost.reported` activity。
- 创建 cost event 后回写 organization/agent monthly spend 字段。
- 实现 cost summary/query：
  - `GET /api/orgs/{orgId}/costs/summary`
  - `GET /api/orgs/{orgId}/costs/by-agent`
  - `GET /api/orgs/{orgId}/costs/trend`
  - `GET /api/orgs/{orgId}/costs/by-agent-model`
  - `GET /api/orgs/{orgId}/costs/by-provider`
  - `GET /api/orgs/{orgId}/costs/by-biller`
  - `GET /api/orgs/{orgId}/costs/window-spend`
  - `GET /api/orgs/{orgId}/costs/by-project`
- 保持 organization scope，不允许跨 organization 上报或查询 cost。

## 剩余待开发

- 当前没有 `server/routes/costs.py`，也没有 cost summary/query API。
- 当前没有 `cost_events` 表、cost event validator、cost event 写入后 monthly spend 回写逻辑。

## 边界

- 不做 activity query；归 Step 25。
- 不做 budget policy、budget incident、hard-stop、approval 副作用；归 Step 28。
- 不做 provider quota 真实读取；归 Step 28。
- 不做 skills analytics 真实归集；归 Step 28。
- 不改变 runtime adapter 执行协议；adapter 继续只产出 usage/cost 原始证据。

## 验收

- Tests 覆盖 cost event 创建、summary、by-agent、by-provider、by-biller、by-project 和日期过滤。
- Tests 覆盖 cost 创建后的 `cost.reported` activity。
- Tests 覆盖跨 organization 拒绝和 agent 只能上报自己 cost。
