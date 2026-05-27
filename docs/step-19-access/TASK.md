# Step 19: Auth / Actor / Access

状态：待开发

## 任务

- 按上游证据实现真实 authentication、actor context 与 access checks。
- 以真实身份来源替换 Step 5 的开发 actor 来源。
- 保证业务 API 和 actor 数据形态不因接入真实访问能力而重构。

## 边界

- 不发明上游不存在的角色或授权前置条件。

## 验收

- Tests 验证真实与开发 context 来源输出兼容结构，并覆盖已实现 API 的访问行为。
