# Step 13: Wakeup 与 Heartbeat Run

状态：待开发

## 任务

- 对照上游 server 行为映射 run schema 与 shared contract。
- 实现 wakeup 触发、heartbeat run 生命周期和运行记录查询。
- 实现上游已有的并发防护及完成/失败状态记录。

## 不包含

- Runtime adapter 的实际执行，归 Step 14。

## 验收

- Workflow tests 覆盖触发、并发保护、成功和失败记录。
