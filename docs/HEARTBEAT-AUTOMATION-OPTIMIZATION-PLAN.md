# Heartbeat 与 Run Recovery 优化计划（Automation 已拆分）

状态：Run/Heartbeat 计划；Automation 已暂缓并拆入 `docs/AUTOMATION-TODO.md`
日期：2026-08-13
范围：Agent Heartbeat、wakeup/run 调度内核；Automation 仅保留架构边界说明
实施基线：Octopus `step-29-plugins` @ `58202426e54faf93b512954fa18fed3295305b9e`，对照当前上游控制面实现 `2d519f17fe6bcab33206cf7007411d780305a0a8`

## 1. 目标

本计划解决三个相互关联但不应混为一体的问题，并按依赖顺序分批实施：

1. Run 恢复必须能把已经产生明确终态、但仍显示为 `running` 的记录恢复到正确终态，并补齐相关清理动作。
2. Heartbeat 应在保留任务遗漏兜底能力的同时，避免没有可执行工作时启动 Agent Runtime、调用模型和消耗资源。
3. Automation 应成为独立、持久化、可审计的自动化工作领域，而不是继续依赖 `heartbeat` 中的 `source="automation"` 字符串表达业务身份；该工作已经暂缓，后续待办统一维护在 `docs/AUTOMATION-TODO.md`。

当前计划只继续维护 Run 终态、恢复和 Heartbeat。Automation 不属于当前交付范围，恢复实施时必须从 `docs/AUTOMATION-TODO.md` 建立独立实施批次。

目标状态：

```text
业务事件 / Heartbeat / Automation
              ↓
      持久化 wakeup 或 run intent
              ↓
       统一 admission / dispatcher
              ↓
         Agent Runtime 执行
              ↓
       终态、输出、审计和恢复
```

Heartbeat 回答“这个 Agent 是否仍有工作需要处理”；Automation 回答“这条预定义工作是否应在此刻执行”。两者可以共用调度和执行基础设施，但必须保持独立配置、判断规则和运行证据。

Run 恢复是两者共同依赖的基础。如果 Run 已实际完成却永久停留在 `running`，Heartbeat 会误判 Agent 忙碌，Automation 也可能错误跳过或合并后续执行。

## 2. 当前基线与主要缺口

### 2.1 Heartbeat

当前 Octopus 已具备：

- `agent_wakeup_requests`、`heartbeat_runs`、`heartbeat_run_events` 持久化；
- assignment、review、on-demand、内部 automation 等唤醒来源；
- queued run claim、每 Agent 并发限制、paused 延期、取消、重试和 orphan recovery；
- server lifespan 中的周期调度与 queued run 恢复；
- `waiting_for_children` 与 `issue_children_settled` 父任务续跑。

当前缺口：

- timer 只有 `runDiagnosticsOnTimer=true` 时才真正运行，默认不会承担任务遗漏兜底；
- `preflightEnabled` 虽然被配置和展示，但执行路径没有消费它；
- timer 没有根据 assignee/reviewer Issue 动态判断是否存在可执行工作；
- Heartbeat 指南中的默认值、环境变量和 preflight 描述与当前代码存在偏差；
- `lastHeartbeatAt` 容易同时承载“调度检查”和“真实运行活动”两种含义；
- wakeup 幂等主要依赖先查后写，缺少完整数据库唯一约束，并发下仍存在重复风险。

### 2.2 Automation

正式 Automation 领域尚未实现，并且不属于当前计划的交付范围。全部功能待办、前置条件和验收标准见 `docs/AUTOMATION-TODO.md`。

## 3. 设计原则

