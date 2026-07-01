# OpenCode Provider/Model 配置

本文说明 OpenCode 上游方案和 Octopus 当前 server 端改造边界。

## 上游方案

上游 upstream reference 没有为 OpenCode provider/model 建专门表。

持久化字段只有：

```text
agents.agent_runtime_type
agents.agent_runtime_config.model
```

OpenCode 的 provider、baseURL、认证和模型目录来自 OpenCode 自己的 home：

```text
用户 OpenCode home
-> opencode models
-> agents.agent_runtime_config.model
-> upstream reference-managed OpenCode home
```

## Octopus 当前方案

Octopus server 增加实例级手动维护能力：

```text
llm_providers
llm_provider_bindings
llm_models
llm_runtime_defaults
agents.agent_runtime_config.model
```

边界：

- server 支持 provider CRUD。
- server 支持 model CRUD。
- server 不提供 `/models/refresh`。
- server 不主动请求模型服务 `/models`。
- 模型列表是否更新，需要用户或上层管理流程显式维护。
- provider 的 `api_key` 开发期明文保存，API 返回脱敏。

## 配置流程

```text
1. 创建 provider：
   POST /api/llm/providers

2. 手动添加模型：
   POST /api/llm/providers/{providerId}/models?runtimeType=opencode_local

3. 创建或编辑智能体时选择模型：
   agents.agent_runtime_config.model = provider/model

4. 执行时 runtime adapter 读取实例级 provider/model 配置。

5. `opencode_local` adapter 执行前将配置渲染到 managed OpenCode home：
   .octopus/instances/default/organizations/<org_id>/opencode-home/home/.config/opencode/opencode.json
```

## OpenCode 配置含义

OpenCode 仍然通过自己的配置文件识别 provider/model。Octopus 会在执行前从
`llm_providers`、`llm_provider_bindings`、`llm_models` 和 `llm_runtime_defaults`
生成 managed home 内的 OpenCode 配置，
不长期修改用户全局 OpenCode 配置。

`opencode_local` 可以复制宿主机 OpenCode 配置作为 managed home 的基础配置，
但 `.config/opencode` 必须是 managed home 内的独立副本，不能是指向宿主机配置
目录的 symlink。执行前写入 DB provider/model 时，只允许修改 managed home，不
允许写回 `%USERPROFILE%/.config/opencode/opencode.json`。

示例目标文件：

```text
.octopus/instances/default/organizations/<org_id>/opencode-home/home/.config/opencode/opencode.json
```

示例内容：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "kimi": {
      "name": "Kimi",
      "npm": "@ai-sdk/openai-compatible",
      "options": {
        "baseURL": "https://api.moonshot.cn/v1",
        "apiKey": "resolved-secret"
      },
      "models": {
        "kimik/kimi-k2.5": {
          "name": "Kimi K2.5"
        }
      }
    }
  }
}
```

## 当前边界

当前 `opencode_local` 已支持从 DB provider/model 生成 managed home 配置。
`codex_local`、`claude_local` 也已复用 DB provider/model 注入逻辑，但二者
按各自 CLI 约定使用环境变量传递 provider 连接信息，而不是生成 OpenCode
配置文件。
