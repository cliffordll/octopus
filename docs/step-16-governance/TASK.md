# Step 16: Cost、Budget 与 Activity

状态：待开发

## 依赖边界

Step 11 只记录首个可运行闭环必须产生的执行结果或必要活动。本步骤补齐完整 cost、budget 与 activity 治理语义。

## 任务

- 实现 run cost 的兼容记录和归集。
- 实现上游已有的 budget 检查与受限行为。
- 补齐执行和治理操作产生的 activity 输出。
- 将 Step 14 的 skills analytics 兼容空响应升级为真实归集：基于 run/event/activity 中的 loaded/requested/used evidence 统计 agent skill 使用情况。
- 归集 Step 14 adapter quota window probe 输出，并与 budget/cost 查询和限制行为建立可解释联动。

## 边界

- 仅增加存在上游证据的成本、预算和活动语义。
- 不负责 runtime skills 的 materialization、mount 或 organization skill 管理；这些分别归 Step 14 和独立 skills 管理步骤。

## 验收

- Tests 覆盖消耗归集、预算限制和必须产生的 activity entries。
- Tests 覆盖 skills analytics 从空兼容响应升级为真实统计后，loaded/requested/used evidence 的计数、时间窗口和 agent/org scope 行为。
