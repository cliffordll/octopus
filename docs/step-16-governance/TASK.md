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
- 将 Step 14 的 quota window 兼容入口升级为真实 provider quota 读取：失败继续可解释，不阻断普通 run。
- 归一化 provider/biller/cost 字段，补齐 OpenRouter、内置 provider 与本地 CLI usage/cost 的治理口径。
- 明确 quota window、budget、cost 三者关系：quota 是 provider 使用窗口证据，budget 是组织/项目治理限制，cost 是 run/activity 归集结果。

## 边界

- 仅增加存在上游证据的成本、预算和活动语义。
- 不修改 runtime adapter 的执行协议；adapter 只提供 probe/usage 原始证据，本步骤负责治理归集和限制解释。
- 不负责 runtime skills 的 materialization、mount 或 organization skill 管理；这些分别归 Step 14 和独立 skills 管理步骤。

## 验收

- Tests 覆盖消耗归集、预算限制和必须产生的 activity entries。
- Tests 覆盖 provider quota 原始读取失败、成功归集、窗口过期和 budget 联动行为。
- Tests 覆盖 skills analytics 从空兼容响应升级为真实统计后，loaded/requested/used evidence 的计数、时间窗口和 agent/org scope 行为。