1. **上游契约优先。** 外部 schema、API、枚举、状态和关键副作用按当前上游控制面证据实现，不为 Python 重写发明另一套产品模型。
2. **事件驱动为主，周期扫描兜底。** Issue assignment、review、mention、approval 等事件应立即入队；Heartbeat 不应成为正常任务启动的主要路径。
3. **不空跑模型。** timer preflight 在数据库层完成；无可执行工作时记录 skipped evidence，不创建 Agent Run，不启动 Runtime。
4. **意图先持久化，再执行。** Scheduler 不直接启动 Agent；它只物化持久化意图，Dispatcher 负责准入和执行。
5. **一个调度宿主，多个领域 tick。** Heartbeat、Automation、scheduled wakeup、recovery 共享后台循环生命周期，但各自拥有独立 service 和规则。
6. **数据库保证幂等。** 关键 exactly-once/at-most-once 边界不能只依赖应用层先查询再插入。
7. **组织作用域贯穿全链路。** 定义、触发、运行、输出、密钥、Issue、Chat 和 Agent 均需验证 organization 边界。
8. **每种结果都有证据。** queued、running、completed、failed、skipped、coalesced、deferred 都必须可查询和解释。

## 4. 目标架构

### 4.1 后台调度宿主

```text
Scheduler Host
├─ recover_orphaned_runs(now)
├─ materialize_due_scheduled_wakeups(now)
├─ dispatch_queued_runs(now)
├─ tick_agent_heartbeats(now)
```

要求：

- 每个 tick 独立捕获错误，单个领域失败不得阻断其他领域；
- 所有时间判断使用显式 `now`，便于确定性测试；
- 调度循环支持协作式停止和 server restart recovery；
- PostgreSQL 多实例下使用条件更新、行锁或 `SKIP LOCKED` 保护领取；
- SQLite 保持开发兼容，但不把 SQLite 单进程结果当作并发正确性证明。

### 4.2 Run 终态与恢复

```text
Runtime 结束
  ↓
原子事务 / CAS
  ├─ running → succeeded / failed / timed_out / cancelled
  ├─ terminal_effects_pending = true
  └─ 保存待执行的终态副作用
  ↓
幂等补齐终态副作用
  ├─ 更新 wakeup
  ├─ 恢复 Agent 状态
  ├─ 释放 Issue 执行锁
  └─ 清理 Workspace/runtime resources
  ↓
terminal_effects_pending = false
```

这里的 terminal effects intent 只表示“Run 已进入终态后，还有哪些收尾动作待完成”，不是另一个 Run 目标状态字段。具体字段名、存储形态和 CAS 条件必须在 Phase 0 对照上游 schema、service 和 tests 后锁定；上图中的 `terminal_effects_pending` 是协议语义名称，不授权在未对照前自由增加字段。

必须区分两类记录：

1. **新产生的 Run：** Run 从 `running` 进入终态时，必须在同一原子事务中写入 Run 终态和待执行终态副作用。新代码不得再产生 `status=running` 但已有 `finishedAt` 的记录。
2. **已经存在的损坏记录：** 只有存在权威终态证据时，才能兼容修复到对应终态；如果只有 `finishedAt`、`exitCode` 或 `resultJson`，不能猜测成功，必须结合 execution lease、进程状态和恢复策略处理。

`waiting_for_children`、`issue_children_settled` 和 parent continuation 是 Octopus 的本地父子任务扩展，不属于本计划声明的当前上游兼容基线。其状态与并发加固在 Phase 1C 单独处理，不作为 Heartbeat 或 Automation 的前置条件。

### 4.3 Heartbeat 流程

```text
timer 到期
  ↓
检查 agent policy 和状态
  ↓
preflightEnabled ?
  ├─ yes → 查询可执行 assignee/reviewer work
  │          ├─ 无工作 → skipped wakeup，更新检查时间
  │          └─ 有工作 → queued wakeup/run
  └─ no  → queued wakeup/run
  ↓
Dispatcher执行预算、暂停、并发、Issue lease等准入
  ↓
Agent Runtime
```

可执行工作口径与当前上游保持一致：

