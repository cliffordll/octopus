# Heartbeat Run / Scheduler / Agent Wakeup Bug 清单

这份清单记录当前讨论中暴露出的产品语义、架构边界和实现风险，并同步本轮处理状态。

本轮最终模型：

- 导航入口叫“心跳”。它是智能体健康和运行监控入口，不等同于 `heartbeat_runs`。
- `heartbeat.enabled=true` 表示状态检测开启，默认每 300s 检查一次。
- 状态检测不默认启动真实 agent run。
- `runDiagnosticsOnTimer=true` 才允许 timer 到点创建真实 no-issue diagnostic run；默认关闭。
- 手动“运行诊断”继续调用 `/api/agents/{id}/heartbeat/invoke`。
- 任务主链路仍是 server 侧创建 queued run，再由 dispatcher 启动；不是 agent 定时查 inbox 后自行决定任务。
- 底层继续保留 `HeartbeatService`、`heartbeat_runs`、`/api/heartbeat-runs`。

## BUG-1：Agent 页面同时暴露“唤醒”和“运行诊断”

状态：已解决
优先级：P1

### 本轮处理

Agent 页面只保留一个 agent 级手动操作：

```text
运行诊断
```

它调用：

```text
POST /api/agents/{id}/heartbeat/invoke
```

语义：启动一次无任务 agent run，用于验证 runtime、provider、control-plane 和 agent 配置；不会执行具体 issue。

### 保留边界

- `/heartbeat/invoke`：UI 手动诊断入口。
- `/wakeup`：内部、CLI、自动化、带 payload 的程序化唤醒入口；不在 Agent 页面作为普通按钮暴露。

### 验收点

- Agent 页面不存在“唤醒”按钮。
- Agent 页面不存在“运行诊断”按钮。
- Agent 页面只展示“运行诊断”。
- 点击“运行诊断”只请求 `/api/agents/{id}/heartbeat/invoke`。

## BUG-2：“心跳”文案需要重新定义为上层监控概念

状态：已解决
优先级：P1

### 问题

如果把“心跳”等同于 `heartbeat_runs`，用户会误以为：

- 300s 心跳会执行任务。
- Run heartbeat 是任务执行。
- timer heartbeat 是任务调度主链路。

### 本轮处理

“心跳”保留为导航入口，但重新定义为上层监控概念：

```text
心跳 = 状态检测 + 运行记录 + 运行诊断入口
```

用户文案收敛为：

| 场景 | 文案 |
| --- | --- |
| 组织导航入口 | 心跳 |
| 300s 轻量检查 | 状态检测 |
| 真实 agent run 列表 | 运行记录 |
| 手动 no-issue run | 运行诊断 |
| timer 真实诊断 run | 定时诊断 |
| Issue run context | 运行上下文 |
| Agent 配置区 | 心跳策略 |

### 验收点

- 组织导航显示“心跳”。
- 心跳页面标题显示“心跳”。
- 心跳页面内的真实 run 区域叫“运行记录”。
- Agent 页详情导航使用“运行记录”，和组织心跳页分区保持一致。

## BUG-3：inbox 容易被误解成执行队列

状态：设计已澄清，代码无变更
优先级：P1

正确边界：

```text
inbox = 待办视图
queued run = 执行队列
dispatcher = 启动 queued run
```

常规任务必须由 server 侧事件创建 queued run，再由 dispatcher 启动。

## BUG-4：scheduler 巡检唤醒被误认为任务调度主链路

状态：已解决
优先级：P1

正确边界：

```text
任务调度主路径 = server 事件创建 queued run + dispatcher 启动
scheduler 300s 状态检测 = 低成本健康/状态检查
定时诊断 run = 显式开启后的 no-issue agent run
```

本轮处理：

- `heartbeat.enabled` 默认 true，表示状态检测开启。
- `intervalSec` 默认 300。
- `runDiagnosticsOnTimer` 默认 false，避免默认创建 no-issue run。
- `tick_timers` 只有在 `runDiagnosticsOnTimer=true` 时才创建 timer diagnostic run。

## BUG-5：OCTOPUS_SANDBOX_DIR 容易被误解为 issue workspace

状态：设计已澄清，代码无变更
优先级：P1

