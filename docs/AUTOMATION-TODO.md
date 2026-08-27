# Automation TODO

状态：暂缓，未排期
拆分日期：2026-08-24
来源：`docs/HEARTBEAT-AUTOMATION-OPTIMIZATION-PLAN.md` 原 Phase 3～Phase 7

## 1. 为什么暂缓

Automation 是独立产品领域，不是当前任务执行链的必要前置条件。普通 Issue 分配、子任务批量创建、父任务 continuation、Heartbeat preflight、`RunExecutionService`、`RunFinalizationService` 和 `RunRecoveryService` 均不依赖正式 Automation。

当前优先级是继续加固已有执行链，尤其是 Workspace 并发准备、Run 启动前异常收口以及 SQLite 开发环境下的写锁竞争。等产品明确需要定时报表、API 触发或 Webhook 自动执行时，再启动本 TODO。

当前代码中的 `invocation_source="automation"` 只是内部恢复或系统收尾 Run 的来源标记，不代表已经实现本文所述的 Automation 产品功能。

## 2. 目标

Automation 用于保存一项可重复触发的固定工作，并在定时、手动、API 或 Webhook 触发后，创建可审计的 Automation Run，再通过统一 `RunDispatchService` 调用 Agent。

```text
Automation definition
        ↓
Schedule / Manual / API / Webhook
        ↓
Automation Run
        ↓
concurrency / idempotency gate
        ↓
Issue output 或 Chat output
        ↓
Agent Run
```

Heartbeat 回答“Agent 当前是否有遗漏工作”；Automation 回答“预定义工作是否应在此刻执行”。两者可以共用 wakeup、`RunDispatchService`、`RunExecutionService`、`RunFinalizationService` 和 `RunRecoveryService`，但必须拥有独立配置、状态和运行证据。

## 3. 前置条件

- Run 终态 CAS、terminal effects、execution lease 和 claim 已稳定；
- wakeup 幂等和 queued Run reconciliation 已稳定；
- Heartbeat 与真实执行活动的语义已经分离；
- 完整 Webhook 需要真实 actor、access 和 secret 能力；
- 开始实施前更新 `docs/FEATURE.md`，为 Automation 建立独立 Step 和目录映射。

## 4. Phase 3：数据与共享契约

目标：建立独立、兼容、可审计的 Automation 领域基础。

待办：

- 新增 `automations`、`automation_triggers`、`automation_runs` schema 和 migrations；
- 在 `packages/shared/` 增加 API paths、types、constants 和 validators；
- 定义 Automation 状态、trigger kind、run status、output mode、concurrency policy 和 catch-up policy；
- 保持 organization、project、goal、parent Issue 和 assignee Agent 的关联边界；
- 为 trigger/idempotency、public webhook id 和 next-run 扫描建立索引与唯一约束；
- Goal dependency query 返回真实 Automation 依赖。

验收：

- schema 和 API shape 与实施时锁定的上游版本一致；
- migration 覆盖 SQLite、PostgreSQL 以及项目承诺的 MySQL 范围；
- 跨 organization 引用被拒绝；
- 删除或修改关联对象时具有明确的阻止、级联或置空规则。

## 5. Phase 4：定义、触发与调度

目标：完成 schedule、manual 和 API 的最小可靠闭环。

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

待办：

- 实现 Automation CRUD、pause/resume 和 trigger CRUD；
- 实现 Cron validation、timezone 和 `nextRunAt`；
- 使用条件更新原子领取到期 trigger；
- 实现 `skip_missed` 和有上限的 missed-run catch-up；
- 实现 manual/API trigger 和调用方 idempotency key；
- 实现 `coalesce_if_active`、`skip_if_active`、`always_enqueue`；
- skipped/coalesced 也持久化 Automation Run 和原因；
- Automation tick 独立失败，不阻断 Heartbeat、Recovery 和 queued dispatch。

验收：

- 相同 schedule tick 在并发 scheduler 下只触发一次；
- 服务重启后 `nextRunAt` 正确恢复；
- DST、无效时区、错过周期和 catch-up 上限具有确定性测试；
- 三种并发策略均留下正确运行证据。

## 6. Phase 5：输出路由

目标：让 Automation 结果进入真实 Issue 或 Chat 工作闭环。

待办：

