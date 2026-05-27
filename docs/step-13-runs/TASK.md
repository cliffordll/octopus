# Step 13: Run 调度与恢复

状态：待开发

## 依赖边界

Step 11 已建立首个 agent wakeup、heartbeat run 与实际 adapter 执行闭环。本步骤不重复创建基础 contract，而是在该闭环上补齐运行编排和恢复语义。

## 任务

- 对照上游 server 行为扩展定时、队列或业务事件触发规则。
- 实现 run claim、并发防护、重复触发幂等、取消与中断恢复。
- 扩展运行记录查询和恢复事件记录。

## 不包含

- `codex_local` adapter 归 Step 11E；其他新 runtime 类型的 adapter 实现归 Step 14。
- 完整 workspace 与治理闭环，分别归 Step 15 和 Step 16。

## 验收

- Workflow tests 覆盖调度、竞争领取、重复触发、取消和中断恢复。
