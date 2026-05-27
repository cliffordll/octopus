# Step 11: Agent 与 Runtime 配置

状态：待开发

## 调整原因

上游 `goals.owner_agent_id` 直接引用 agent。先实现 agent 主对象和 runtime 配置边界，Step 12 Goal 才能在首次落地时校验 `ownerAgentId`，避免引入暂时不兼容的空关联行为。

## 任务

- 对照上游证据冻结 agent contract、schema/query、管理 API 与 runtime 配置 shape。
- 实现 agent 的 organization scope、创建/读取/更新等上游已存在管理行为。
- 实现供后续 Goal 与 Run 使用的兼容 runtime 配置表示与校验。
- 明确敏感配置、外部 runtime id 和响应脱敏边界。

## 不包含

- Goal CRUD、父子层级或 goal/project 关系；这些归入 Step 12。
- 实际 run 触发、heartbeat 生命周期或 runtime 执行。

## 验收

- Tests 验证 agent 管理、organization scope、runtime 配置 shape 和外部标识兼容性。
- Step 12 可以使用已实现 agent 对 `Goal.ownerAgentId` 做同 organization 引用校验。
