# Claude Local DB Provider 控制设计

## 目标

本文设计 `claude_local` 在 Octopus 中的 provider/model 控制方式。目标是同时满足：

- 对齐上游 upstream reference 的 Claude local runtime 行为。
- 复用 Octopus 已有 DB provider/model 管理能力。
- 不污染用户真实 Claude 配置、shell 环境变量或系统环境变量。
- 不把 Claude settings 误建模成 OpenCode 风格的 provider registry。

## 上游行为基线

上游 upstream reference 的 `claude-local` runtime 使用本地 Claude CLI。核心行为如下：

- 准备 upstream reference-managed Claude home：

```text
~/.upstream-reference/instances/<instanceId>/organizations/<orgId>/claude-home
```

- 从 operator home 同步或链接 Claude 相关配置和登录态：

```text
.claude/settings.json
.claude.json
.config/claude
.config/anthropic
.anthropic
```

- 执行 Claude CLI 时仍使用 CLI 参数和环境变量：

```text
claude --print - --output-format stream-json --verbose --model <model>
```

- `ANTHROPIC_API_KEY` 存在时走 API-key auth。
- 没有 `ANTHROPIC_API_KEY` 时依赖本地 Claude login/subscription session。

因此，上游不是把 provider 写入 `.claude/settings.json`。`.claude/settings.json`
是 Claude Code 行为配置文件，不是 OpenCode 那种 provider registry。

## Octopus 控制流程

Octopus 应在上游 managed Claude home 语义上叠加 DB provider/model 控制。

```text
DB runtime provider/model
        |
        v
server inject_runtime_provider_config()
        |
        v
context.config._octopus.runtimeProvider
        |
        v
claude_local adapter
        |
        +--> managed Claude home seeding/sync
        +--> per-run env: ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL
        +--> CLI args: --model <modelId>
        v
claude child process
```

这个流程中，DB provider/model 在每次 run/chat 调用 runtime 前动态生效：

1. server 读取 agent 的 `agent_runtime_type` 和 `agent_runtime_config`。
2. server 调用 `inject_runtime_provider_config()`。
3. 该函数根据 `agentRuntimeConfig.model` 或 runtime 默认模型查询 DB provider/model。
4. 查询结果写入 `context.config._octopus.runtimeProvider`。
5. `claude_local` adapter 读取该运行时配置。
6. adapter 只对本次 Claude 子进程设置 env 和 CLI 参数。

## Managed Claude Home

`claude_local` 应准备 per-runtime managed home，避免直接使用 operator home：

```text
<OCTOPUS_HOME>/instances/<instanceId>/organizations/<orgId>/claude-home/home
```

准备 managed home 时应参考上游同步以下 Claude 文件或目录：

```text
.claude/settings.json
.claude.json
.config/claude
.config/anthropic
.anthropic
```

安全要求：

- 不写用户真实 `~/.claude/settings.json`。
- 不写用户真实 `.claude.json` 或 Claude auth/cache 目录。
- 如果某个条目会被 runtime 修改，应优先 copy 到 managed home，而不是 symlink 回用户目录。
- 登录态、credential shim 和本地 CLI 认证文件的复用应沿用现有 managed home credential sync 策略。

## DB Provider Materialization

`claude_local` 的 DB provider materialization 不写 settings 文件，而是运行时注入：

| DB 字段 | Claude local 生效方式 |
| --- | --- |
| `provider.apiKey` | 本次子进程 env `ANTHROPIC_API_KEY` |
| `provider.baseUrl` | 本次子进程 env `ANTHROPIC_BASE_URL` |
| `model.modelId` | CLI 参数 `--model <modelId>` |
| `provider.config.env` | 本次子进程 env 补充项 |

这种方式有两个关键性质：

- DB provider 修改后，下一次 run/chat 生效。
- 父进程、本机 shell、Windows 用户/系统环境变量不会被修改。

## `.claude/settings.json` 的定位

`.claude/settings.json` 应被视为 Claude Code 行为配置，可影响：

- permissions
- hooks
- env
- model 默认值
- enabled plugins 或其他 Claude Code 设置

但它不应成为 Octopus DB provider 的主存储。原因：

- Claude settings 没有 OpenCode `opencode.json` 那种明确 provider registry 语义。
- 将 DB provider 写入 settings 会引入上游没有的配置层。
- 明文 API key 不应落入长期 settings 文件。
- Claude CLI 版本变化可能改变 settings 字段语义。

因此，Octopus 可以同步或复制 settings 以获得上游兼容的本地 Claude 行为，但 provider/model
仍应通过 DB 注入到本次子进程 env 和 CLI args。

## 优先级

推荐优先级：

```text
explicit agentRuntimeConfig fields
> DB selected provider/model
> managed/copied Claude settings
> operator home Claude login/session
```

具体规则：

- `agentRuntimeConfig.model` 明确设置时，优先解析该模型引用。
- 未设置 model 时，可使用 runtime default model。
- DB provider 存在时，本次 run 的 `ANTHROPIC_API_KEY` 和 `ANTHROPIC_BASE_URL`
  应覆盖 copied settings 或 operator 环境对本次子进程的影响。
- `agentRuntimeConfig.env` 是显式 runtime 配置；除 `ANTHROPIC_API_KEY` 和
  `ANTHROPIC_BASE_URL` 外应原样保留。若 DB provider 被选中，这两个 key 由 DB
  provider 覆盖，保证 UI/DB 中选择的 provider 是本次 run 的执行真相。

## 与 OpenCode 的差异

`opencode_local` 必须写 managed `.config/opencode/opencode.json`，因为 OpenCode
需要 provider registry：

```text
provider -> options/baseURL/apiKey -> models
```

只传 `--model provider/model` 不足以让 OpenCode 知道 provider 的实现方式。

`claude_local` 不同。Claude CLI 的连接信息可以通过 Anthropic-compatible env 传入，
模型通过 `--model` 传入，本地 subscription/login session 通过 Claude 自己的 home
文件发现。因此 `claude_local` 应采用 env/CLI materialization，而不是 OpenCode 风格
的 provider config 文件 materialization。

## 不推荐方案

不推荐把 DB provider/model 写入 `.claude/settings.json` 作为主路径。

该方案看起来能让 `claude_local` 和 `opencode_local` 在形式上统一，但会造成三个问题：

- 偏离上游 upstream reference 的 Claude local 行为。
- 把 `.claude/settings.json` 扩展成 provider registry，语义不稳。
- 可能把敏感 provider 信息写入长期文件。

如果后续确实需要控制 Claude settings，可引入单独的扩展字段，例如
`agentRuntimeConfig.claudeSettingsPatch`，只用于 permissions/hooks/非敏感行为配置，
并明确它不是 provider/model 控制主路径。

## 验收点

- `claude_local` run 前会准备 managed Claude home，并包含上游同类 Claude 配置/登录态入口。
- DB provider/model 会在 run/chat 调用 runtime 前注入到 `config._octopus.runtimeProvider`。
- `claude_local` 将 provider 转换为本次子进程 env，而不是写入用户全局环境变量。
- `claude_local` 将 model 转换为 `--model <modelId>`。
- 不修改用户真实 `~/.claude/settings.json`。
- 不把明文 API key 写入长期 settings 文件。
- 日志和 meta 输出中的 env 必须脱敏。
