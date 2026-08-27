# Run 生命周期可靠性重构计划

状态：实施中

## 背景

当前 Run 执行、终态收尾和异常恢复集中在 `HeartbeatService` 与 `RunDispatchService`
函数中。现场问题表明以下生命周期边界仍不完整：

1. 后台 Run 的数据库 Session 可能未可靠归还连接池；
2. fire-and-forget `RunDispatchService` task 的异常可能未被观察；
3. execution lease 已过期但没有 `processPid` 的 Run 会被周期恢复永久跳过；
4. 父 Run 因基础设施故障失败时，即使仍有活动子任务，父 Issue 也可能被错误改为 `blocked`；
5. recovery Run 成功后不能安全恢复由同一系统故障造成的父 Issue 状态；
6. 已经损坏的现场 Run/Issue 需要基于证据进行一次性修复，不能靠修改代码自动猜测历史状态。

## 目标结构

- `RunExecutionService`：每个已领取 Run 的执行生命周期，独占数据库 Session，负责
  Adapter 调用、租约续期、取消响应、提交/回滚和资源释放。
- `RunFinalizationService`：正常执行与恢复共同使用的终态入口，负责 Run 终态和可恢复、
  幂等的 wakeup、Agent、Issue、Workspace、父任务续跑等副作用。
- `RunRecoveryService`：周期检查异常 Run，依据 lease 与进程证据进行 CAS 认领，调用
  `RunFinalizationService` 收口，并在允许时创建一次关联原 Run 的 recovery Run。

`RunDispatchService` 只负责领取排队 Run、创建 `RunExecutionService` 并观察后台 task 结果；
Adapter 只负责启动和监控 Runtime 进程，不负责数据库租约或业务终态。

## 批次与提交边界

### 批次一：RunExecutionService

- 把每个 Run 的 Session、HeartbeatService、执行与清理封装为显式对象；
- `RunDispatchService` 必须持有并观察后台 task，异常进入结构化日志；
- commit、rollback、close 具有明确顺序，关闭失败不得静默吞掉；
- 保持现有 claim、并发槽、Adapter 和 API 契约不变。

验收：Adapter 成功、失败、取消以及 task 异常时 Session 均被关闭；续租随执行结束；
后台异常可观察；相关 Step 13 workflow/contract 测试通过。

### 批次二：RunFinalizationService

- 提取正常执行与 recovery 共用的 Run 终态和 terminal effects 入口；
- terminal effects 保持可重入，旧 owner 不能覆盖新 owner；
- 父 Issue 仍有可见活动子任务时，基础设施失败不得将父 Issue 永久改为
  `blocked`；
- 只有最新状态证据表明 `blocked` 由同一个系统失败 Run 产生时，才允许恢复，
  用户手动阻塞不得被覆盖。

验收：terminal effects 重放无重复副作用；活动子任务、用户手动 blocked、系统
blocked、并发 Run 状态均有工作流测试。

### 批次三：RunRecoveryService

- lease 是恢复主证据，PID 是本地进程辅助证据；
- lease 有效保持 `running`；lease 过期且进程存活时暂缓并记录证据；
- lease 过期且进程消失，或无 PID 且超过恢复宽限期时，CAS 收口为
  `failed/process_lost`；
- 自动 recovery Run 保留 `retryOfRunId`、Issue、Agent、Workspace 和上下文，
  同一故障最多创建一次自动重试；
- `RunRecoveryService` 不直接调用 Adapter，新 Run 统一交回 `RunDispatchService`。

验收：无 PID 过期 Run 可恢复；有效租约和活进程不误杀；重复/并发扫描只收口和
重试一次；恢复 Run 仍属于原任务。

### 批次四：历史数据修复

- 提供受 organization 与目标 ID 限制的诊断/修复入口或维护命令；
- 先输出证据和拟执行变更，再修复明确指定的损坏 Run/Issue；
- 不批量推断只有模糊字段的历史 Run，也不覆盖用户手动业务状态；
- 修复 `fd6590eb-609f-4deb-9f59-67d41188f241` 时，收口过期子 Run、创建允许的
  recovery Run，并按活动子任务和状态来源恢复父 Issue。

验收：dry-run 可复核；重复执行无额外 Run/事件；目标任务可以继续到父任务汇总。

## 验证策略

每个批次只执行对应聚焦测试、格式和 diff 检查，通过后形成独立提交。全部批次完成
后统一执行：

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run pytest`
4. `uv run pyright .`

最后按场景正确性和工程交付可信度进行串行双角色复核。用户在最终验证前可以保留
服务停止状态，现场数据修复不得在未确认数据库实例和 dry-run 结果时直接执行。

## 非目标

- 不修改对外 Run、Issue 或 Runtime API 契约；
- 不新增业务状态值；
- 不让 `RunRecoveryService` 维护或复活旧 Adapter/OS 进程；
- 不在本批次实现 Automation；
- 不把父任务汇总拆成额外的 summary child Issue。

## 提交记录

- 批次一：`496b9c3 refactor run execution lifecycle`；74 个 Run workflow / Session
  cleanup 相关测试通过，聚焦 Ruff、Pyright 和 diff check 通过。
- 批次二：`3815d16 refactor run terminal finalization`；61 个 Step 13 workflow、
  68 个 Run/Agent contract 测试通过，聚焦静态检查通过。
- 批次三：`cb342a7 fix expired run recovery without process metadata`；63 个 Step 13
  workflow、22 个 Scheduler/Run contract 测试通过，聚焦静态检查通过。
- 批次四：随维护命令实现所在提交交付；目标任务 dry-run 只命中
  `c99f545a-c219-415f-822d-794bc0202bf4` 与
  `1a817bd4-7614-4077-8314-984c1857cf36` 两个租约过期且无 PID 的 Run。现场
  `--apply` 必须在服务重启并加载本轮代码后执行，避免新旧恢复逻辑混用。
