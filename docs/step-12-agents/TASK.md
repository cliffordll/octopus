# Step 12: Agent 与 Runtime 配置

状态：待开发

## 任务

- 实现 agent contract、持久化和管理 API。
- 实现供后续运行流程使用的兼容 runtime 配置表示与校验。
- 明确敏感配置及外部 runtime id 的保存/返回边界。

## 不包含

- 实际 run 触发或 runtime 执行。

## 验收

- Tests 验证 agent 管理、配置 shape 和外部标识兼容性。
