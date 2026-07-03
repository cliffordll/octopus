# Heartbeat Run、Scheduler、Dispatcher、Inbox 与 OCTOPUS_SANDBOX_DIR 架构说明

这份文档整理当前问答后的统一理解。目标是把几件容易混淆的事分开：

- scheduler 是怎么发现该推进的事情的。
- dispatcher 是怎么启动 queued run 的。
- inbox 到底是什么。
- heartbeat run 为什么既包含 issue run，也包含 no-issue run。
- `OCTOPUS_SANDBOX_DIR` 到底在哪些场景使用。

本文不建议重命名底层表、API 或 Service。当前底层仍保持上游语义：`heartbeat` 是 agent runtime 执行框架名，不只是“300 秒心跳”。

## 1. 总结结论

当前系统应按下面三层理解：

```text
调度层：
  scheduler / dispatcher
  决定什么时候该启动 run

执行层：
  HeartbeatService / heartbeat_runs
  记录并执行一次 agent run

工作区层：
  issue workspace / heartbeat sandbox workspace / managed runtime home
  给 runtime 子进程提供 cwd、env 和工具
```

关键结论：

- 常规任务执行应该由 server 侧 scheduler / dispatcher 判断并启动，不应该靠 agent 醒来后自己查 inbox 作为主路径。
- `inbox` 是待办视图，不是执行队列。
- `heartbeat_runs` 是统一运行记录表，里面既有 issue run，也有 no-issue heartbeat run。
- `OCTOPUS_SANDBOX_DIR` 只用于 no-issue heartbeat run 的安全 cwd。
- 任务代码分支隔离问题应该由 issue execution workspace / git worktree 解决，不应该由 `OCTOPUS_SANDBOX_DIR` 解决。

## 2. 术语表

| 术语 | 含义 | 是否主路径 | 说明 |
| --- | --- | --- | --- |
| scheduler | 周期性调度器 | 是 | 定期扫描系统状态，做恢复、timer 巡检、scheduled wakeup materialize、queued run dispatch 兜底 |
| dispatcher | 派发逻辑 | 是 | 非常驻；有任务入队或 run 结束后被调用，尝试启动 queued run |
| heartbeat run | agent 一次运行记录 | 是 | `heartbeat_runs` 表中的 run；可能有 issue，也可能没有 issue |
| issue run | 带 issue 上下文的 heartbeat run | 是 | 执行具体 issue，应该使用 issue workspace |
| no-issue heartbeat run | 不带 issue 上下文的 heartbeat run | 兜底/巡检 | 没有 issue workspace，需要 heartbeat sandbox cwd |
| 巡检唤醒 | scheduler 发起的 no-issue wakeup | 兜底/巡检 | 不应该作为“找任务”的主路径 |
| inbox | agent 的待办视图 | 否 | 用于 UI/agent 查看事项，不是执行队列 |
| queued run | 等待执行的 run | 是 | dispatcher 的输入，来自 `heartbeat_runs.status = queued` |
| scheduled wakeup | 未来某个时间点应转成 run 的唤醒请求 | 是 | 存在 `agent_wakeup_requests.status = scheduled` |
| issue workspace | issue 执行 cwd | 是 | 具体任务的代码/文件/产物目录 |
| heartbeat sandbox workspace | no-issue run 的安全 cwd | 兜底/巡检 | 来源于 `OCTOPUS_SANDBOX_DIR` |
| managed runtime home | runtime 工具和 agent home | 是 | 放 control-plane shim、skills、runtime home，不等于任务 workspace |

## 3. 主路径：具体 issue 怎么被执行

常规任务执行不应该依赖 agent 自己醒来查 inbox，而应该由 server 侧事件和调度逻辑直接创建 run。

典型链路：

