# Step 16: Cost、Budget 与 Activity

状态：待开发

## 依赖边界

Step 11 只记录首个可运行闭环必须产生的执行结果或必要活动。本步骤补齐完整 cost、budget 与 activity 治理语义。

## 任务

- 实现 run cost 的兼容记录和归集。
- 实现上游已有的 budget 检查与受限行为。
- 补齐执行和治理操作产生的 activity 输出。

## 边界

- 仅增加存在上游证据的成本、预算和活动语义。

## 验收

- Tests 覆盖消耗归集、预算限制和必须产生的 activity entries。