- `track_issue`：创建带 Automation origin metadata 的 Issue，保存 `linkedIssueId`，再复用普通 assignment wakeup；
- `chat_output`：每个真实 Automation Run 创建独立 conversation，保存 `linkedChatConversationId`，再走 Chat Agent execution；
- coalesced/skipped Run 不创建空 Issue 或空 Chat；
- 同步 Automation Run 与关联 Issue、Chat、Agent Run 的终态；
- 失败时保留可见错误和部分输出，不生成无证据成功；
- activity 记录定义变更、触发、跳过、合并、输出创建和终态。

验收：

- tracked Issue 可导航并完成普通执行及审核闭环；
- chat output 每次运行使用独立 Chat，刷新后仍可读取；
- Agent paused、预算阻断、并发饱和和 Runtime 失败具有正确状态；
- Automation 不绕过 Agent、Issue、Chat、预算或 organization 权限。

## 7. Phase 6：Webhook 与安全

前置：真实 actor、access 和 secret 能力可用。

待办：

- 创建不可预测 public id；
- 使用 organization secret 保存 Bearer/HMAC 材料；
- 实现 timestamp/replay window、常量时间签名比较和请求大小限制；
- 支持外部 idempotency key；
- 旋转密钥时保留必要审计，不回传旧密钥；
- 增加 rate limit、失败日志和敏感字段脱敏。

验收：

- 正确签名只触发一次，重复请求幂等；
- 过期、篡改、跨 organization 和禁用 trigger 均被拒绝；
- 日志、activity 和 API 响应不泄漏 secret。

## 8. Phase 7：UI、可观测性与迁移

待办：

- Automation 列表和详情展示定义、trigger、next run、最近运行及输出链接；
- 支持创建、编辑、暂停、恢复和手动运行；
- 展示失败、跳过、合并及其原因；
- Run 详情区分 invocation source 与 Automation 业务身份；
- 旧 `source="automation"` passive follow-up 继续标记为系统收尾，不归类成用户 Automation；
- 增加 tick、due count、skip reason、queue latency 和 run outcome 指标。

验收：

- 用户能区分触发、排队、运行、跳过、合并和失败；
- 刷新或重启后定义与运行历史一致；
- 旧数据不会被错误归类成 Automation definition 或 Automation Run。

## 9. 测试清单

| 场景 | 期望 |
| --- | --- |
| Cron 正常到期 | 创建一个 Automation Run |
| 两个 scheduler 领取同一 tick | 恰好一个有效 trigger claim |
| active + coalesce | 新 Run 记录 coalesced 并指向活动 Run |
| active + skip | 新 Run 记录 skipped 和原因 |
| active + always enqueue | 新 Run 正常排队 |
| missed schedule | 按 catch-up policy 跳过或有限补跑 |
| tracked Issue 输出 | 创建 Issue 并走 assignment 执行链 |
| Chat 输出 | 创建独立 conversation 并保存结果 |
| Webhook 重复 | 同一幂等键只执行一次 |
| Webhook 签名或时间错误 | 拒绝且不产生有效 Run |
| 跨 organization 引用 | 拒绝且无跨域写入 |
| Runtime 失败或进程丢失 | 状态、错误和恢复证据可读 |

验证层级：shared contract、schema/migration、service、PostgreSQL 双连接并发、API workflow、真实 Runtime E2E 和 UI E2E。

## 10. 发布边界

- Automation scheduler 初始默认关闭；
- Schema migration 先发布，新增字段和表保持向后兼容；
- Webhook 最后启用，且必须先完成 secret 与 actor 边界；
- 回滚只能关闭 scheduler，不能删除 Automation 定义、Run 或审计证据；
- queued Automation Run 必须按明确策略继续、取消或保留，不能静默丢弃。

## 11. 启动条件

只有同时满足以下条件，才从 TODO 转入正式实施：

1. 产品出现明确的定时、API 或 Webhook 自动执行场景；
2. 用户确认 Automation 的首个交付范围；
3. `RunExecutionService`、`RunFinalizationService` 和 `RunRecoveryService` 的现有稳定性问题完成验收；
4. 为 Automation 建立独立 Step、实施计划和验收批次；
5. 不与 Heartbeat 或 Run Recovery 修复混在同一个开发提交中。
