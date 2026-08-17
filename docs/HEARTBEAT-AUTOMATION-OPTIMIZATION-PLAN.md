# Heartbeat 与 Automation 优化计划

状态：实施准备就绪（必须从 Phase 0 开始）  
日期：2026-08-13  
范围：Agent Heartbeat、wakeup/run 调度内核、Automation 独立领域  
实施基线：Octopus `step-29-plugins` @ `58202426e54faf93b512954fa18fed3295305b9e`，对照当前上游控制面实现 `2d519f17fe6bcab33206cf7007411d780305a0a8`

## 1. 目标

本计划解决三个相互关联但不应混为一体的问题，并按依赖顺序分批实施：

1. Run 恢复必须能把已经产生明确终态、但仍显示为 `running` 的记录恢复到正确终态，并补齐相关清理动作。
2. Heartbeat 应在保留任务遗漏兜底能力的同时，避免没有可执行工作时启动 Agent Runtime、调用模型和消耗资源。
3. Automation 应成为独立、持久化、可审计的自动化工作领域，而不是继续依赖 `heartbeat` 中的 `source="automation"` 字符串表达业务身份。

实施顺序固定为：先完成 Run 终态与恢复，再优化 Heartbeat，最后实现 Automation。三者可以放在同一总体计划中，但不得在同一个实现批次中混合交付。

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

当前 Octopus 只有 `automation` invocation source 和内部 passive follow-up，不具备正式 Automation 领域。

当前缺失：

- Automation definition、trigger、run 三类持久化对象；
- Automation 管理 API、权限与 activity；
- Cron、时区、next-run、catch-up 和并发策略；
- 手动/API/Webhook 触发；
- tracked Issue 与 Chat 两种输出路由；
- Automation run 历史、跳过、合并、失败和恢复证据；
- Webhook 密钥、签名、重放窗口和幂等边界。

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
└─ tick_automation_triggers(now)
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

### 4.4 Automation 流程

```text
Schedule / Manual / API / Webhook
              ↓
         automation_runs
              ↓
      concurrency / idempotency gate
              ↓
       output routing decision
          ├─ track_issue
          │    ↓
          │  创建 Issue → assignment wakeup → Agent Run
          └─ chat_output
               ↓
             创建每次运行独立 Chat → Chat Agent execution
```

`agent_wakeup_requests.source="automation"` 只表示下游 Agent 唤醒来源；Automation 的身份、触发和终态必须以 `automation_runs` 为准。

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
- 在开始 Automation 实施前，先更新 `docs/FEATURE.md`，新增独立 Step 和目录映射。建议在 Step 30 之后建立 `step-31-automations/`，因为完整 Webhook/secret/actor 能力依赖 Step 30；如果只先做 schedule/manual core，则在 Step 31 中显式记录 Webhook 后置依赖。

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

### Phase 3：Automation 数据与共享契约

目标：建立独立、兼容、可审计的 Automation 领域基础。

任务：

- 新增 `automations`、`automation_triggers`、`automation_runs` schema 和 migrations；
- 在 `packages/shared/` 增加 API paths、types、constants 和 validators；
- 保持 organization、project、goal、parent Issue、assignee Agent 关联边界；
- 定义 Automation 状态、trigger kind、run status、output mode、concurrency policy 和 catch-up policy；
- 为 trigger/idempotency、public webhook id、next-run 扫描建立索引和唯一约束；
- Goal dependency query 返回真实 Automation 依赖，而不是固定空数组。

验收：

- schema/API shape 与锁定的上游版本一致；
- migration 在 SQLite、PostgreSQL、MySQL 支持范围内通过；
- 跨 organization 引用被拒绝；
- 删除或修改关联对象时遵循明确的阻止、级联或置空契约。

### Phase 4：Automation 定义、触发与调度

目标：完成 schedule、manual/API 的最小可靠闭环。

建议服务边界：

```text
server/services/automations/
├─ definitions.py
├─ triggers.py
├─ scheduler.py
├─ dispatch.py
├─ output_routing.py
└─ recovery.py
```

任务：