```text
issue 创建 / 分配 / 评论 @agent / review / 自动收口 followup
  -> server 创建 wakeup request 或 queued run
  -> dispatcher 被调用
  -> dispatcher 检查 agent 并发上限
  -> claim queued heartbeat run
  -> HeartbeatService 执行 run
  -> runtime adapter 启动 agent CLI 子进程
  -> 子进程 cwd 使用 issue workspace
  -> agent 执行具体 issue
  -> agent 用 octopus issue done/block/comment/review 回写结果
  -> run 结束后再调用 dispatcher，继续派发同 agent 的下一条 queued run
```

这个路径里：

- scheduler / dispatcher 负责判断“有没有该跑的 run”。
- agent 不需要先查 inbox 才知道有没有任务。
- `heartbeat_runs` 记录这次执行。
- 因为 run 有 issue 上下文，所以 cwd 应该是 issue workspace。

## 4. scheduler 到底怎么扫

当前 scheduler 不是把所有业务表无脑扫一遍。它主要做两类事情。

### 4.1 timer 巡检：按组织和 agent 扫

入口是 server lifespan 里的 scheduler loop：

```text
recover_orphaned_runs()
list_organizations()
for each org:
  HeartbeatService.tick_timers(org.id)
dispatch_all_queued_runs()
sleep(interval)
```

`tick_timers(org.id)` 会：

```text
list_org_agents(org_id)
for each agent:
  读取 agent.runtime_config.heartbeat
  对比 agent.last_heartbeat_at / created_at 和 interval
  检查是否已有 active timer run
  如果到期，创建 timer wakeup / queued heartbeat run
```

涉及表：

```text
organizations
agents
heartbeat_runs
agent_wakeup_requests
```

### 4.2 queued / scheduled 推进：按状态索引查

这部分不是按组织 agent 全扫，而是直接查 due/queued 状态记录。

```text
agent_wakeup_requests
  where status = scheduled
  and requested_at <= now

heartbeat_runs
  where status = queued
  and requested_at <= now
select distinct agent_id
```

然后对这些 agent 调 dispatcher。

所以准确说：

```text
timer 巡检：
  scheduler 按 org -> agent 扫

任务队列推进：
  scheduler 直接查 scheduled wakeup / queued run
```

## 5. dispatcher 是什么

`dispatcher` 不是常驻进程，也不是另一个 scheduler。

它是一段“尝试启动 queued run”的逻辑，触发时机包括：

- 新任务入队后。
- run 结束后。
- scheduler 周期性兜底时。

它做的事：

```text
给定 agent_id
  -> 查这个 agent 是否 paused / terminated / pending_approval
  -> 查这个 agent 当前 running run 数量
  -> 计算是否还有并发容量
  -> 查 heartbeat_runs.status = queued 的 run
  -> claim 为 running
  -> 调 runtime adapter 执行
```

所以排队任务不是靠 dispatcher “一直盯着”。它是被事件或 scheduler 兜底调用。

## 6. inbox 是什么

`inbox` 是待办视图，不是执行队列。

当前 `octopus agent inbox` 调的是：

```text
GET /api/agents/me/inbox-lite
  -> AgentService.list_inbox()
  -> 查 issues
  -> 查 comment wakeups
```

它主要返回：

```text
分配给这个 agent 的 issue
需要这个 agent review 的 issue
和这个 agent 相关的 blocked/comment wakeup
```

它和 queued run 的区别：

| 概念 | 面向谁 | 作用 |
| --- | --- | --- |
| inbox | UI / agent | 展示有哪些事项需要关注 |
| queued run | scheduler / dispatcher | 决定实际要启动哪次执行 |
| heartbeat run | 执行系统 | 记录一次真实 agent 运行 |

因此：

```text
inbox 不是调度入口。
agent 醒来后查 inbox 不应该是常规任务启动方式。
```

如果 server 已经知道 issue 分配、评论、review、自动收口 followup，就应该直接创建 queued run，而不是先启动一个 no-issue run 再让 agent 查 inbox。

## 7. scheduler 巡检唤醒到底干什么

`scheduler 巡检唤醒` 是 scheduler 发起的一类 no-issue agent run。