- assignee Issue：`todo`、`in_progress`、`blocked`；
- reviewer Issue：`in_review`、`blocked`，排除已经记录过阻塞审核决定的重复工作；
- 已到期但尚未关联 Run 的 queued/deferred wakeup 不重复创建 timer Run，应优先恢复或跳过 timer 请求。

### 4.4 Automation 边界

Automation 已暂缓，目标流程和实施细节见 `docs/AUTOMATION-TODO.md`。当前只保留一条兼容边界：`agent_wakeup_requests.source="automation"` 是内部 Run 来源标记，不代表正式 Automation 产品对象。

## 5. 实施阶段

### Phase 0：锁定契约并修正文档

目标：在改代码前消除当前文档与实现的冲突。

任务：

- 对照当前上游 schema、shared validators、routes、services 和 tests，形成字段/状态/API 对照表；
- 锁定上游 Run 终态 CAS、terminal effects intent、recovery、claim 和 lease 的具体字段与算法；在完成对照前，不决定新增字段、锁类型或 migration 结构；
- 修正 `docs/guides/heartbeat-scheduler.md` 中环境变量、默认扫描周期、`intervalSec`、`preflightEnabled` 和 `runDiagnosticsOnTimer` 的当前行为说明；
- 明确 `runDiagnosticsOnTimer` 是 Octopus 扩展或旧配置兼容项，不将其描述为当前上游契约；再决定保留、迁移或弃用策略；
- 将 `waiting_for_children`、`issue_children_settled` 和 parent continuation 明确记录为 Octopus 本地扩展；
- 明确 Heartbeat 优化属于 Step 13 follow-up；

旧损坏 Run 的兼容恢复必须按以下证据优先级处理：

| 旧数据证据 | 处理方式 |
| --- | --- |
| Run 已是终态 | 以 Run 状态为准，只补齐 terminal effects |
| Run 为 `running`，存在可信的 `run succeeded` 终态事件 | 恢复为 `succeeded` |
| Run 为 `running`，存在可信的失败、超时或取消终态事件 | 恢复为对应终态 |
| 只有 `finishedAt`、`exitCode` 或 `resultJson` | 不猜测成功，继续按 lease、进程状态和 orphan recovery 判断 |
| 多个终态事件互相冲突 | 不自动修复；记录恢复错误并等待人工或后续专用修复流程处理 |
| Runtime 仍存活且 execution lease 有效 | 保持 `running` |
| Runtime 已消失且没有权威终态证据 | 按 orphan recovery 处理，不冒充成功 |

表中的“可信终态事件”必须在 Phase 0 对照上游事件结构、写入事务和唯一性保证后定义，不能只依赖任意 message 字符串匹配。

验收：

- 文档只描述已实现行为或明确标记目标行为；
- 外部契约差异均有上游代码或测试依据；
- Run 终态协议、terminal effects 和 lease/claim 实现均有上游字段或算法依据；Octopus 扩展被单独标记；
- 未以 `source="automation"` 代替 Automation 产品对象。

### Phase 1A：Run 原子终态与可恢复终态副作用

目标：先解决“Issue 已经完成，但 Run 仍为 `running`”及相关恢复一致性问题。

任务：

- 新产生的 Run 使用原子 CAS 从 `running` 写入真实终态，并在同一事务中持久化 terminal effects pending intent；
- terminal effects intent 只描述待执行收尾动作，不保存另一个 Run 目标状态；
- 将终态副作用设计为可重复执行：更新 wakeup、恢复 Agent 状态、释放 Issue execution/checkout lock、推进 deferred wakeup、释放 runtime services，并完成 Workspace 清理或 interrupted 标记；
- 对已经存在的损坏记录制定兼容恢复规则：有权威终态证据时恢复到对应终态；只有 `finished_at`、`exit_code` 或 `result_json` 时不猜测成功；
- 实现必须遵循 Phase 0 的“旧损坏 Run 证据优先级”表，包括冲突证据不自动修复、有效 lease 保持运行和无权威证据时进入 orphan recovery；
- 明确终态事务提交后、每个终态副作用执行前后的崩溃恢复顺序。