- 实现 Automation CRUD、pause/resume 和 trigger CRUD；
- 实现 Cron validation、timezone 和 `nextRunAt` 计算；
- 使用条件更新原子领取到期 trigger；
- 实现 `skip_missed` 和有上限的 missed-run catch-up；
- 实现 manual/API trigger 和调用方 idempotency key；
- 实现 `coalesce_if_active`、`skip_if_active`、`always_enqueue`；
- skipped/coalesced 也必须持久化 Automation Run 和原因；
- 独立 tick 失败不得阻断 Heartbeat 和 queued dispatch。

验收：

- 相同 schedule tick 在并发 scheduler 下只触发一次；
- 服务重启后 `nextRunAt` 正确恢复；
- DST、无效时区、错过周期和 catch-up 上限有确定性测试；
- active work 下三种并发策略分别留下正确运行证据。

### Phase 5：Automation 输出路由

目标：Automation 结果进入真实 Issue 或 Chat 工作闭环。

任务：

- `track_issue`：创建带 Automation origin metadata 的 Issue，保存 `linkedIssueId`，再复用普通 assignment wakeup；
- `chat_output`：每个真实 Automation Run 创建独立 conversation，保存 `linkedChatConversationId`，通过 Chat assistant/runtime 路径执行；
- coalesced/skipped Run 不创建空 Issue 或空 Chat；
- 同步 Automation Run 与关联 Issue/Chat/Agent Run 的终态；
- 失败时保留可见错误和部分输出，不生成无证据的成功状态；
- activity 中记录定义变更、触发、跳过、合并、输出创建和终态。

验收：

- tracked Issue 可从 Automation Run 导航并完成普通执行/审核闭环；
- chat output 每次运行使用独立 Chat，刷新后仍可读取结果；
- Agent paused、预算阻断、并发饱和和 Runtime失败都有正确 Automation Run 状态；
- Automation 不绕过 Agent、Issue、Chat、预算或organization权限。

### Phase 6：Webhook 与安全边界

前置：Step 30 的真实 actor/access/secret 能力可用。

任务：

- 创建不可预测 public id；
- 使用 organization secret 保存 Bearer/HMAC材料；
- 实现 timestamp/replay window、常量时间签名比较和请求大小限制；
- 支持外部 idempotency key；
- 旋转密钥时保留必要审计，不回传旧密钥；
- rate limit、失败日志和敏感字段脱敏。

验收：

- 正确签名触发一次；重复请求幂等；
- 过期、篡改、跨organization和已禁用trigger均被拒绝；
- 日志、activity、API响应不泄漏secret。

### Phase 7：UI、可观测性与迁移

任务：

- Heartbeat设置页分别解释 timer enabled、interval、preflight 和 on-demand，不使用“总开关”误导用户；
- Automation 列表/详情展示定义、trigger、next run、最近运行、跳过/合并原因和输出链接；
- Run详情区分 invocation source 与 Automation业务身份；
- 为旧 `runDiagnosticsOnTimer` 配置提供一次性迁移或兼容读取，并记录弃用策略；
- 对已有 `source="automation"` passive follow-up 保持兼容，但UI标记为系统收尾，不伪装成用户Automation；
- 增加scheduler tick、due count、skip reason、queue latency和run outcome指标。

验收：

- 用户可以明确看出“定时检查但未运行”“因无工作跳过”“Automation触发但合并”等不同状态；
- 重启、刷新和重新打开后状态与运行历史一致；
- 旧数据不被错误归类成Automation定义或Automation Run。

## 5.1 交付版本拆分

本计划按三个可独立实施、测试、验收和回滚的版本交付：

| 版本 | 包含阶段 | 核心结果 | 进入下一版的条件 |
| --- | --- | --- | --- |
| 第一版：Run 恢复安全 | Phase 0、Phase 1A、Phase 1B | Run 原子终态、可恢复 terminal effects、execution lease、claim 和 wakeup 幂等可靠 | 旧损坏 Run 可按证据安全恢复，新 Run 不再产生部分终态；并发与崩溃恢复验收通过 |
| 第二版：Heartbeat 节省资源 | Phase 2 | 有可执行工作才创建 Run；无工作记录 skipped，不启动 Runtime 或调用模型 | Heartbeat preflight、竞争和重启恢复验收通过 |
| 第三版：Automation | Phase 3～Phase 7 | 独立 Automation definition、trigger、run、输出、安全、UI 和可观测性闭环 | Automation 各阶段验收、PostgreSQL 并发和真实 Runtime E2E 通过 |

