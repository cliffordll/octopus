# Step 22: Auth / Actor / Access

状态：待开发

## 任务

- 按上游证据实现真实 authentication、actor context 与 access checks。
- 以真实身份来源替换 Step 5 的开发 actor 来源。
- 保证业务 API 和 actor 数据形态不因接入真实访问能力而重构。
- 接入 local agent JWT/API key 兼容入口，使 Step 14 runtime adapter 暴露的 auth 边界能解析为真实 actor/access 语义。
- 实现 runtime secret/env binding 解析：从真实身份、组织、agent/runtime config 中得到受控环境变量，不把密钥泄漏到响应或日志。
- 保持调试阶段模拟 actor 与真实 actor 的结构一致；切换身份来源时不得改变 API payload 形态。

## 边界

- 不发明上游不存在的角色或授权前置条件。
- 不在 runtime adapter 内部硬编码真实 secret 来源；adapter 只消费本步骤解析后的受控 env/context。
- 不把 local agent JWT/API key 作为业务所有权模型；它只用于上游兼容的本地 runtime 调用身份。
- 基础调试可见性已在 Step 18 提前完成，本步骤只替换身份来源和访问语义，不重做 observability。

## 验收

- Tests 验证真实与开发 context 来源输出兼容结构，并覆盖已实现 API 的访问行为。
- Tests 覆盖 local agent JWT/API key、secret/env binding、日志脱敏和 runtime 调用上下文注入。