它不是常规任务执行主路径。

更合理的定位是：

```text
低频兜底 / 健康检查 / 兼容未事件化的边缘检查
```

它不应该承担：

```text
扫描所有 issue
自己判断谁该执行
直接启动 agent
```

这类“该执行什么任务”的判断，应该在 server 的 scheduler / dispatcher / issue wakeup service 中完成。

巡检唤醒可以保留的场景：

- 检查 agent runtime 是否还能启动。
- 恢复某些漏掉的 wakeup。
- 兼容还没完全事件化的后台检查。
- 做非常低频的 agent 自检。
- 作为开发阶段的诊断入口。

但如果所有任务来源都已经事件化并能创建 queued run，周期性 no-issue 巡检唤醒就可以弱化，甚至关闭。

## 8. scheduler 巡检唤醒是不是通过 CLI 实现

不是。

scheduler 不调用 `octopus` CLI。

实际链路是：

```text
server scheduler loop
  -> HeartbeatService.tick_timers()
  -> HeartbeatService.wakeup()
  -> 写 agent_wakeup_requests
  -> 写 heartbeat_runs(status=queued)
  -> dispatch_all_queued_runs()
  -> dispatch_queued_agent(agent_id)
  -> HeartbeatService.execute_claimed_run()
  -> get_runtime_adapter(agent.agent_runtime_type)
  -> adapter.execute(context)
  -> runtime adapter 启动 codex / opencode / claude / process 子进程
```

`octopus` CLI 是 agent 子进程启动后用来和 server 通信的工具，不是 scheduler 的实现方式。

## 9. 为什么 no-issue run 需要 OCTOPUS_SANDBOX_DIR

runtime adapter 会启动真实的 agent CLI 子进程。子进程必须有 cwd。

issue run 有 issue workspace：

```text
issue run
  -> 有 issueId
  -> 能解析 issue workspace
  -> 子进程 cwd = issue workspace
```

但巡检唤醒没有 issue：

```text
scheduler 巡检唤醒
  -> no-issue heartbeat run
  -> 没有 issueId
  -> 不能解析 issue workspace
  -> 仍然要启动 agent 子进程
  -> 子进程需要 cwd
  -> 使用 heartbeat sandbox workspace
```

这个 heartbeat sandbox workspace 的根目录来自 `OCTOPUS_SANDBOX_DIR`。

它解决的是：

```text
无 issue agent 子进程不能继承 server cwd
```

如果没有它，开发环境里子进程可能继承：

```text
D:\coding\octopus
```

于是 agent 会误把 Octopus 自己的仓库当作工作区，可能读写错误文件或执行错误 git 操作。

## 10. OCTOPUS_SANDBOX_DIR 的实际使用场景

`OCTOPUS_SANDBOX_DIR` 只应该用于 no-issue heartbeat run。

包括：

| 场景 | 是否使用 `OCTOPUS_SANDBOX_DIR` | 原因 |
| --- | --- | --- |
| scheduler 巡检唤醒 | 是 | 没有 issue workspace，但要启动 agent 子进程 |
| 手动无任务唤醒 agent | 是 | 没有 issue workspace |
| agent 健康检查 / 能力检查 run | 是 | 没有具体 issue cwd |
| 具体 issue 执行 | 否 | 应该使用 issue workspace |
| review run | 否 | 有 issue/review 上下文，应使用 issue workspace |
| 自动收口 followup run | 通常否 | 如果是针对具体 issue 的 followup，应使用 issue workspace |
| shared workspace 任务 | 否 | 使用项目配置的 shared cwd |
| isolated workspace 任务 | 否 | 使用 issue 级 git worktree |

路径形态：

```text
<OCTOPUS_SANDBOX_DIR or ~/.octopus-sandboxes>/
  <instance>/
    organizations/
      <org-id>/
        agents/
          <workspace-key>/
            heartbeat-workspace/
```