建议涉及：

- `server/services/heartbeat.py`
- `server/services/workspaces.py`
- `packages/database/queries/heartbeat.py`
- `packages/database/schema/heartbeat.py`
- `packages/database/schema/agent_state.py`
- `tests/workflows/test_step13_run_workflow.py`
- `tests/contract/test_step13_run_management.py`

验收：

- 当前未提交测试场景中的 Run 最终恢复为 `succeeded`，不再保持 `running`；
- 新执行路径不会产生 `status=running` 且 `finishedAt` 已存在的 Run；
- wakeup、Agent 状态、Issue 执行锁和 Workspace/runtime resources 与 Run 终态一致；
- 同一个恢复流程连续执行两次不会产生重复副作用；
- server 在终态写入和各项清理动作之间崩溃后，下一次恢复可以补齐剩余动作；
- 仅有 `finishedAt`、`exitCode` 或 `resultJson` 的损坏记录不会被误判为成功。

### Phase 1B：Execution lease、claim 与 wakeup 幂等

目标：确保 Dispatcher、Recovery、Heartbeat 和 Automation 可以安全共用 Run 执行基础设施。

任务：

- 按 Phase 0 锁定的上游算法实现或加固 Run execution lease 和原子 claim；
- 避免两个 worker 执行或收尾同一个 Run，并阻止 lease 失效的旧 worker 覆盖新 owner 的结果；
- 为 `agent_wakeup_requests` 的非空 idempotency key 增加数据库级唯一约束，约束键至少包含 Agent 作用域；
- 明确 scheduled wakeup、queued Run、running orphan 和 terminal effects pending 的恢复顺序；
- 所有 after-commit dispatch 都必须可由周期 reconciliation 补偿。

验收：

- 两个 recovery/dispatcher 同时扫描时，同一 Run 不会重复执行或重复收尾；
- 旧 worker 在 lease 失效后不能覆盖新 owner 的状态；
- 唯一冲突被解释为幂等命中，而不是暴露 500；
- server 在入队后和 dispatch 前崩溃时，周期 reconciliation 可以继续执行。

Phase 1A 和 1B 是 Heartbeat 与 Automation 的共同前置条件，必须独立测试和验收。

实施状态（2026-08-13）：第一版已在当前工作区按本节协议实现，原先“避免错误取消、但可能永久保留为 `running`”的临时处理已被替换。正式验收仍以原子终态 CAS、pending terminal effects、旧损坏 Run 证据优先级、execution lease 和数据库幂等约束为准。

### Phase 1C：Octopus 父子任务汇合扩展并发加固

性质：Octopus 本地扩展，不属于当前上游兼容功能，也不是 Heartbeat 或 Automation 的前置条件。

任务：

- 单独维护 `waiting_for_children`、`issue_children_settled` 和 parent continuation；
- 引入父级锁、completion generation 或等价唯一键，避免最后两个子任务并发完成时漏唤醒或重复唤醒；
- 不把父子汇合扩展字段或状态混入上游 Run 终态协议。

验收：

- PostgreSQL 双事务并发完成最后两个子任务时，父 continuation 恰好产生一次；
- 扩展关闭或未使用时，不影响普通 Run、Heartbeat 或 Automation 恢复。

#### Phase 1C 补充：原子拆分与父任务汇总所有权

父子汇合可靠性还要求“拆分结果先落库，再启动子任务”。本扩展不新增 plan/batch 表，也不依赖标题作为幂等键：