每一版完成后必须单独汇报改动、验证和残余风险，并由用户确认后才能进入下一版。三个版本不得合并成一次大改动或一次统一验收。

Phase 1C 是 Octopus 父子任务汇合扩展的独立维护批次，不属于以上三个主版本，也不阻塞第二版或第三版。它应单独排期、测试和验收；不得为了顺手处理而并入第一版 Run 恢复安全。

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

### 6.3 Automation

| 场景 | 期望 |
| --- | --- |
| Cron正常到期 | 一个Automation Run |
| 两个scheduler领取同一tick | 恰好一个有效trigger claim |
| active + coalesce | 新Run记录coalesced并指向活动Run |
| active + skip | 新Run记录skipped和原因 |
| active + always enqueue | 新Run正常排队 |
| missed schedule | 按catch-up policy跳过或有限补跑 |
| tracked Issue输出 | 创建Issue并走assignment执行链 |
| Chat输出 | 创建独立conversation并保存结果 |
| Webhook重复 | 同一幂等键只执行一次 |
| Webhook签名/时间错误 | 拒绝且不产生有效Run |
| 跨organization引用 | 422/403，且无跨域写入 |
| Runtime失败/进程丢失 | Run失败可读，恢复策略明确 |

### 6.4 验证层级

1. Shared contract/validator tests。
2. Schema/migration tests，覆盖SQLite、PostgreSQL及项目承诺的MySQL范围。
3. Service tests，使用可控时间验证Cron、preflight、catch-up和状态机。
4. PostgreSQL双连接并发测试，分别验证上游兼容的 claim/幂等，以及 Octopus 扩展的父子汇合。
5. API workflow tests，覆盖organization/permission/output路径。
6. 真实Runtime E2E，证明无任务不启动、任务可执行、Automation可产出Issue/Chat。
7. UI E2E，覆盖创建、暂停、触发、运行历史、错误和刷新恢复。

## 7. 发布与回滚策略

- Schema迁移先于功能开关发布，新增字段/表保持向后兼容；
- Heartbeat新preflight先提供实例级灰度开关和诊断日志，再成为默认；
- Octopus 扩展/旧配置 `runDiagnosticsOnTimer` 迁移期间只读兼容，禁止无提示改变现有Agent执行频率；
- Automation scheduler初始默认关闭，完成数据迁移和真实环境验收后再启用；
- Webhook最后启用，且必须依赖secret和actor边界完成；
- 回滚时可关闭Heartbeat timer或Automation scheduler，但不得删除定义、Run和审计证据；
- 已创建的queued Run按明确策略继续、取消或保留，不允许静默丢弃。

## 8. 风险与待确认决策

1. **兼容目标：** `runDiagnosticsOnTimer` 明确属于 Octopus 扩展或旧配置兼容项；待 Phase 0 对照后决定保留、迁移或弃用。建议只做迁移兼容，不继续扩展产品含义。
2. **Heartbeat时间字段：** 是否新增独立scheduler checked字段，需先对照上游schema；如上游无字段，应优先保持外部schema并在内部runtime state或调度记录中保存。
3. **Automation排期：** 完整Webhook依赖Step 30；schedule/manual core可以先实现，但必须在Step映射中声明拆分边界。
4. **多数据库承诺：** MySQL的Cron claim、partial unique index和JSON索引实现需要独立兼容设计，不能直接复制PostgreSQL DDL。
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
- 并发scheduler不会重复执行同一wakeup、Run或Automation tick；
- Automation具有独立definition、trigger、run和输出证据；
- schedule/manual/API/Webhook及两种输出模式符合锁定的上游契约；
- organization、permission、budget、Agent状态、Issue lease和secret边界通过测试；
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

第三版：Automation
  Phase 3 → Phase 4 → Phase 5 → Phase 6 → Phase 7 → 独立验收

独立维护批次（非前置）：
  Phase 1C：Octopus父子汇合扩展并发加固
```

不建议先开发 Heartbeat preflight 或 Automation UI，也不建议直接把 Automation 逻辑继续加入现有大型 `heartbeat.py`。先交付并验收第一版 Run 恢复安全，再实施第二版 Heartbeat 节省资源，最后实施第三版 Automation。Phase 1C 是 Octopus 父子任务扩展，始终独立排期。
