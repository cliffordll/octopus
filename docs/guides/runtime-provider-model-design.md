# 组织级 Runtime Provider/Model 设计

本文说明 Octopus 如何管理 `opencode_local`、`codex_local`、`claude_local`
等本地运行时的 provider/model 配置。

## 核心结论

```text
provider/model 连接配置属于组织
agentRuntimeConfig.model 属于智能体
runtime adapter 负责把组织配置渲染到 managed home
```

当前 server 只支持数据库维护，不自动发现模型：

- `GET /models` 只返回 `runtime_models` 中已有数据。
- 不提供 `/models/refresh`。
- server 不主动请求外部模型服务 `/models`。
- 模型服务是否更新，由用户或上层管理流程手动维护到 Octopus。

## 数据表

### runtime_providers

保存组织级模型服务连接配置。

```text
id
org_id
runtime_type
provider_id
name
protocol
npm_package
base_url
api_key
config
enabled
created_at
updated_at
```

唯一约束：

```text
unique(org_id, runtime_type, provider_id)
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `org_id` | 组织隔离边界 |
| `runtime_type` | `opencode_local`、`codex_local`、`claude_local` 等 |
| `provider_id` | provider 标识，例如 `local`、`openrouter`、`kimi` |
| `name` | 展示名称 |
| `protocol` | 协议类型，例如 `openai_chat_completions`、`openai_responses`、`ai_sdk_provider` |
| `npm_package` | OpenCode 需要的 AI SDK package，例如 `@ai-sdk/openai-compatible` |
| `base_url` | 模型服务地址 |
| `api_key` | 开发期明文保存；API 响应必须脱敏 |
| `config` | 额外配置 |
| `enabled` | 是否启用 |

### runtime_models

保存组织级 provider 下可选模型。

```text
id
org_id
runtime_type
provider_id
model_id
display_name
metadata
enabled
created_at
updated_at
```

唯一约束：

```text
unique(org_id, runtime_type, provider_id, model_id)
```

字段说明：

| 字段 | 说明 |
| --- | --- |
| `org_id` | 组织隔离边界 |
| `runtime_type` | 所属 runtime |
| `provider_id` | 所属 provider |
| `model_id` | provider 内部模型 id，可包含 `/` |
| `display_name` | 展示名称 |
| `metadata` | context window、输入输出能力、价格等可选信息 |
| `enabled` | 是否允许在 UI 中选择 |

## API

### Provider 管理

```text
GET    /api/orgs/{orgId}/runtime-providers?runtimeType=opencode_local
POST   /api/orgs/{orgId}/runtime-providers
PATCH  /api/orgs/{orgId}/runtime-providers/{providerId}?runtimeType=opencode_local
DELETE /api/orgs/{orgId}/runtime-providers/{providerId}?runtimeType=opencode_local
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
GET    /api/orgs/{orgId}/runtime-providers/{providerId}/models?runtimeType=opencode_local
POST   /api/orgs/{orgId}/runtime-providers/{providerId}/models?runtimeType=opencode_local
PATCH  /api/orgs/{orgId}/runtime-providers/{providerId}/models/{modelId}?runtimeType=opencode_local
DELETE /api/orgs/{orgId}/runtime-providers/{providerId}/models/{modelId}?runtimeType=opencode_local
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
3. 创建/编辑智能体时，UI 查询 runtime_models。
4. 用户选择 model。
5. server 保存到 agents.agent_runtime_config.model。
```

当前 server 不知道模型服务是否新增模型；必须通过 model CRUD 显式维护。

## 执行流程

```text
1. server 读取 agent：
   agents.agent_runtime_type
   agents.agent_runtime_config.model

2. 根据 agent.org_id 和 runtime_type 查询 runtime_providers/runtime_models。

3. adapter 准备 managed runtime home。

4. 对 `opencode_local`，adapter 执行前生成：
   .octopus/runtime-homes/opencode_local/<org_id>/<agent_id>/home/.config/opencode/opencode.json

5. 启动本地 CLI。
```

当前 `opencode_local` 已支持把 DB provider/model 配置渲染到 managed home。
`codex_local`、`claude_local` 的 provider/model 渲染仍属于后续 runtime adapter 深化。

## 安全要求

- 当前开发期 `api_key` 明文存储。
- API 不返回明文 `api_key`，只返回 `***REDACTED***` 和 `hasApiKey`。
- 后续正式方案需要迁移到 secret 引用或加密存储。
- 删除 provider 会同时删除该 provider 下的 runtime models。
