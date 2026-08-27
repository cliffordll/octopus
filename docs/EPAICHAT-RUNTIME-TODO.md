# EPAIChat Runtime 接入代办

## 状态

暂缓接入。当前只保留 Runtime 扩展接口，不增加 EPAIChat 配置、运行时类型、API 路由或数据库字段。

## 已具备的扩展边界

- `RuntimeAdapterProtocol`：所有 Runtime 实现必须满足的统一契约。
- `LocalRuntimeAdapter`：Codex、OpenCode、Claude 等本地进程 Runtime 的公共执行基类。
- `RemoteRuntimeAdapter`：HTTP、SSE 或 Gateway Runtime 的公共执行基类。
- `RuntimeArtifactsCollector`：把 Runtime 原生文件事件统一转换为 Octopus 产物记录。

EPAIChat 后续应作为 `RemoteRuntimeAdapter` 的独立实现接入，不在调度、Run 生命周期或 Workspace 持久化代码中增加 EPAIChat 分支。

## 后续实施项

1. 明确 EPAIChat 的鉴权、会话续接、超时、取消和错误码契约。
2. 新增独立 Runtime 类型及配置校验，不复用普通一次性 HTTP Runtime 的配置含义。
3. 对接 OpenAI 兼容的 `/v1/responses` 或 `/v1/chat/completions`，并支持 SSE 增量事件。
4. 将 EPAIChat 的产物事件转换为 `artifactEvidence`，继续复用 `RuntimeArtifactsCollector`。
5. 增加环境检测、流式日志、取消、超时、会话恢复、产物登记和异常响应测试。
6. 使用真实 EPAIChat 服务完成端到端验收后再开放 UI 配置。

## 非目标

- 当前版本不访问 `D:/coding/epaichat` 的运行服务。
- 当前版本不注册 `epaichat` Runtime ID。
- 当前版本不改变现有 `http` 与 `openclaw_gateway` 的外部契约。
