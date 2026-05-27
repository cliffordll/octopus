# Step 14: 其他 Runtime Adapter 扩展

状态：待开发

## 依赖边界

Step 11 已定义统一 adapter contract，并由 11C 提供 `process` 路径、由 11E 提供 `codex_local` 智能体执行路径。本步骤扩展其余上游 runtime 覆盖范围，不承担首次打通 Agent 交互执行闭环。

## 任务

- 按上游证据实现 `process` 与 `codex_local` 以外的新增 runtime adapter 类型。
- 扩展 session、environment、usage、日志和失败语义映射。
- 确认新增 adapter 复用既有 run 状态机和业务 API。

## 不包含

- Workspace 生命周期与产物持久化，归 Step 15。
- Cost/budget 治理，归 Step 16。
- 触发 Codex Agent 的最小 conversation/message 链路，归 Step 11F。

## 验收

- Tests 证明 runtime 差异不会改变业务 API 或 run 状态语义。