`OCTOPUS_SANDBOX_DIR` 只服务 no-issue diagnostic/timer diagnostic run 的安全 cwd。

它不应该用于：

- issue run 工作区。
- control-plane shim 查找。
- `.env` 查找。
- 任务产物目录。
- 分支隔离。

## BUG-6：`/wakeup` 与 `/heartbeat/invoke` API 语义重叠

状态：已解决 UI 入口，API 保留
优先级：P2

本轮处理：

- Agent 页面移除对 `/wakeup` 的直接调用。
- Agent 页面“运行诊断”只调用 `/heartbeat/invoke`。
- API 不删除，避免破坏 CLI/内部/自动化路径。

## BUG-7：默认 300s timer 产生无意义 no-issue run

状态：已解决
优先级：P2

本轮处理：

- 保留 300s 心跳，但语义改为状态检测。
- 新 agent 默认 `heartbeat.enabled=true`。
- 新 agent 默认 `runDiagnosticsOnTimer=false`。
- 默认不会每 300s 创建 no-issue run。
- 用户显式开启定时运行诊断后，timer 才会创建真实 agent run。
- 手动“运行诊断”不受定时诊断开关影响。

## BUG-8：615B4C-2 暴露 runtime env / control-plane path 指引不清

状态：已修复待审核
优先级：P0

当前修复方向保持不变：

- runtime prompt 明确 Runtime Context Contract。
- skill 文档禁止读 workspace `.env`。
- CLI 支持从 env 默认读取 agent/run/org。
- control-plane 从 PATH 调用。

## BUG-9：运行记录没有区分任务执行 / 诊断 / 定时诊断

状态：已解决
优先级：P2

统一展示标签：

| 条件 | 标签 |
| --- | --- |
| task execution + issue context | 任务执行 |
| review | 评审运行 |
| closeout followup / `issue_passive_followup` | 自动收口 |
| timer diagnostic run | 定时诊断 |
| on-demand no-issue run | 运行诊断 |
| heartbeat + issue context | 任务运行 |
| heartbeat + no issue context | 无任务运行 |

## BUG-10：文档中 heartbeat 术语需要加限定

状态：已解决本轮文档，后续持续执行
优先级：P2

以后文档中优先使用更具体术语：

```text
heartbeat monitor
status check
heartbeat run
issue run
no-issue diagnostic run
timer diagnostic run
wakeup request
runtime diagnostic run
```

## 本轮不建议做的改动

- 不把 `heartbeat_runs` 改成 `agent_runs`。
- 不把 `HeartbeatService` 改名。
- 不删除 `/api/heartbeat-runs`。
- 不删除 `OCTOPUS_SANDBOX_DIR`。
- 不把 agent 级 wakeup 当成任务执行入口。
- 不让 agent 通过 inbox 自己决定主任务调度。

## 本轮验收标准

代码验收：

1. 组织导航入口叫“心跳”。
2. 心跳页说明 300s 状态检测不等于执行任务。
3. 心跳页内真实 run 区域叫“运行记录”。
4. Agent 页详情导航使用“运行记录”。
5. Agent 配置区使用“心跳策略”，包含“状态检测”“状态检测间隔秒数”“定时运行诊断”“运行诊断”。
6. 新 agent 默认开启状态检测：`enabled=true, intervalSec=300`。
7. 新 agent 默认关闭定时诊断：`runDiagnosticsOnTimer=false`。
8. `tick_timers` 默认不创建 no-issue run；只有显式 `runDiagnosticsOnTimer=true` 才创建 timer diagnostic run。
9. 运行记录标签能区分“任务执行 / 评审运行 / 自动收口 / 定时诊断 / 运行诊断”。
10. 不改底层数据库表名、服务名和 API 路由。

验证命令：

```text
cd ui
npm run typecheck
npm test -- agent-page.test.tsx heartbeat-runs-page.test.tsx issue-page.test.tsx projects-page.test.tsx --reporter=dot

cd ..
uv run pytest tests/workflows/test_step13_run_workflow.py tests/contract/test_step13_run_management.py tests/contract/test_database_session_cleanup.py::test_heartbeat_scheduler_recovers_orphaned_runs_on_each_tick
```