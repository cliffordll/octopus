# Heartbeat Run / Scheduler / Agent Wakeup Bug 清单

这份清单记录当前讨论中暴露出的产品语义、架构边界和实现风险。它不是提交计划，只是后续开发和审核的 bug/设计债列表。

## BUG-1：Agent 页面同时暴露“唤醒”和“运行心跳”

状态：待修复  
优先级：P1

### 问题

Agent 页面同时有两个按钮：

```text
唤醒
运行心跳
```

但当前实现里两者都接近 agent 级 no-issue run：

| 按钮 | 接口 | 语义 |
| --- | --- | --- |
| 唤醒 | `POST /api/agents/{id}/wakeup` | 通用 wakeup，可带 payload/context |
| 运行心跳 | `POST /api/agents/{id}/heartbeat/invoke` | on-demand heartbeat invoke，body 为空 |

两者都不是“执行某个 issue”。

### 影响

用户会误以为：

- “唤醒”是让 agent 去找任务。
- “运行心跳”是另一个独立能力。
- 两个按钮一个可能执行任务，一个可能只是健康检查。

实际不是。

### 建议

UI 只保留一个 agent 级操作：

```text
运行诊断
```

说明文案：

```text
启动一次无任务 agent run，用于验证 runtime、provider、control-plane 和 agent 配置是否正常；不会执行具体 issue。
```

后端两个接口可以先保留：

- `/heartbeat/invoke`：UI 手动诊断入口。
- `/wakeup`：内部/CLI/自动化/带 payload 的程序化唤醒入口。

## BUG-2：“心跳”文案过度暴露底层概念

状态：待修复  
优先级：P1

### 问题

当前 UI 大量使用：

```text
心跳
定时心跳
运行心跳
心跳策略
心跳上下文
```

但底层 `heartbeat` 在当前框架里表示 agent runtime 的一次执行记录，不只是传统意义的 heartbeat packet / keepalive。

### 影响

用户难以理解：

- heartbeat run 为什么会执行 agent。
- heartbeat run 和 issue run 是什么关系。
- timer heartbeat 是否等于任务调度。
- Run heartbeat 是否等于执行任务。

### 建议

保留底层命名，调整用户文案：

| 当前文案 | 建议文案 |
| --- | --- |
| 心跳 | 运行记录 |
| 定时心跳 | 定时巡检 |
| 运行心跳 | 运行诊断 / 测试启动 |
| 心跳策略 | 巡检策略 |
| 心跳上下文 | 运行上下文 |

## BUG-3：inbox 容易被误解成执行队列

状态：待修复  
优先级：P1

### 问题

`agent inbox` 实际是待办视图：

```text
分配给 agent 的 issue
需要 agent review 的 issue
相关 comment wakeup
```

它不是 queued run，也不是 dispatcher 的输入。

### 影响

容易形成错误设计：

```text
scheduler 定时唤醒 agent
agent 查询 inbox
agent 自己决定执行哪个任务
```

这会把任务调度责任从 server 转移给 agent，导致边界混乱。

### 建议

文档和 UI 明确：

```text
inbox = 待办视图
queued run = 执行队列
dispatcher = 启动 queued run
```

常规任务必须由 server 侧事件创建 queued run。

## BUG-4：scheduler 巡检唤醒被误认为任务调度主链路

状态：待修复  
优先级：P1

### 问题

当前“定时心跳 / scheduler 巡检唤醒”容易被理解成：

```text
每 300 秒唤醒 agent
agent 自己查有没有任务
agent 自己执行
```

这不是理想主链路。

### 影响

- 任务执行延迟到 timer 周期。
- agent 侧承担过多调度判断。
- `OCTOPUS_SANDBOX_DIR`、inbox、heartbeat run 概念被混在一起。

### 建议

明确：

```text
任务调度主路径 = server 事件创建 queued run + dispatcher 启动
scheduler 巡检唤醒 = 低频兜底/诊断/健康检查
```

如果所有任务事件都已事件化，timer 巡检应弱化或默认关闭。

## BUG-5：OCTOPUS_SANDBOX_DIR 容易被误解为 issue workspace

状态：待修复  
优先级：P1

### 问题

`OCTOPUS_SANDBOX_DIR` 的真实用途是 no-issue heartbeat run 的安全 cwd。

它不应该用于：

- issue run 工作区。
- control-plane shim 查找。
- `.env` 查找。
- 任务产物目录。
- 分支隔离。

### 影响

容易把 615B4C-2 这类 issue run env/control-plane 问题误归因到 sandbox。

### 建议

文档和代码注释明确：

```text
OCTOPUS_SANDBOX_DIR only provides cwd for no-issue heartbeat runs.
```

