# Step 29: Auth / Actor / Access

状态：待开发

## 已提前完成

- Step 5 已提供统一开发 actor dependency、organization scope 校验和 `OCTOPUS_LOCAL_TRUSTED=1` 本地 board actor，用于无真实认证阶段调试。
- Runtime provider/model 配置已支持 org-scoped CRUD，并在 runtime 执行前注入 provider/model/baseUrl/apiKey 到受控 runtime context；API response 会对 provider `apiKey` 做 redaction。
- `codex_local`、`claude_local`、`opencode_local` 已支持数据库 provider/model 配置的运行时注入；Codex/OpenCode/Claude 的本地 CLI env/base URL/model 适配已提前完成。
- Agent config revision 里已有 secret redaction 保护，避免回滚包含已脱敏 secret 的配置。

这些提前完成项是开发期 access/secret 基础，不等同于真实 authentication、actor 和 authorization 子系统。

## 任务

- 按上游证据实现真实 authentication、actor context 与 access checks。
- 以真实身份来源替换 Step 5 的开发 actor 来源。
- 保证业务 API 和 actor 数据形态不因接入真实访问能力而重构。
- 接入 local agent JWT/API key 兼容入口，使 Step 14 runtime adapter 暴露的 auth 边界能解析为真实 actor/access 语义。
- 实现 runtime secret/env binding 解析：从真实身份、组织、agent/runtime config 中得到受控环境变量，不把密钥泄漏到响应或日志。
- 保持调试阶段模拟 actor 与真实 actor 的结构一致；切换身份来源时不得改变 API payload 形态。

## 剩余待开发

- 当前仍没有上游式真实 authentication/board auth/local agent auth 的完整入口；开发 actor 仍是主要请求身份来源。
- 当前没有完整 actor permission 模型、agent permission service、真实 access onboarding 和 authz route。
- 当前 provider/model apiKey 暂存数据库明文字段并在响应脱敏；还没有上游式 secret store、secret reference、secret rotation 或 audit policy。
- 当前 runtime env 解析主要服务 provider/model 配置，还没有覆盖完整 local agent JWT/API key、请求 actor 到 runtime actor 的映射和权限校验。

## 边界

- 不发明上游不存在的角色或授权前置条件。
- 不在 runtime adapter 内部硬编码真实 secret 来源；adapter 只消费本步骤解析后的受控 env/context。
- 不把 local agent JWT/API key 作为业务所有权模型；它只用于上游兼容的本地 runtime 调用身份。
- 基础调试可见性已在 Step 20 完成，本步骤只替换身份来源和访问语义，不重做 observability。

## 验收

- Tests 验证真实与开发 context 来源输出兼容结构，并覆盖已实现 API 的访问行为。
- Tests 覆盖 local agent JWT/API key、secret/env binding、日志脱敏和 runtime 调用上下文注入。
