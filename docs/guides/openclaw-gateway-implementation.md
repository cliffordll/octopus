# OpenClaw Gateway 实现方案

本文说明 Octopus 支持 `openclaw_gateway` runtime 的上游依据、实现边界和验收标准。

## 核心结论

```text
OpenClaw Gateway 是 WebSocket runtime
不是 HTTP hook runtime，也不是 OpenAI /v1/responses 兼容 runtime
```

Octopus 已经把 `openclaw_gateway` 放进 runtime 枚举、CLI 选择项和 UI runtime
列表，并已补齐真实 runner、environment probe 和 WebSocket 协议 helper。实现遵循原生
Gateway WebSocket 协议，不复用 `http` runtime。

## 上游依据

参考上游 upstream reference：

```text
D:\coding\upstream-reference\packages\agent-runtimes\openclaw-gateway
D:\coding\upstream-reference\server\src\__tests__\openclaw-gateway-adapter.test.ts
```

关键行为：

- Gateway URL 必须是 `ws://` 或 `wss://`。
- 连接后先等待 `connect.challenge`。
- 客户端发送 `req connect`，携带 protocol、client、auth、role、scopes 和可选
  device payload。
- 执行时发送 `req agent`。
- 等待结果时发送 `req agent.wait`。
- Gateway 事件以 `event agent` frame 返回，runner 将其写入 run logs。
- `idempotencyKey` 使用 run id。
- `sessionKey` 由 `sessionKeyStrategy` 解析。
- `payloadTemplate` 会合并到 agent request payload。

上游日志格式：

```text
[openclaw-gateway] ...
[openclaw-gateway:event] run=<run_id> stream=<stream> data=<json>
```

Octopus 应保留这些前缀，方便后续 run transcript、debug 和上游行为对齐。

## Octopus 当前状态

已存在：

- `packages/shared/constants/agent.py` 包含 `openclaw_gateway`。
- `packages/runtimes/registry.py` 注册 `OpenClawGatewayRuntimeAdapter`。
- `packages/runtimes/openclaw_gateway/` 包含 protocol、environment 和 runner。
- `cli/commands/agent.py` 允许选择 `openclaw_gateway`。
- `ui/src/pages/NewAgentPage.tsx` 和 `ui/src/pages/AgentPage.tsx` 暴露 runtime。
- `ui/src/utils/runtimeModels.ts` 将 `openclaw_gateway` 识别为支持 provider/model
  配置的 runtime。
- `tests/contract/test_openclaw_gateway_runtime.py` 覆盖 URL 校验、auth 派生、
  session key、payload 构造和 environment probe。
- `tests/contract/test_step14_runtime_adapters.py` 覆盖 registry 与 runtime metadata。

剩余边界：

- Step 14 文档仍按当阶段说明 `openclaw_gateway` 不做完整执行实现；`FEATURE.md`
  已标明该 runtime 在后续 OpenClaw Gateway 工作中升级为真实 WebSocket Gateway runtime。
- UI/CLI 已能选择 runtime 和保存基础 config；OpenClaw 专属 onboarding、invite 和
  pairing 体验仍属于后续产品化增强。

## 实现边界

第一批实现已完成最小可用 Gateway runtime：

- WebSocket 连接和协议握手。
- 基础认证字段解析。
- agent request / wait request。
- run logs 和 result 归一化。
- environment test API 返回可解释的 probe 结果。
- UI/CLI 支持基础配置和测试入口。

第一批不做：

- OpenClaw invite prompt API。
- 稳定 device key 管理。
- 完整 auto-pairing 流程。
- OpenClaw 专属 onboarding wizard。
- 新的业务对象或数据库表。

这些能力可作为第二批在真实 OpenClaw 部署和配对流程确认后再做。

## Runtime 目录

新增目录：

```text
packages/runtimes/openclaw_gateway/
  __init__.py
  environment.py
  protocol.py
  runner.py
```

职责：

| 文件 | 职责 |
| --- | --- |
| `environment.py` | 校验配置、探测 Gateway challenge、生成 environment test result |
| `protocol.py` | 封装 WebSocket frame、message id、session key、auth payload 和 event 解析 |
| `runner.py` | 执行 connect、agent、agent.wait，并归一化 Octopus runtime result |

如当前 Python 依赖中没有 WebSocket client，应引入小型依赖 `websockets`，避免在
runtime 内手写 WebSocket 协议。

## 配置契约

`agent_runtime_config` 支持以下字段：

| 字段 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `url` | string | 无 | Gateway WebSocket URL，必须是 `ws://` 或 `wss://` |
| `headers` | object | `{}` | 额外连接认证或代理 header |
| `authToken` | string | 无 | OpenClaw token |
| `token` | string | 无 | `authToken` 的兼容别名 |
| `password` | string | 无 | Gateway password 认证 |
| `clientId` | string | `octopus-gateway-client` | Gateway client id |
| `clientMode` | string | `agent` | Gateway client mode |
| `clientVersion` | string | Octopus 版本或 `octopus` | 连接版本标识 |
| `role` | string | `operator` | Gateway role |
| `scopes` | string[] | `["operator.admin"]` | Gateway scopes |
| `payloadTemplate` | object | `{}` | 合并到 `req agent` payload |
| `workspaceRuntime` | object | 无 | 传给 Gateway 的 workspace/runtime hints |
| `sessionKeyStrategy` | string | `issue` | `issue`、`fixed` 或 `run` |
| `sessionKey` | string | 无 | `fixed` 策略使用 |
| `timeoutSec` | number | `120` | 整体执行超时 |
| `waitTimeoutMs` | number | `120000` | `agent.wait` 等待超时 |
| `disableDeviceAuth` | boolean | `false` | 第一批可接受但不实现 device signing |
| `autoPairOnFirstConnect` | boolean | `true` | 第一批可接受但不执行 pairing |

