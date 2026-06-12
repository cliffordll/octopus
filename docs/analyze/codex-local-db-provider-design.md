# Codex Local DB Provider 控制设计

## 目标

本文设计 `codex_local` 在 Octopus 中的 provider/model 控制方式。目标是：

- 保持 Codex local runtime 的上游兼容执行语义。
- 复用 Octopus 已有 DB provider/model 管理能力。
- 使用 managed `CODEX_HOME` 隔离 Codex 登录态、配置、session 和 skills。
- 不污染用户真实 shell 环境变量、系统环境变量或 `~/.codex`。
- 不把 DB provider 写入长期 Codex 配置文件作为主路径。

## 当前行为基线

`codex_local` 使用本机 Codex CLI，执行形态是：

```text
codex exec --json --disable plugins --model <model> -c skills.bundled.enabled=false -
```

如果存在可恢复 session，则使用：

```text
codex exec ... resume <sessionId> -
```

当前 runtime 已具备这些边界：

- 默认注入 managed `CODEX_HOME`。
- 使用 `CODEX_HOME/home` 作为子进程 `HOME` / `USERPROFILE`。
- 从 operator home 的 `~/.codex` 同步 Codex credential/config 条目。
- 使用 `CODEX_HOME/skills` 持久化 materialized skills。
- 通过 env 注入 provider API key 和 base URL。
- 通过 CLI 参数注入 model。
- 解析 JSONL stdout，归一化 summary、usage、session 和错误。
- 识别 unknown session，并用 fresh session 自动重试一次。

## Octopus 控制流程

`codex_local` 应采用 managed `CODEX_HOME` + per-run provider 注入模式。

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
codex_local adapter
        |
        +--> resolve CODEX_HOME
        +--> prepare CODEX_HOME/home as managed HOME
        +--> sync operator ~/.codex credentials into CODEX_HOME
        +--> materialize selected skills into CODEX_HOME/skills
        +--> per-run env: OPENAI_API_KEY / OPENAI_BASE_URL
        +--> CLI args: --model <modelId>
        v
codex child process
```

这个流程中，DB provider/model 在每次 run/chat 调用 runtime 前动态生效：

1. server 读取 agent 的 `agent_runtime_type` 和 `agent_runtime_config`。
2. server 调用 `inject_runtime_provider_config()`。
3. 该函数根据 `agentRuntimeConfig.model` 或 runtime 默认模型查询 DB provider/model。
4. 查询结果写入 `context.config._octopus.runtimeProvider`。
5. `codex_local` adapter 读取该运行时配置。
6. adapter 对本次 Codex 子进程设置 env，并构造 CLI 参数。

## Managed CODEX_HOME

如果 `agentRuntimeConfig.env.CODEX_HOME` 未显式配置，`codex_local` 应使用默认 managed home：

```text
<OCTOPUS_HOME>/instances/<instanceId>/organizations/<orgId>/codex-home/agents/<agentId>
```

`CODEX_HOME` 下的职责：

| 路径 | 职责 |
| --- | --- |
| `CODEX_HOME/auth.json` | Codex 登录态或 API auth 相关文件的 managed 副本或链接 |
| `CODEX_HOME/cap_sid` | Codex subscription/session 相关状态 |
| `CODEX_HOME/config.toml` | Codex CLI 本地配置的 managed 副本或链接 |
| `CODEX_HOME/home` | 子进程 `HOME` / `USERPROFILE` |
| `CODEX_HOME/skills` | Octopus materialized Codex skills |

`CODEX_HOME/home` 还会承载通用 CLI credential shim，例如 `.ssh`、`.npmrc`、
`.config/gh` 等，避免 Codex 子进程直接读写 operator home。

安全要求：

- 不写用户真实 `~/.codex`。
- 不写系统环境变量。
- 不修改父进程 shell env。
- 不把 DB provider 的明文 API key 写入长期 `config.toml`。
- 如果从 operator `~/.codex` 复制或链接文件，不能让 DB provider materialization 写回用户真实文件。

## DB Provider Materialization

`codex_local` 的 DB provider materialization 不写 `config.toml`，而是运行时注入：

| DB 字段 | Codex local 生效方式 |
| --- | --- |
| `provider.apiKey` | 本次子进程 env `OPENAI_API_KEY` |
| `provider.baseUrl` | 本次子进程 env `OPENAI_BASE_URL` |
| `model.modelId` | CLI 参数 `--model <modelId>` |
| `provider.config.env` | 本次子进程 env 补充项 |

这种方式有两个关键性质：

- DB provider 修改后，下一次 run/chat 生效。
- Provider secret 只进入本次 Codex 子进程 env，不进入长期 Codex 配置文件。

## Skills Materialization

`codex_local` 和 `claude_local` / `opencode_local` 的 skills 行为不同：

- `codex_local` 使用 persistent mode。
- enabled skills 被 materialize 到 `CODEX_HOME/skills/<slug>/SKILL.md`。
- 普通 skills snapshot 只读当前状态。
- skills sync/enable 会更新持久化 materialization。
- run result 应返回 `loadedSkills`，说明本次 Codex 可发现哪些 skills。

这符合 Codex runtime 的长期 home 语义：同一个 agent 的 Codex skills 应稳定存在于
该 agent 的 managed `CODEX_HOME`，而不是每次 run 使用临时目录。

## Git 和 Credential 边界

`codex_local` 运行时应继续准备 managed Git config：

- `GIT_CONFIG_GLOBAL` 指向 managed `HOME/.gitconfig`。
- `user.useConfigOnly=true`，避免 fallback 到 hostname `.local` 身份。
- 清理不安全的 `.local` author/committer env。
- 注入 GitHub credential helper policy。

这部分和 provider/model 控制分离，但属于 Codex local managed home 的安全边界。

## 优先级

推荐优先级：

```text
explicit agentRuntimeConfig fields
> DB selected provider/model
> managed CODEX_HOME config/auth
> operator ~/.codex credential source
```

具体规则：

- `agentRuntimeConfig.env.CODEX_HOME` 明确设置时，尊重该路径。
- 未设置 `CODEX_HOME` 时，使用 Octopus instance/org/agent scoped 默认路径。
- `agentRuntimeConfig.model` 明确设置时，优先解析该模型引用。
- 未设置 model 时，可使用 runtime default model。
- DB provider 存在时，本次 run 的 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`
  应覆盖 managed `config.toml` 或 operator 环境对本次子进程的影响。