如果候选路径位于某个 git 仓库内部，系统会退回临时目录下的安全路径，避免把仓库目录当 no-issue cwd。

## 11. OCTOPUS_SANDBOX_DIR 不解决什么

它不解决任务代码分支隔离。

以前如果有“代码分支频繁被切换”的问题，现在正确解法应该是：

```text
issue execution workspace
git worktree
workspace policy
branch guard
```

不是 `OCTOPUS_SANDBOX_DIR`。

`OCTOPUS_SANDBOX_DIR` 也不是：

- 不是 issue workspace。
- 不是 project workspace。
- 不是 managed runtime home。
- 不是 control-plane shim 路径。
- 不是 `.env` 来源。
- 不是任务产物目录。
- 不是 agent 长期记忆目录。

## 12. managed runtime home、issue workspace、sandbox workspace 的区别

| 概念 | 放什么 | 用途 |
| --- | --- | --- |
| managed runtime home | runtime 工具、control-plane shim、skills、agent home、缓存 | 让 agent CLI 能启动并具备工具 |
| issue workspace | issue 代码、文件、产物 | 让 agent 执行具体任务 |
| heartbeat sandbox workspace | no-issue run 的隔离 cwd | 防止无 issue 子进程继承 server cwd |

一句话：

```text
runtime home 是工具环境；
issue workspace 是具体任务现场；
heartbeat sandbox workspace 是无任务运行的安全落脚点。
```

## 13. 表和写入关系

主要表：

| 表 | 谁写入 | 用途 |
| --- | --- | --- |
| `agent_wakeup_requests` | `HeartbeatService.wakeup()`、scheduled followup 逻辑、issue wakeup service | 记录唤醒请求、去重、延迟触发、状态流转 |
| `heartbeat_runs` | `HeartbeatService` | 记录一次 agent run，包含 queued/running/succeeded/failed 等状态 |
| `heartbeat_run_events` | `HeartbeatService` | 记录 run 的 lifecycle、log、workspace、adapter 事件 |
| `agents` | AgentService / HeartbeatService | agent 配置、状态、`last_heartbeat_at` |
| `issues` | IssueService / HeartbeatService | issue 状态、assignee/reviewer、execution lock |

典型写入：

```text
创建唤醒：
  agent_wakeup_requests
  heartbeat_runs(status=queued)

派发执行：
  heartbeat_runs(status=running)
  agents(status=running, last_heartbeat_at=now)
  heartbeat_run_events(run started / adapter invocation)

执行结束：
  heartbeat_runs(status=succeeded/failed/...)
  agent_wakeup_requests(status=completed/failed/...)
  agents(status=idle)
  heartbeat_run_events(final events)
```

## 14. 排查口径

先判断 run 有没有 issue 上下文。

```text
有 issueId / issue context:
  这是 issue run
  查 issue workspace / env 注入 / control-plane PATH / 收尾逻辑

没有 issueId / issue context:
  这是 no-issue heartbeat run
  查 heartbeat sandbox workspace / OCTOPUS_SANDBOX_DIR / 是否误当 issue run
```

对于 615B4C-2 这类问题：

```text
智能体读 workspace .env
或硬编码 workspace/.octopus/bin/octopus
```

这不是 `OCTOPUS_SANDBOX_DIR` 的问题。

正确修复方向是：

- runtime 通过进程 env 注入 `OCTOPUS_*`。
- control-plane 从 PATH 调用。
- skill / prompt 禁止读取 workspace `.env`。
- CLI 支持从 env 默认读取 agent/run/org 上下文。

## 15. 最终设计边界

当前推荐边界：

```text
server 负责判断该执行什么：
  scheduler / issue wakeup service / dispatcher

agent 负责执行已分配的工作：
  issue run / review run / followup run

inbox 负责展示待办：
  不作为常规调度入口

OCTOPUS_SANDBOX_DIR 负责 no-issue run 安全 cwd：
  不参与 issue workspace 和分支隔离
```