- 父 Agent 必须先生成完整的并行子任务集合，再通过一个批量接口在同一事务中写入全部 child Issue 和 assignment wakeup；禁止逐条创建同级子任务；
- 由活跃父 Run 创建的 child wakeup 先以 `deferred_parent_yield` 持久化，不生成或启动可执行 child Run；父 Agent 可以完成短暂评论和协调，再显式调用 `yield-children`；
- 父任务让出采用两阶段协议：第一阶段只持久化 `yield_requested_at`，父 Run 仍为 `running` 并继续持有执行租约和工作区锁；执行层通知 Adapter 停止并确认进程退出后，第二阶段才原子完成 `running → waiting_for_children`、终态副作用、父 Issue 执行锁释放和 deferred child wakeup 入队；事务提交后才允许 Dispatcher 启动子任务；
- 父协调窗口有固定上限。父 Adapter 未主动让出时，Run Recovery 先持久化同一让出请求；租约过期且 Runtime 已消失后才代为完成第二阶段。不能依赖模型自行退出，也不能在父进程仍存活时提前释放资源；
- 父 Issue 行锁是创建边界：若父任务已经存在可见子任务，普通重试直接返回已落库集合，不重新规划或补建另一批；单个子任务的重试或替换继续使用显式 retry/replace 流程；
- 父 continuation 发起 retry/replace 时，新执行同样先 deferred，父任务再次让出后才进入队列；replacement 必须隐藏旧 child，使旧 blocked/cancelled 记录不再参与当前父级汇合；
- 子任务只是实际可并行执行的工作，不创建“汇总、合并、报告”子任务；最后一批子任务结算后，由 parent continuation 读取子任务结果并在父任务中完成最终汇总；
- 普通 Heartbeat actionable 查询排除已有子任务的父 Issue，避免父任务在等待期间被当成普通工作再次启动；`issue_children_settled` continuation 是父任务恢复执行的主路径；
- Heartbeat/manual preflight 必须能够发现“父任务仍为 `todo/in_progress`、全部子任务已结算、当前 settlement generation 缺少 continuation”的历史记录，并按同一父级幂等键补建 continuation；
- Run 上下文和终态收尾统一使用 Issue UUID；identifier 只作为 API/CLI 输入别名，不能直接作为 execution lock、deferred wakeup 或 parent continuation 的数据库关联键。

补充验收：

- 同一父任务的批量创建请求重复执行（即使重试载荷标题变化）也只保留首个完整子任务集合；
- 批量中的任一 child/wakeup 创建失败时整批回滚，不留下部分子任务；
- 父任务让出前没有 child Run 可被 Dispatcher 领取；让出事务完成后 child Run 才统一进入 queued；父任务未主动让出时 Recovery 能在协调宽限期后完成同样交接；
- blocked child 的 retry/replace 不会在父 continuation 仍持有执行权时启动，replacement 后旧 child 不再计入 active/settled 汇合集合；
- 父任务等待子任务期间不会被 Heartbeat 普通预检重复运行；
- 全部子任务已结束但 continuation 丢失时，下一次 Heartbeat/manual preflight 能补建且只补建一次；
- 通过 identifier 执行或关闭子任务时，终态收尾仍能释放正确的 UUID 锁并唤醒父任务；
- 最终汇总产物属于父任务，不存在仅用于汇总的子 Issue。

### Phase 2：Heartbeat 语义对齐

目标：timer 到期时有工作才运行，无工作不启动模型。

任务：

- 在 Heartbeat policy 中真正解析并使用 `preflightEnabled`；
- 实现 assignee/reviewer actionable work 查询；
- 查询 pending runless wakeups，避免 timer 与已有请求竞争或重复；
- 无工作时写入 skipped wakeup evidence，并推进下一次 timer baseline；
- 将 Agent 的调度检查时间与真实运行活动时间分离，必要时新增内部字段或明确既有字段写入规则；
- 对 Octopus 扩展/旧配置 `runDiagnosticsOnTimer` 制定兼容迁移：读取旧配置但不继续作为默认产品语义，禁止让它绕过明确的资源控制预期；
- 保持 assignment/review/mention/approval 的即时唤醒路径不等待 timer。

验收：

