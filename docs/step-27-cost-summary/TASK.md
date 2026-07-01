# Step 27: Cost Events / Cost Summary

状态：已完成基础开发

## 已提前完成

- Runtime adapter 已经能从部分本地 CLI 输出中归一化 `usage_json`、`costUsd`、provider、biller 等原始证据，但这些仍只停留在 run/result 或 adapter response 中。
- `runtime_providers` / `runtime_models` 的 CRUD 与 activity 写入已在 Step 21 提前完成；这为后续 cost by provider/model 提供配置维度，但不等同于 cost event 归集。
- Step 25 负责 activity query；本步骤可以复用 activity 写入能力记录 `cost.reported`。

## 目标

实现不阻塞主链路的 cost event 归集和成本摘要查询，让用户能看见 agent/run/chat 消耗了多少，并为 Step 28 budget/governance 提供成本事实来源。

本步骤只做 cost event、summary/query 和 monthly spend 回写；budget hard-stop、incident、quota、skills analytics 归 Step 28。

## 上游证据

- `D:\coding\upstream-reference\packages\db\src\schema\cost_events.ts`
- `D:\coding\upstream-reference\server\src\routes\costs.ts`
- `D:\coding\upstream-reference\server\src\services\costs.ts`
- `D:\coding\upstream-reference\packages\shared\src\types\cost.ts`
- `D:\coding\upstream-reference\packages\shared\src\validators\cost.ts`

## 任务

### 27A: Cost event contract 与持久化

作用：把 runtime/run/chat 上报的成本事实落成独立 `cost_events`，作为 Step 28 budget/governance 的唯一成本事实来源。

修改范围：

- `packages/shared/api_paths/costs.py`：新增 cost event 与 summary 路径常量。
- `packages/shared/types/cost.py`：新增 cost event payload、event response、summary row 类型。
- `packages/shared/validators/cost.py`：校验 cost event 创建 payload 和 summary query 参数。
- `packages/database/schema/costs.py`：新增 `CostEvent` 表。
- `packages/database/migrations/versions/20260608_000019_cost_events.py`：创建表和索引。
- `packages/database/queries/costs.py`：封装 create/list/aggregate query。
- `tests/contract/test_step27_cost_summary.py`：先覆盖 cost event 创建和 schema 行为。

验收：

- `POST /api/orgs/{orgId}/cost-events` 支持 board 上报 organization 内任意 agent cost。
- agent actor 只能上报自己的 cost，不能替其他 agent 或跨 organization 上报。
- 创建 cost event 后写入 `cost.reported` activity。
- 创建 cost event 后回写 `organizations.spent_monthly_cents` 和 `agents.spent_monthly_cents`。

### 27B: Cost summary/query API

作用：提供不阻塞主链路的成本看板数据，让用户按 agent/provider/biller/project/model/window 查看支出。

接口：

- `GET /api/orgs/{orgId}/costs/summary`
- `GET /api/orgs/{orgId}/costs/by-agent`
- `GET /api/orgs/{orgId}/costs/trend`
- `GET /api/orgs/{orgId}/costs/by-agent-model`
- `GET /api/orgs/{orgId}/costs/by-provider`
- `GET /api/orgs/{orgId}/costs/by-biller`
- `GET /api/orgs/{orgId}/costs/window-spend`
- `GET /api/orgs/{orgId}/costs/by-project`

查询约定：

- 所有查询保持 organization scope。
- 支持 `startTime`、`endTime`、`agentId`、`projectId`、`provider`、`biller`、`model` 和 `limit`。
- cost 统一以 cents 聚合；原始 cost USD 和 usage 保留在 event detail 中。
- 空 provider/biller/project/model 使用 `unattributed` 分桶，避免 UI 端自行猜测。

### 27C: Runtime 成本归集入口

作用：复用已有 adapter `usage_json` / `result_json` 原始证据，在 run 完成后尽量归集 cost event；归集失败不能影响 run 成功状态。

修改范围：

- `server/services/heartbeat.py`：run 完成后从 `usage_json`、`result_json`、runtime provider config 中提取 cost/provider/model/biller，调用 `CostService.record_run_cost_if_present()`。
- 归集失败只写 warning/log，不抛出到主 run 流程。

### 27D: UI / CLI

作用：让本地开发者和用户能直接查看成本，不需要查数据库。

UI：

- 在 organization 级设置或 observability 页面增加成本摘要入口。
- 展示总成本、本月窗口、by-agent、by-provider、by-biller、by-project。
- 所有金额以美元展示，后端仍返回 cents。

CLI：

- 新增 `cost` 命令组：
  - `cost report --org-id ... --agent-id ... --cost-cents ...`
  - `cost summary --org-id ...`
  - `cost by-agent --org-id ...`
  - `cost by-provider --org-id ...`
  - `cost by-biller --org-id ...`
  - `cost by-project --org-id ...`

## 剩余待开发

- 更丰富的成本趋势可视化、预算 hard-stop、quota window 和 incident 仍按 Step 28 边界处理。
- 当前 Step 27 已提供 cost event、summary/query、runtime run cost best-effort 归集、UI 设置页摘要和 CLI 查询/上报。

## 完成记录

- 新增 `cost_events` schema、migration、query、service、route、shared type/validator。
- 新增 `POST /api/orgs/{orgId}/cost-events` 和成本 summary/by-agent/trend/by-agent-model/by-provider/by-biller/window-spend/by-project 查询。
- 创建 cost event 后写入 `cost.reported` activity，并回写 organization/agent monthly spend。
- heartbeat run 完成后会从 `usage_json` / `result_json` best-effort 归集 runtime cost；归集失败只写 warning，不影响 run 状态。
- UI 组织设置页新增“成本”section，展示 summary 和 agent/provider/biller/project 维度。
- CLI 新增 `cost report`、`cost summary`、`cost by-agent`、`cost by-provider`、`cost by-biller`、`cost by-project`、`cost by-agent-model`、`cost trend`、`cost window-spend`。

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
- Tests 覆盖 UI API client 路径和 CLI cost 命令 payload。
- `uv run pyright .`、`uv run ruff check .`、后端 contract tests、UI typecheck/test 必须通过。