认证解析顺序：

1. `authToken`
2. `token`
3. `headers.x-openclaw-token`
4. `headers.x-openclaw-auth`
5. `headers.authorization`
6. `password`

如果 token 存在且 headers 没有 `Authorization`，runner 应派生：

```text
Authorization: Bearer <token>
```

## 协议流程

```text
1. open WebSocket(url, headers)
2. wait connect.challenge
3. send req connect
4. wait connect ok/error
5. send req agent
6. collect event agent frames into logs
7. send req agent.wait
8. wait result or timeout
9. normalize result
```

`req agent` payload 至少包含：

```json
{
  "message": "<run task message>",
  "idempotencyKey": "<run_id>",
  "sessionKey": "<resolved_session_key>"
}
```

同时合并：

- `payloadTemplate`
- workspace hints
- runtime service intents
- run/task/issue/org identifiers

## Result 归一化

成功结果：

- `exitCode = 0`
- `timedOut = false`
- `provider = "openclaw"`
- summary 来自 Gateway wait result 的文本输出或结构化 message。
- event frames 写入 run logs。
- Gateway meta 中的 `runtimeServices` 归一化为 Octopus runtime services。
- Gateway meta 中的 `previewUrl` / `previewUrls` 进入 result metadata。

失败结果：

- URL 缺失：`openclaw_gateway_url_missing`
- URL 非法：`openclaw_gateway_url_invalid`
- URL 协议非法：`openclaw_gateway_url_protocol_invalid`
- challenge 超时或握手失败：`openclaw_gateway_probe_failed`
- wait 超时：`openclaw_gateway_wait_timeout`
- Gateway 返回 error frame：保留 Gateway error code，并包装为 runtime failure。

## Environment Probe

environment test 应对齐上游 check code：

| code | 含义 |
| --- | --- |
| `openclaw_gateway_url_missing` | 未配置 URL |
| `openclaw_gateway_url_invalid` | URL 解析失败 |
| `openclaw_gateway_url_protocol_invalid` | URL 不是 `ws://` 或 `wss://` |
| `openclaw_gateway_url_valid` | URL 格式有效 |
| `openclaw_gateway_plaintext_remote_ws` | 非本机地址使用明文 `ws://` |
| `openclaw_gateway_auth_present` | 已发现认证配置 |
| `openclaw_gateway_auth_missing` | 未发现认证配置 |
| `openclaw_gateway_probe_ok` | probe 握手成功 |
| `openclaw_gateway_probe_challenge_only` | 收到 challenge，但 connect 未完成 |
| `openclaw_gateway_probe_failed` | probe 失败 |
| `openclaw_gateway_probe_error` | probe 异常 |

Probe 不应启动 run，也不应写业务数据。

## UI 和 CLI

UI 第一批只补基础配置体验：

- 在 agent 创建/编辑中保留 `openclaw_gateway` runtime。
- 为 OpenClaw 展示基础配置字段或 JSON config helper。
- 提供 test environment 入口并展示 probe code/message。
- 不做 invite/onboarding wizard。

CLI 第一批支持：

- 创建 `openclaw_gateway` agent 时传入 config JSON。
- test environment 时输出 OpenClaw probe check。
- run 失败时展示 Gateway error code 和主要 message。

## 测试计划

服务端测试：

- URL 缺失返回 `openclaw_gateway_url_missing`。
- URL 协议非法返回 `openclaw_gateway_url_protocol_invalid`。
- mock WebSocket Gateway 成功完成 `connect -> agent -> agent.wait`。
- runner 发送的 `idempotencyKey` 等于 run id。
- runner 解析 `sessionKeyStrategy=issue|fixed|run`。
- event frames 写入 `[openclaw-gateway:event]` 日志。
- wait timeout 返回 `openclaw_gateway_wait_timeout`。
- Gateway meta 中的 `runtimeServices` 被归一化。

UI/CLI 测试：

- OpenClaw runtime 可选择。
- OpenClaw config 能保存并回显。
- environment test 能展示 probe 结果。
- CLI 能传入 config JSON 并命中对应 API payload。

## 验收标准

- `openclaw_gateway` 不再返回未实现 runtime。
- 配置合法的 mock Gateway run 能成功完成并产生 run log。
- 配置错误能返回稳定、可解释的 OpenClaw check code。
- UI/CLI 能创建、编辑和测试 OpenClaw agent。
- 实现不改变 `http`、`codex_local`、`claude_local`、`opencode_local` 的行为。
- invite prompt、device signing、auto-pairing 没有被误标为已完成。

## 本地验证记录

- `uv run pytest tests/contract/test_openclaw_gateway_runtime.py tests/contract/test_step14_runtime_adapters.py::test_step14_registry_returns_known_adapters_or_unavailable tests/contract/test_step14_runtime_adapters.py::test_openclaw_gateway_runtime_metadata_reports_environment_support -q`：14 passed。