- 无任务的 timer tick 不创建 `heartbeat_runs`，不调用 adapter；
- 存在 assignee/reviewer actionable work 时只创建一次 timer Run；
- preflight disabled 时保留明确的显式诊断语义；
- assignment wakeup 仍可立即启动，不依赖 timer；
- timer 与已有 queued/deferred wakeup 不产生重复执行；
- Heartbeat 创建的 Run 能通过 Phase 1A 和 Phase 1B 的恢复、lease 与幂等测试。

### Automation：已拆分并暂缓

Automation 的 Phase 3～Phase 7、数据模型、触发方式、输出路由、Webhook、安全、UI、测试和发布边界已经统一迁移到 `docs/AUTOMATION-TODO.md`。

Automation 不属于当前 Run/Heartbeat 交付范围。恢复实施前必须重新确认产品场景、前置能力和首个版本范围，并作为独立开发批次验收。

## 5.1 交付版本拆分

本计划按两个可独立实施、测试、验收和回滚的版本交付：

| 版本 | 包含阶段 | 核心结果 | 进入下一版的条件 |
| --- | --- | --- | --- |
| 第一版：Run 恢复安全 | Phase 0、Phase 1A、Phase 1B | Run 原子终态、可恢复 terminal effects、execution lease、claim 和 wakeup 幂等可靠 | 旧损坏 Run 可按证据安全恢复，新 Run 不再产生部分终态；并发与崩溃恢复验收通过 |
| 第二版：Heartbeat 节省资源 | Phase 2 | 有可执行工作才创建 Run；无工作记录 skipped，不启动 Runtime 或调用模型 | Heartbeat preflight、竞争和重启恢复验收通过 |

Run 恢复安全与 Heartbeat 节省资源必须分别汇报改动、验证和残余风险。Automation 已从本计划拆出，不再作为当前计划的“下一版”。

Phase 1C 是 Octopus 父子任务汇合扩展的独立维护批次，不属于以上两个主版本，也不阻塞第二版。它应单独排期、测试和验收；不得为了顺手处理而并入第一版 Run 恢复安全。

## 6. 测试矩阵

### 6.1 Run 终态与恢复

| 场景 | 期望 |
| --- | --- |
| Issue 已 done，Run 有明确成功终态但仍为 running | 恢复为 succeeded，不取消、不永久 running |
| 只有 finishedAt/exitCode/resultJson，没有明确终态 | 不猜测 succeeded，按进程与恢复规则处理 |
| 新 Run 正常完成 | 原子写入 Run 终态和 terminal effects pending intent |
| Run 已终态，wakeup/Agent/Issue 锁未收尾 | 幂等补齐剩余终态副作用 |
| recovery 连续执行两次 | 第二次 no-op，无重复事件或唤醒 |
| 两个 worker 同时恢复同一 Run | 只由一个有效 lease/claim 完成处理 |
| 旧 worker 在 lease 失效后迟到写入 | 不覆盖新 owner 的 Run 状态 |
| 终态写入后 server 崩溃 | 重启后补齐 Agent、Issue、Workspace 和 runtime resources |

### 6.2 Heartbeat

| 场景 | 期望 |
| --- | --- |
| timer 到期，无任何工作 | skipped wakeup；无 Run；adapter 未调用 |
| assignee 有 `todo` | 创建一个 timer Run并执行 |
| reviewer 有 `in_review` | 创建一个 timer Run并执行 |
| 只有 backlog/done/cancelled | 不启动 |
| 已有 queued runless wakeup | 不重复创建timer Run |
| Agent paused | 延期或跳过符合policy，不执行 |
| 预算hard-stop | 不执行并留下原因 |
| 两个scheduler同时tick | 最多一个有效Run |
| assignment 与timer竞争 | 同一Issue不重复执行 |
| server重启 | queued/scheduled/orphan状态可恢复 |

### 6.3 验证层级