- `agentRuntimeConfig.env` 是显式 runtime 配置；除 `OPENAI_API_KEY` 和
  `OPENAI_BASE_URL` 外应原样保留。若 DB provider 被选中，这两个 key 由 DB
  provider 覆盖，保证 UI/DB 中选择的 provider 是本次 run 的执行真相。

## 与 OpenCode 的差异

`opencode_local` 必须写 managed `.config/opencode/opencode.json`，因为 OpenCode
需要 provider registry：

```text
provider -> options/baseURL/apiKey -> models
```

`codex_local` 不同。Codex CLI 的 provider 连接信息可以通过 OpenAI-compatible env
传入，模型通过 `--model` 传入，登录态和本地配置通过 `CODEX_HOME` 发现。因此
`codex_local` 应采用 env/CLI materialization，而不是 OpenCode 风格的 provider
config 文件 materialization。

## 不推荐方案

不推荐把 DB provider/model 写入 `CODEX_HOME/config.toml` 作为主路径。

该方案的问题：

- 会把 per-run provider 选择写入长期 runtime state。
- DB 中的明文 provider secret 可能落到长期文件。
- 多次 run、多个 provider 或 model fallback 场景下，长期 config 容易变成隐式状态源。
- 它与当前 `inject_runtime_provider_config()` 的动态注入模型不一致。

如果后续需要控制 Codex CLI 的非敏感固定配置，可引入单独字段，例如
`agentRuntimeConfig.codexConfigPatch`，只用于非敏感 CLI 行为配置，并明确它不是
provider/model 控制主路径。

## 验收点

- 未显式设置 `CODEX_HOME` 时，`codex_local` 使用 org/agent scoped managed `CODEX_HOME`。
- `CODEX_HOME/home` 是子进程 `HOME` / `USERPROFILE`。
- operator `~/.codex` 的 auth/config 入口可被同步到 managed `CODEX_HOME`。
- DB provider/model 会在 run/chat 调用 runtime 前注入到 `config._octopus.runtimeProvider`。
- `codex_local` 将 provider 转换为本次子进程 env，而不是写入用户全局环境变量。
- `codex_local` 将 model 转换为 `--model <modelId>`。
- 不把明文 API key 写入长期 `config.toml`。
- enabled skills 能 materialize 到 `CODEX_HOME/skills`。
- run result 返回 `loadedSkills`、`billingType`、`biller`、usage 和 session。
- unknown session 能自动 fresh retry，并在结果中表达是否需要清理旧 session。