因此，不应该设计成：

```text
每 300 秒唤醒所有 agent
agent 自己查 inbox
agent 自己决定有什么任务要做
```

更合理的是：

```text
server 侧事件和调度逻辑创建具体 queued run
有 queued run 才启动对应 agent
run 结束后继续 dispatch 同 agent 的下一条 queued run
no-issue 巡检唤醒只作为低频兜底/诊断/健康检查
```

## 16. 上游 `Run heartbeat` 的含义

上游项目也保留 `heartbeat` 这个底层框架名，并且 UI 里有 `Run heartbeat` 操作。

上游链路可以概括为：

```text
AgentActionsMenu -> Run heartbeat
  -> agentsApi.invoke(agent.id, orgId)
  -> POST /agents/:id/heartbeat/invoke
  -> heartbeat.invoke(agentId, "on_demand", context, "manual", actor)
  -> enqueueWakeup(...)
  -> 创建 agent_wakeup_requests
  -> 创建 heartbeat_runs
  -> 启动 runtime adapter
```

它的语义是：

```text
手动运行一次 agent runtime，记录为 heartbeat run。
```

它不是：

```text
执行一个具体 issue。
```

默认情况下，它没有：

- `issueId`
- issue workspace
- issue checkout ownership
- issue done/block/review 收尾责任

所以中文产品语义不应该翻成“执行任务”。更准确的用户理解是：

```text
运行诊断 / 测试启动 / 手动运行一次 agent runtime
```

如果用户要执行具体任务，入口应该是 issue 级操作，例如：

```text
执行此任务
重新派发此任务
请求 reviewer 评审
触发自动收口 followup
```

这些入口必须携带 issue context，并使用 issue workspace。

## 17. Agent 页面按钮设计建议

当前 Octopus Agent 页面同时存在：

```text
唤醒
运行诊断
```

这两个按钮在产品语义上高度重叠。当前实现中：

| 按钮 | 接口 | 实际效果 |
| --- | --- | --- |
| 唤醒 | `POST /api/agents/{id}/wakeup` | 创建一次 agent wakeup / heartbeat run，可接受 payload |
| 运行诊断 | `POST /api/agents/{id}/heartbeat/invoke` | 创建一次 on-demand diagnostic run，body 为空 |

两者都不是“执行某个 issue”。

上游保留两个 API，但 UI 主操作只暴露一个 `Run heartbeat`。因此当前 Octopus UI 不应该同时暴露两个按钮。

推荐产品调整：

```text
删除“唤醒”按钮
保留一个 agent 级操作，文案改为“运行诊断”或“测试启动”
```

推荐按钮说明：

```text
启动一次无任务 agent run，用于验证 runtime、provider、control-plane 和 agent 配置是否正常；不会执行具体 issue。
```

后端接口可以先保留：

| 接口 | 推荐定位 |
| --- | --- |
| `/heartbeat/invoke` | UI 手动诊断入口 |
| `/wakeup` | 内部、CLI、自动化或带 payload/context 的程序化唤醒入口 |

不要把 agent 级 wakeup 设计成任务执行入口。任务执行应该走 issue 级 run。

## 18. 文案边界

底层可以继续叫：

```text
heartbeat_runs
HeartbeatService
/api/heartbeat-runs
```

但用户界面应该尽量避免把所有东西都叫“心跳”。建议：

| 底层概念 | UI/文档推荐文案 |
| --- | --- |
| heartbeat run | 运行记录 |
| timer heartbeat | 定时巡检 |
| Run heartbeat | 运行诊断 / 测试启动 |
| wakeup | 唤醒请求 / 运行请求，视场景而定 |
| no-issue heartbeat run | 无任务诊断 run / 巡检 run |
| issue heartbeat run | 任务运行 / issue run |

核心原则：

```text
面向开发者可以说 heartbeat；
面向用户要说这次 run 到底是在执行任务、巡检，还是诊断。
```