1. Shared contract/validator tests。
2. Schema/migration tests，覆盖SQLite、PostgreSQL及项目承诺的MySQL范围。
3. Service tests，使用可控时间验证 preflight 和状态机。
4. PostgreSQL双连接并发测试，分别验证上游兼容的 claim/幂等，以及 Octopus 扩展的父子汇合。
5. API workflow tests，覆盖organization/permission/output路径。
6. 真实Runtime E2E，证明无任务不启动且任务可执行。
7. UI E2E，覆盖创建、暂停、触发、运行历史、错误和刷新恢复。

## 7. 发布与回滚策略

- Schema迁移先于功能开关发布，新增字段/表保持向后兼容；
- Heartbeat新preflight先提供实例级灰度开关和诊断日志，再成为默认；
- Octopus 扩展/旧配置 `runDiagnosticsOnTimer` 迁移期间只读兼容，禁止无提示改变现有Agent执行频率；
- 回滚时可关闭 Heartbeat timer，但不得删除 Run 和审计证据；
- 已创建的queued Run按明确策略继续、取消或保留，不允许静默丢弃。

## 8. 风险与待确认决策

1. **兼容目标：** `runDiagnosticsOnTimer` 明确属于 Octopus 扩展或旧配置兼容项；待 Phase 0 对照后决定保留、迁移或弃用。建议只做迁移兼容，不继续扩展产品含义。
2. **Heartbeat时间字段：** 是否新增独立scheduler checked字段，需先对照上游schema；如上游无字段，应优先保持外部schema并在内部runtime state或调度记录中保存。
3. **Automation排期：** 已暂缓并迁移到 `docs/AUTOMATION-TODO.md`；重新启动时再确认 Step、Webhook 前置依赖和首个交付范围。
4. **多数据库承诺：** MySQL 的 partial unique index 和 JSON 索引实现需要独立兼容设计，不能直接复制 PostgreSQL DDL。
5. **父子汇合并发：** `waiting_for_children`、`issue_children_settled` 和 parent continuation 是 Octopus 本地扩展，在 Phase 1C 独立加固；它们不是 Heartbeat 或 Automation 的前置条件。
6. **多实例部署：** 如果短期仍只承诺单实例，应在文档中明确；数据库约束仍应提前建立，避免未来迁移成本。

## 9. Definition of Done

以下条件全部满足后，改造才算完成：

- Heartbeat配置、代码、文档和UI语义一致；
- 已产生明确终态的 Run 不会永久停留在 `running`；
- 新 Run 通过原子 CAS 同时记录真实终态和 pending terminal effects，不产生新的部分终态损坏记录；
- Run 终态恢复能够补齐 wakeup、Agent、Issue lock、Workspace 和 runtime resource 状态；
- 无可执行任务时不会启动Agent Runtime；
- Issue assignment/review等实时事件不依赖timer；
- queued/deferred/orphan工作可在重启后恢复；
- 并发 scheduler 不会重复执行同一 wakeup 或 Run；
- organization、permission、budget、Agent 状态和 Issue lease 边界通过测试；
- PostgreSQL真实并发测试和真实Runtime E2E通过；
- `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest`、`uv run pyright .` 全部通过；
- `docs/FEATURE.md`、对应Step `TASK.md`、指南和实施记录已同步；
- 实现完成后先由用户确认，只有收到明确提交指令后才创建Git提交。

## 10. 推荐执行顺序摘要

```text
第一版：Run恢复安全
  Phase 0 → Phase 1A → Phase 1B → 独立验收

第二版：Heartbeat节省资源
  Phase 2 → 独立验收

Automation（暂缓）：
  见 docs/AUTOMATION-TODO.md，重新立项后独立实施和验收

独立维护批次（非前置）：
  Phase 1C：Octopus父子汇合扩展并发加固
```

Automation 不属于当前计划的后续开发步骤，也不应把相关逻辑继续加入现有大型 `heartbeat.py`。当前只维护 Run/Heartbeat 与独立的 Phase 1C 父子任务扩展；Automation 重新启动时按 `docs/AUTOMATION-TODO.md` 独立立项。