issue run 应使用 issue execution workspace / git worktree。

## BUG-6：`/wakeup` 与 `/heartbeat/invoke` API 语义重叠

状态：待决策  
优先级：P2

### 问题

两个接口最终都会创建 agent wakeup/run：

```text
/api/agents/{id}/wakeup
/api/agents/{id}/heartbeat/invoke
```

上游也保留两个接口，但 UI 主操作只暴露 `Run heartbeat`。

### 影响

如果 UI 同时暴露两个入口，会制造重复概念。

### 建议

短期：

- 保留两个 API。
- UI 只用 `/heartbeat/invoke` 作为“运行诊断”。
- `/wakeup` 留给 CLI/内部/自动化/带 payload 的程序化入口。

长期可以考虑：

- 明确 route doc。
- 对 `/wakeup` payload schema 增加更强语义。
- 避免 UI 直接使用无 payload wakeup。

## BUG-7：默认 300s timer 巡检可能制造无意义 run

状态：待决策  
优先级：P2

### 问题

如果所有任务来源都已经通过 server 事件创建 queued run，那么周期性 no-issue timer heartbeat 的价值会下降。

### 影响

- 产生无任务 run。
- 消耗 runtime/provider quota。
- 干扰用户理解运行记录。
- 需要 `OCTOPUS_SANDBOX_DIR` 兜底 cwd。

### 建议

评估是否：

- 默认关闭 timer 巡检。
- 延长默认周期。
- 仅在诊断/开发模式启用。
- UI 明确叫“定时巡检”，并说明不会执行具体任务。

## BUG-8：615B4C-2 暴露 runtime env / control-plane path 指引不清

状态：已修复待审核  
优先级：P0

### 问题

智能体可能错误地：

```text
读取 workspace .env
硬编码 workspace/.octopus/bin/control-plane
```

但当前 runtime 实际应该：

```text
通过进程 env 注入 OCTOPUS_*
通过 PATH 调用 control-plane
```

### 影响

当 workspace 和 runtime home 分离时，agent 会找错 env 或 control-plane，导致 issue run 失败。

### 建议

保留当前修复方向：

- runtime prompt 明确 Runtime Context Contract。
- skill 文档禁止读 workspace `.env`。
- CLI 支持从 env 默认读取 agent/run/org。
- control-plane 从 PATH 调用。

## BUG-9：运行记录页面没有区分 issue run / diagnostic run / timer inspection

状态：待修复  
优先级：P2

### 问题

所有 run 都叫 heartbeat，用户无法快速判断这条 run 是：

- 执行任务。
- 执行 review。
- 自动收口 followup。
- 手动诊断。
- 定时巡检。

### 影响

排查时容易混淆 cwd、context、收尾逻辑和错误归因。

### 建议

UI 使用 `run_purpose`、`invocation_source`、`context_snapshot.issueId` 显示明确标签：

| 条件 | 标签 |
| --- | --- |
| 有 issueId + task_execution | 任务执行 |
| 有 issueId + review | 评审运行 |
| 有 issueId + closeout_followup | 自动收口 |
| 无 issueId + invocation_source=timer | 定时巡检 |
| 无 issueId + invocation_source=on_demand | 运行诊断 |

## BUG-10：文档中“heartbeat”与“agent heartbeat”术语需要收敛

状态：待修复  
优先级：P2

### 问题

不同文档里可能把 heartbeat 分别描述为：

- 心跳机制。
- 执行框架。
- timer heartbeat。
- agent wakeup。
- run 记录。

### 影响

读者无法判断 heartbeat 到底指哪一层。

### 建议

以后文档中优先使用更具体的术语：

```text
heartbeat run
issue run
no-issue heartbeat run
timer inspection
wakeup request
runtime diagnostic run
```

不要单独写“heartbeat”而不加限定。

## 不建议做的改动

当前不建议：

- 不把 `heartbeat_runs` 改成 `agent_runs`。
- 不把 `HeartbeatService` 改名。
- 不删除 `/api/heartbeat-runs`。
- 不删除 `OCTOPUS_SANDBOX_DIR`。
- 不把 agent 级 wakeup 当成任务执行入口。
- 不让 agent 通过 inbox 自己决定主任务调度。

## 推荐实施顺序

1. 先改 UI 文案和按钮：合并“唤醒/运行心跳”为“运行诊断”。
2. 再改运行记录标签：区分任务执行、评审、自动收口、定时巡检、运行诊断。
3. 再评估 timer 巡检默认策略：是否默认关闭或延长周期。
4. 最后再整理 API 文档：明确 `/wakeup` 与 `/heartbeat/invoke` 的边界。
