# LLM Provider/Model 设计

本文说明 Octopus 如何管理 `opencode_local`、`codex_local`、`claude_local`、`openclaw_local`
等本地运行时的 provider/model 配置。

## 核心结论

```text
provider/model 连接配置属于实例级 LLM catalog
runtimeType 只用于运行时默认模型绑定
agentRuntimeConfig.model 属于智能体
runtime adapter 负责把 LLM 配置注入到 managed home 或运行时环境
```

当前 server 只支持数据库维护，不自动发现模型：

- `GET /models` 只返回 `llm_models` 中已有数据。
- 不提供 `/models/refresh`。
- server 不主动请求外部模型服务 `/models`。
- 模型服务是否更新，由用户或上层管理流程手动维护到 Octopus。

## 数据表

### llm_providers

保存实例级模型服务基础信息。

```text
id
provider_id
name
protocol
npm_package
enabled
created_at
updated_at
```

唯一约束：

```text
unique(provider_id)
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `provider_id` | provider 标识，例如 `local`、`openrouter`、`kimi` |
| `name` | 展示名称 |
| `protocol` | 协议类型，例如 `openai_chat_completions`、`openai_responses`、`ai_sdk_provider` |
| `npm_package` | OpenCode 需要的 AI SDK package，例如 `@ai-sdk/openai-compatible` |
| `enabled` | 是否启用 |

### llm_provider_bindings

保存 provider 的实例级连接信息。

```text
id
scope_type
scope_id
provider_id
base_url
api_key
config_json
enabled
priority
created_at
updated_at
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `scope_type` | 当前使用 `instance` |
| `scope_id` | 实例级绑定为空字符串 |
| `provider_id` | provider 标识 |
| `base_url` | 模型服务地址 |
| `api_key` | 开发期明文保存；API 响应必须脱敏 |
| `config_json` | 额外配置 |
| `enabled` | 是否启用 |

### llm_models

保存 provider 下可选模型。

```text
id
provider_id
model_id
display_name
metadata_json
enabled
created_at
updated_at
```

唯一约束：

```text
unique(provider_id, model_id)
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `provider_id` | 所属 provider |
| `model_id` | provider 内部模型 id，可包含 `/` |
| `display_name` | 展示名称 |
| `metadata_json` | context window、输入输出能力、价格等可选信息 |
| `enabled` | 是否允许在 UI 中选择 |

### llm_runtime_defaults

保存每个运行时的默认 provider/model。

```text
id
scope_type
scope_id
runtime_type
provider_id
model_id
created_at
updated_at
```

唯一约束：

```text
unique(scope_type, scope_id, runtime_type)
```

## API

### Provider 管理

```text
GET    /api/llm/providers
POST   /api/llm/providers
PATCH  /api/llm/providers/{providerId}?runtimeType=opencode_local
DELETE /api/llm/providers/{providerId}?runtimeType=opencode_local
```

写入示例：

```json
{
  "runtimeType": "opencode_local",
  "providerId": "kimi",
  "name": "Kimi",
  "protocol": "openai_chat_completions",
  "npmPackage": "@ai-sdk/openai-compatible",
  "baseUrl": "https://api.moonshot.cn/v1",
  "apiKey": "secret-value",
  "config": {},
  "enabled": true
}
```

返回时必须脱敏：

```json
{
  "runtimeType": "opencode_local",
  "providerId": "kimi",
  "apiKey": "***REDACTED***",
  "hasApiKey": true
}
```

更新 provider 时，`apiKey` 传 `***REDACTED***` 表示保持原值不变。

### Model 管理

```text
GET    /api/llm/providers/{providerId}/models?runtimeType=opencode_local
POST   /api/llm/providers/{providerId}/models?runtimeType=opencode_local
PATCH  /api/llm/providers/{providerId}/models/{modelId}?runtimeType=opencode_local
DELETE /api/llm/providers/{providerId}/models/{modelId}?runtimeType=opencode_local
```

写入示例：

```json
{
  "modelId": "kimik/kimi-k2.5",
  "displayName": "Kimi K2.5",
  "metadata": {
    "contextWindow": 128000
  },
  "enabled": true
}
```

`modelId` 可以包含 `/`，例如 `kimik/kimi-k2.5`。

## 前端配置流程

```text
1. 用户创建或更新 provider。
2. 用户手动新增或更新 provider 下的 models。
3. 创建/编辑智能体时，UI 查询 LLM provider/model 配置。
4. 用户选择 model。
5. server 保存到 agents.agent_runtime_config.model。
```

当前 server 不知道模型服务是否新增模型；必须通过 model CRUD 显式维护。

## 执行流程

```text
1. server 读取 agent：
   agents.agent_runtime_type
   agents.agent_runtime_config.model

2. 根据 runtime_type 查询 `llm_runtime_defaults`，再读取 `llm_providers`、`llm_provider_bindings`、`llm_models`。

3. adapter 准备 managed runtime home。

4. 对 `opencode_local`，adapter 执行前生成：
   .octopus/instances/default/organizations/<org_id>/opencode-home/home/.config/opencode/opencode.json

5. 启动本地 CLI。
```

当前 `opencode_local`、`codex_local`、`claude_local` 已复用 DB
provider/model 注入逻辑。`opencode_local` 会生成 managed OpenCode 配置；
`codex_local` 会把 provider `apiKey/baseUrl` 注入为 `OPENAI_API_KEY` /
`OPENAI_BASE_URL`，并把 CLI model 转为 provider 内部 `modelId`；
`claude_local` 会把 provider `apiKey/baseUrl` 注入为 `ANTHROPIC_API_KEY` /
`ANTHROPIC_BASE_URL`，并把 CLI model 转为 provider 内部 `modelId`。
`openclaw_gateway` 是 WebSocket Gateway runtime；provider/model 表只保存配置，不做
模型自动发现。真实执行由 `packages/runtimes/openclaw_gateway` runner 接入 Gateway。

`opencode_local` 的 managed `.config/opencode` 必须是独立副本，不能 symlink 到
宿主机 `%USERPROFILE%/.config/opencode`。这样 DB provider/model materialization
不会污染宿主机全局 OpenCode 配置。

## 安全要求

- 当前开发期 `api_key` 明文存储。
- API 不返回明文 `api_key`，只返回 `***REDACTED***` 和 `hasApiKey`。
- 后续正式方案需要迁移到 secret 引用或加密存储。
- 删除 provider 会同时删除该 provider 下的 runtime models。

## Chat 创建任务

Chat runtime prompt 明确要求：当用户要求创建任务、issue、work item 或 ticket
时，智能体不得直接创建 issue，而应返回 `issue_proposal` JSON envelope：

```json
{
  "summary": "我可以为你创建这个任务。",
  "kind": "issue_proposal",
  "structuredPayload": {
    "issueProposal": {
      "title": "分析 upstream-reference 源码",
      "description": "分析 upstream-reference 源码并整理核心架构。",
      "priority": "medium"
    }
  }
}
```

server 会把该 envelope 保存为 `issue_proposal` assistant message，并创建
`chat_issue_creation` approval。真正创建 issue 仍通过：

```text
POST /api/chats/{id}/convert-to-issue
```

这样保留用户确认边界，避免普通对话自动落库创建任务。
