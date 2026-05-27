# Step 13: Run 调度与恢复

状态：开发中

## 上游依据

- 参考工程：`D:\coding\rudder`
- 关键实现：`server/src/services/runtime-kernel/heartbeat.*.ts`、`server/src/routes/agents.management-routes.ts`
- 关键表结构：`packages/db/src/schema/agent_wakeup_requests.ts`、`packages/db/src/schema/heartbeat_runs.ts`

## 依赖边界

Step 11 已落地 agent wakeup、heartbeat run、run event 与实际 adapter 执行闭环，并已保留上游用于调度和恢复的字段：`idempotencyKey`、`coalescedCount`、`retryOfRunId`、process 与 context snapshot 字段。Step 12 Goal 能力已进入当前基线，但本步骤仅补齐这些既有运行 contract 对应的 server 行为，不重复建立基础运行模型，也不扩展 Goal 领域规则。

## 13A：队列、领取与幂等

- 按上游 `runtimeConfig.heartbeat.maxConcurrentRuns` 补齐每 agent 最大并发控制，采用默认值 `3`，并限制在 `1..10`。
- 当 agent 已达到运行并发上限时保留 `queued` run；在存在执行容量时领取并运行队列项。
- 领取动作必须以条件状态更新保护，避免同一 `queued` run 被重复执行。
- 按 wakeup 的 `idempotencyKey` 复用重复请求结果；对可合并的延期 wakeup 累计 `coalescedCount`。

## 13B：定时触发与延期恢复

- 补齐 heartbeat timer 的服务入口，按照 agent runtime heartbeat 配置创建 `timer` 来源的 wakeup/run。
- 保持 paused agent 的 wakeup 为 `deferred_agent_paused`，并提供 agent 恢复后重放延期 wakeup 的服务行为。
- 队列恢复只负责通用运行调度；需要 issue 专属执行上下文的 preflight/closeout 行为不在本步骤扩展。

## 13C：取消、重试与事件查询

- 新增 `POST /api/heartbeat-runs/{runId}/cancel`，取消 `queued` 或 `running` run，并同步 wakeup 状态及 lifecycle event；本地 runtime 会响应取消信号终止活跃 child process。
- 新增 `POST /api/heartbeat-runs/{runId}/retry`，仅允许 `failed`、`timed_out`、`cancelled` run 创建 recovery run，并保存 `retryOfRunId` 与 recovery context。
- 扩展 `GET /api/heartbeat-runs/{runId}/events` 支持 `afterSeq` 与 `limit`，供恢复和流式观察场景增量读取。
- 按上游活动语义记录 `heartbeat.cancelled` 与 `heartbeat.retried`。

## 13D：测试与实施记录

- Contract tests 覆盖路径、输入输出字段、取消/重试限制和 events 分页参数。
- Workflow tests 覆盖幂等 wakeup、并发排队与领取、paused 延期重放、timer 触发、取消和重试恢复。
- 开发完成后补充可执行 curl 验收 demo。

## 当前实施记录

- Shared 已新增 cancel/retry API path 与上游并发限制常量。
- Database query 已新增幂等 wakeup 查询、queued/running 查询、条件 claim 及增量 event 查询。
- Server 已将 HTTP wakeup/invoke/retry 改为先返回 `queued` run，再通过后台派发完成执行；Step 11 的手动执行 API 因此演进为可观察队列语义。
- Server 已实现 `idempotencyKey` 复用、paused wakeup 合并/恢复、per-agent 启动锁、队列恢复、timer tick、cancel/retry 路由、live child process interruption、recovery context 及 cancel/retry activity。
- Lifespan 已启动 heartbeat scheduler，按配置周期触发 timer、恢复持久化 queued run，并将启动时遗留的 `running` run 标记为 `process_lost` 后排入一次 automatic recovery。
- Tests 已覆盖 API path、scheduler 启动触发、幂等、已有并发占位下的排队恢复、paused 重放、cancel/retry、活跃 process 中断、orphaned run 自动恢复和增量 events。

## 待继续实现

- 当前已完成 orphaned `running` 状态识别与单次 automatic recovery；尚未持久化并安全核验 child PID，因此 server 重启后遗留的 OS 级孤儿进程主动终止仍待继续实现。

## Scheduler 配置

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED` | `true` | 是否在 server lifespan 启动 heartbeat scheduler |
| `OCTOPUS_HEARTBEAT_SCHEDULER_INTERVAL_SECONDS` | `5` | timer 检查与 queued run 恢复周期，最小 `0.1` 秒 |

## 不包含

- 新 adapter 或 runtime 类型实现，归 Step 14。
- workspace 创建、释放、产物和日志存储闭环，归 Step 15。
- budget/cost/activity 治理联动，归 Step 16。
- issue 专属运行治理、automation 调度实体及依赖其领域规则的 closeout；仅保留本步骤通用调度语义。

## 验收

- 相同 `idempotencyKey` 不创建重复运行；竞争领取不重复执行同一 run。
- 达到并发限制的 run 保持排队，释放容量后可恢复运行。
- paused wakeup 能在恢复后重放；timer 能基于已配置 agent 触发运行。
- 运行可取消、终态可重试，恢复 run 保留原始 run 关联与 recovery context；安全的 orphan child process 终止完成后再关闭本步骤。
- events 支持增量读取，Step 11 已建立的存储 contract 不发生破坏性变化。

## Curl 验收 Demo

启动服务：

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
$env:OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED = "1"
$env:OCTOPUS_HEARTBEAT_SCHEDULER_INTERVAL_SECONDS = "0.2"
uv run server
```

创建可取消的长运行 agent，并触发/取消一次 run：

```powershell
$base = "http://127.0.0.1:8000"
$python = (Get-Command python).Source
$org = curl.exe -s -X POST "$base/api/orgs" -H "Content-Type: application/json" -d '{"name":"Run Recovery Demo"}' | ConvertFrom-Json
$body = @{
  name = "Cancelable Runner"
  runtimeConfig = @{ heartbeat = @{ enabled = $true; intervalSec = 60; maxConcurrentRuns = 1 } }
  agentRuntimeConfig = @{ command = $python; args = @("-c", "import time; time.sleep(30)") }
} | ConvertTo-Json -Depth 5 -Compress
$agent = curl.exe -s -X POST "$base/api/orgs/$($org.id)/agents" -H "Content-Type: application/json" -d $body | ConvertFrom-Json
$run = curl.exe -s -X POST "$base/api/agents/$($agent.id)/wakeup" -H "Content-Type: application/json" -d '{"idempotencyKey":"cancel-demo"}' | ConvertFrom-Json
Start-Sleep -Milliseconds 300
curl.exe -s -X POST "$base/api/heartbeat-runs/$($run.id)/cancel"
curl.exe -s "$base/api/heartbeat-runs/$($run.id)/events?afterSeq=0&limit=20"
```

预期结果：触发响应初始为 `queued`，取消响应和后续详情状态为 `cancelled`，events 包含 `run started` 与 `run cancelled`。
