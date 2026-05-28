# Step 14: Runtime Adapter 扩展

状态：需补齐

## 上游依据

- 参考工程：本地上游参考仓库
- Runtime 枚举：`packages/shared/src/constants.ts`
- Runtime registry：`server/src/agent-runtimes/registry.ts`
- Server 内置 adapter：`server/src/agent-runtimes/process/`、`server/src/agent-runtimes/http/`
- Local runtime packages：`packages/agent-runtimes/codex-local/`、`packages/agent-runtimes/claude-local/`、`packages/agent-runtimes/opencode-local/`
- 环境检查入口：`POST /api/orgs/:orgId/adapters/:type/test-environment`
- Skills schema：`packages/shared/src/validators/adapter-skills.ts`、`packages/shared/src/types/adapter-skills.ts`
- Agent instructions materialization：`server/src/routes/agents.ts` 中 `materializeDefaultInstructionsBundleForNewAgent`
- Runtime quota windows：`getQuotaWindows` adapter capability

## 依赖边界

Step 11 已定义统一 adapter contract，并由 11C 提供 `process` 路径、由 11E 提供 `codex_local` 智能体执行路径。本步骤扩展其余上游 runtime 覆盖范围，不承担首次打通 Agent 交互执行闭环。

Step 13 已补齐 run 调度、取消、恢复和事件查询。本步骤必须复用既有 run 状态机，不新增独立执行模型。

Step 15 仍负责 execution workspace 生命周期、workspace runtime service、运行产物和清理；但 Step 14 必须先补齐 runtime adapter 可消费的 managed instructions、skills、model discovery、environment test 和 quota window probe 能力。

Step 16 仍负责 cost、budget、activity 查询与治理联动；但 Step 14 必须先提供 adapter 侧 quota window 原始获取能力和运行结果中的 usage 基础归一化。

## 14A：HTTP Adapter

- 实现 `http` runtime adapter。
- 支持 `url`、`method`、`headers`、`payloadTemplate`、`timeoutSec` 等上游配置字段。
- 将 HTTP 状态、响应 body、超时和网络错误归一化为 `RuntimeExecutionResult`。
- 确保 heartbeat run 与 chat direct invocation 均通过统一 adapter contract 调用。

## 14B：Runtime 环境检查

- 新增上游兼容路径 `POST /api/orgs/{orgId}/adapters/{type}/test-environment`。
- 输入使用 `agentRuntimeConfig`，输出包含 runtime type、整体 status、checks 与 tested timestamp。
- status/check level 语义向上游 `pass`/`warn`/`fail` 与 `info`/`warn`/`error` 对齐；Python 内部可保留适配层，但 API 响应不得使用无法映射的自造状态。
- `process`、`codex_local`、`http`、`claude_local`、`opencode_local` 返回可执行的环境检查结果。
- `codex_local` 检查 cwd、command resolvable、认证线索和 hello probe。
- `claude_local` 检查 cwd、command resolvable、API key/subscription auth 线索和 hello probe。
- `opencode_local` 检查 cwd、command resolvable、model discovery、model configured/available 和 hello probe。
- `http` 检查 url、method、协议与 endpoint probe。
- 对当前不实施的 runtime 返回兼容的 unavailable/failed 检查结果，不抛出未实现异常。

## 14C：本地 CLI Adapter

- 实现 `claude_local` runtime adapter。
- 实现 `opencode_local` runtime adapter。
- 两个本地 CLI adapter 必须复用现有 child process 运行、取消、日志和 `processPid/processStartedAt` 记录边界。
- `claude_local` 不得只是 `process` 薄封装；必须按上游使用 `claude --print - --output-format stream-json --verbose` 基础形态，支持 `model`、`effort`、`maxTurnsPerRun`、`dangerouslySkipPermissions`、`chrome`、`extraArgs/args`、`cwd`、`env`、`timeoutSec`、`graceSec`。
- `claude_local` 必须解析 stream-json，归一化 summary、session id、usage、max turns、login required、非 0 退出、timeout 和取消结果。
- `opencode_local` 不得只是 `process` 薄封装；必须按上游使用 `opencode run --format json --model <provider/model>` 基础形态，支持 `model`、`variant`、`extraArgs/args`、`cwd`、`env`、`timeoutSec`、`graceSec`。
- `opencode_local` 必须解析 json/jsonl 输出，归一化 summary、session id、usage、model unavailable、auth required、非 0 退出、timeout 和取消结果。
- `codex_local` 需要补齐上游已有但当前缺失的运行边界：managed CODEX_HOME、credential home sync、benign stderr 过滤、unknown session 识别、tool session error 识别、usage/biller 字段归一化和 loaded skills 元数据。
- `claude_local`、`codex_local`、`opencode_local` 需要注入上游兼容 runtime env、agent/run context、local agent JWT 兼容边界；真实 secret/env 解析归 Step 19，但本步骤要保留结构兼容入口。

## 14D：模型发现与 Skills Sync

- 实现 runtime model discovery 的服务端兼容边界。
- 实现 runtime skills sync 的服务端兼容边界。
- `process`、`http` 可返回空模型/空 skills 或不支持结果，但响应结构必须兼容。
- `codex_local` 模型发现需要对齐上游：优先通过 OpenAI models API 或配置文件可用 key 发现模型，失败时合并/回退到内置 fallback models，并带缓存。
- `opencode_local` 模型发现需要对齐上游：执行 `opencode models`、解析 `provider/model` 输出、排序去重、缓存并在失败时返回空列表而不是破坏业务 API。
- `claude_local` 可使用上游静态 models 列表；列表内容应来自上游包证据，不使用任意自造模型名。
- `codex_local` skills snapshot 需要读取 runtime skills entries、解析 desired skills、检测 managed CODEX_HOME/skills 安装状态，返回 `persistent` mode、entries、warnings 和状态字段。
- `claude_local` skills snapshot 需要读取 runtime skills entries、解析 desired skills、检测 `~/.claude/skills` 外部安装项，返回 `ephemeral` mode、entries、warnings 和状态字段。
- `opencode_local` skills snapshot 需要读取 runtime skills entries、解析 desired skills、检测 Claude-compatible skills home 外部安装项，返回 `ephemeral` mode、entries、warnings 和状态字段。
- `POST /api/agents/{id}/skills/sync` 使用上游一致的 `desiredSkills` 入参，更新 agent enabled skills 选择，清理持久化 adapter skill sync 配置，返回最新 snapshot，并记录 `agent.skills_synced` activity。
- 新增 `POST /api/agents/{id}/skills/enable`，使用 `skills` 入参向当前 enabled skills 追加选择，返回最新 snapshot，并记录 `agent.skills_enabled` activity。
- 新增 `POST /api/agents/{id}/skills/private`，创建 agent private skill，返回 skill entry，并记录 `agent.private_skill_created` activity。
- 新增 `GET /api/agents/{id}/skills/analytics`，返回 agent skills 使用 analytics；数据可先基于已持久化 heartbeat/run event 能力实现，不能自造与上游不兼容的响应结构。
- `desiredSkills` 不能只保存在临时响应中；必须能被 Agent detail、configuration、skills snapshot/sync/enable 后续查询稳定读取。

## 14E：Agent Instructions Materialization

- 创建 `codex_local`、`claude_local`、`opencode_local` agent 时，如果未显式设置 `instructionsRootPath`、`instructionsFilePath` 或 `agentsMdPath`，需要按上游加载默认 managed instructions bundle。
- `agentRuntimeConfig.promptTemplate` 作为角色/persona 内容覆盖 managed bundle 的 `SOUL.md`，materialize 后从持久化 adapter config 中移除 `promptTemplate` 与 `bootstrapPromptTemplate`。
- 已显式配置 instructions path 的 agent 不应被自动覆盖。
- 需要支持相对 instructions path 解析到 `agentRuntimeConfig.cwd`，且 cwd 必须是绝对路径；非法路径返回 422。
- 需要提供 target agent 或上级 manager 可更新 instructions path 的访问边界；真实认证来源仍复用当前开发 actor/agent actor 结构。

## 14F：Runtime Quota Window Probe

- `codex_local` 和 `claude_local` adapter 需要提供上游已有的 quota window probe 能力。
- 本步骤只负责 adapter 侧原始 quota window 获取与标准化输出；预算限制、治理联动、查询聚合仍归 Step 16。
- probe 失败必须返回可解释错误，不得影响普通 run、model discovery 或 skills API。

## 14G：Registry 与错误归一化

- Registry 不再对已知 runtime type 直接抛出 Python 内部异常；未实施 runtime 应返回可解释的 adapter unavailable 失败。
- unknown runtime type 行为需要对齐上游 fallback 策略或在 contract 中明确 Python 兼容层差异；不能出现未捕获内部异常。
- registry 需要暴露 adapter metadata：models/listModels、skills capability、environment test、quota window capability、local agent JWT support、agent configuration doc。
- Run 结果中的 `errorCode`、`error`、`resultJson`、`usageJson` 和 `sessionIdAfter` 不因 adapter 类型不同而改变外部结构。
- Contract tests 覆盖 runtime type 接入、环境检查 path、模型发现、skills sync 和未实施 runtime 的错误形态。

## 当前实施记录

以下为当前已实现基线，不代表 Step 14 已满足上游全量要求：

- Shared 已新增 adapter models、environment test、agent skills snapshot/sync API path、validator 和响应类型。
- Runtime registry 已接入 `http`、`claude_local`、`opencode_local`，并对当前未纳入的已知 runtime 返回 unavailable adapter。
- `http` adapter 已支持 `url`、`method`、`headers`、`payloadTemplate`、`timeoutSec`，并将 HTTP 成功、非 2xx、超时和网络错误归一化为 `RuntimeExecutionResult`。
- `claude_local` 已从通用 process 薄封装升级为独立 adapter，构造 `claude --print - --output-format stream-json --verbose` 基础命令，支持 stdin prompt、model/effort/max turns/permission/chrome/extra args、session、summary、usage、cost、login required、max turns、timeout 和取消结果归一化。
- `opencode_local` 已从通用 process 薄封装升级为独立 adapter，构造 `opencode run --format json` 基础命令，支持 stdin prompt、model、variant、extra args、session、summary、usage、cost、provider、auth/model error、timeout 和取消结果归一化。
- Server 已新增 `GET /api/orgs/{orgId}/adapters/{type}/models`、`POST /api/orgs/{orgId}/adapters/{type}/test-environment`、`GET /api/agents/{id}/skills`、`POST /api/agents/{id}/skills/sync`。
- Runtime model discovery 与 skills sync 已提供兼容响应结构；当前 `process`/`http` 返回空能力，`codex_local`/`claude_local`/`opencode_local` 返回基础模型或同步结果。
- Agent 已补齐上游兼容的说明与技能字段边界：`capabilities` 作为智能体能力说明直接持久化，`agentRuntimeConfig.promptTemplate` 作为 runtime prompt 配置透传，`desiredSkills` 通过 `agent_enabled_skills` 持久化并在 Agent detail、configuration、skills snapshot/sync 中返回。
- Skills sync 已使用上游一致的 `desiredSkills` 入参，成功同步后记录 `agent.skills_synced` 活动。
- Skills snapshot/sync 已支持 `skillsRootPath` 下 `<skill>/SKILL.md` 的基础 runtime entries 扫描，返回 key、selectionKey、runtimeName、description、source path、workspace edit path、desired/configured 状态；`codex_local` 使用 `persistent` mode，`claude_local` 与 `opencode_local` 使用 `ephemeral` mode。
- 内置 bundled skills 已按当前项目约定落地到 `server/skills/bundled/`，默认纳入 skills snapshot；未显式配置 `skillsRootPath` 的本地 runtime agent 也能发现 bundled skills。该目录是资源目录，不是 Python 包，已从 pyright/ruff 项目代码检查中排除。
- `codex_local` skills sync 已补齐运行时 materialization：`POST /api/agents/{id}/skills/sync` / `enable` 会把 desired bundled/organization skill 写入 managed `CODEX_HOME/skills/<skill>`；优先使用 `agentRuntimeConfig.env.CODEX_HOME`，未配置时使用服务端内部 agent runtime home。普通 `GET /skills` 只读 snapshot，不写运行时 home。
- `codex_local` 执行时已补齐 managed `CODEX_HOME` 默认注入：未显式配置 `env.CODEX_HOME` 时，运行时使用 `.octopus/runtime-homes/codex_local/<orgId>/<agentId>`，与 skills sync 的默认 materialization 位置一致。
- `codex_local` 执行时已补齐 managed runtime `HOME/USERPROFILE`：默认指向 `CODEX_HOME/home`，并从 operator home 同步常见本地 CLI 凭据目录/文件（如 `.ssh`、`.npmrc`、`.config/gh`），避免 Codex 直接污染或误读用户全局 home。
- `codex_local` heartbeat run 已把 `sessionIdBefore` 注入 runtime context；执行时会先使用 `codex exec ... resume <sessionId> -`，如果上游兼容 unknown session/rollout missing 错误出现，则记录日志并用 fresh session 自动重试一次。
- `codex_local` 已注入上游兼容 runtime env/context：基础 `RUDDER_AGENT_ID`、`RUDDER_ORG_ID`、`RUDDER_RUN_ID`、`RUDDER_API_URL`，wake/task/approval 字段，workspace 字段，agent/org workspace 路径字段，以及 runtime service JSON/primary URL。
- `codex_local` 执行结果已返回当前 `CODEX_HOME/skills/<slug>/SKILL.md` 中可发现的 `loadedSkills` 元数据，并在 `usageJson`/`resultJson` 中补齐 `billingType` 与 `biller` 基础归一化。
- `codex_local` 已过滤 Codex telemetry/analytics 类 benign stderr 噪声，并按上游逻辑抑制 closed stdin tool-session lifecycle warning，避免把该类工具会话告警误报为业务失败原因。
- Skills snapshot 已补齐上游状态语义：Codex persistent entries 能区分 `available`、`missing`、`installed`、`stale`、`external`；Claude/OpenCode ephemeral entries 保持 desired `configured`，并只检测用户 Claude-compatible skills home 中的额外外部安装项。
- Skills enable/private/analytics 已补齐服务端契约闭环：`skills/enable` 追加 enabled skills 并记录 `agent.skills_enabled`，`skills/private` 返回 agent private skill entry 并记录 `agent.private_skill_created`，`skills/analytics` 返回上游兼容空统计结构，后续真实归集复用 run/event 记录。
- Agent-private skill 已按上游 `AGENT_HOME/skills/<slug>/SKILL.md` 语义文件化；Python 版当前 `AGENT_HOME` 解析到服务启动目录下 `.octopus/workspaces/org_<orgId>/agents/<agentWorkspaceKey>/`，因此实际文件路径为 `.octopus/workspaces/org_<orgId>/agents/<agentWorkspaceKey>/skills/<slug>/SKILL.md`。返回 entry 使用 `selectionKey=agent:<slug>`、`sourceClass=agent_home`、`origin=user_installed`、`state=external`；enable 后可被 Codex materialize 到 managed `CODEX_HOME/skills/<slug>`。
- Runtime registry 已暴露 adapter metadata/config doc 与 quota window probe 兼容接口；`codex_local`、`claude_local` 返回 provider quota probe 失败结构，未纳入 runtime 返回 unavailable 结构，不影响普通 run/model/skills API。
- Tests 已覆盖 Step 14 contract、environment/model/skills API、未纳入 runtime unavailable 响应、`http` heartbeat run 执行，以及 `claude_local`/`opencode_local` 本地 CLI 执行链路。

## 剩余开发拆分

Step 14 剩余工作必须先补齐控制面可调用的服务端契约，再深化本地 CLI adapter 的真实执行细节。这样可以让 UI/CLI 先依赖稳定 API，不把 workspace、governance 或真实 secret/env 接入提前混入本步骤。

### 14R1：服务端契约闭环

本轮目标是补齐 runtime 能力发现、skills 管理和 quota probe 的 API/contract 形态，不处理本地 CLI 的深度协议解析。

- 新增 `/api/agents/{id}/skills/enable`，使用 `skills` 入参追加 enabled skills，复用 `agent_enabled_skills` 持久化，返回最新 snapshot，并记录 `agent.skills_enabled` activity。
- 新增 `/api/agents/{id}/skills/private`，创建 agent private skill 兼容响应；如当前缺少上游完整持久化证据，先落在 runtime skill entry 兼容边界，不引入无证据业务表。
- 新增 `/api/agents/{id}/skills/analytics`，基于现有 run/event/activity 记录返回兼容结构；没有可归集数据时返回空统计，不自造使用量。
- 扩展 runtime adapter contract，增加 metadata/config doc 暴露，包含 models、skills、environment test、quota window、local agent JWT 和 agent configuration doc 能力声明。
- 扩展 runtime adapter contract，增加 quota window probe；`codex_local`、`claude_local` 返回标准化原始 probe 结果，失败时返回可解释错误；其他 runtime 返回 unsupported/unavailable 兼容结果。
- `process`、`http` 和未纳入 runtime 不得因为新增 metadata、skills 或 quota 接口抛出内部异常。
- 补齐 shared path、types、validators、service、route、contract tests 和 workflow tests。
- 更新本文件的当前实施记录与待补齐清单。

### 14R2：本地 CLI Adapter 深化

本轮目标是把 `codex_local`、`claude_local`、`opencode_local` 从基础可执行升级为上游兼容的本地 runtime adapter 行为。

- `claude_local` 改为独立 adapter，不再只依赖通用 `process` 薄封装；构造 `claude --print - --output-format stream-json --verbose` 基础命令。
- `claude_local` 解析 stream-json，归一化 summary、session id、usage、max turns、login required、非 0 退出、timeout、取消和 stderr。
- `opencode_local` 改为独立 adapter，不再只依赖通用 `process` 薄封装；构造 `opencode run --format json --model <provider/model>` 基础命令。
- `opencode_local` 解析 json/jsonl 输出，归一化 summary、session id、usage、model unavailable、auth required、非 0 退出、timeout、取消和 stderr。
- `codex_local` 补齐 managed `CODEX_HOME`、credential home sync、benign stderr 过滤、unknown session/tool session error 识别、usage/biller 字段归一化和 loaded skills 元数据。
- `codex_local`、`claude_local`、`opencode_local` 注入上游兼容 runtime env、agent/run context 和 local agent JWT 结构入口；真实 secret/env 解析仍留给 Step 19。
- 将 environment test 升级为真实 probe：cwd、command resolvable、auth 线索、hello probe、OpenCode model probe、HTTP endpoint probe。
- 将 model discovery 升级为 Codex/OpenCode 发现与缓存，Claude 使用上游静态列表。
- 将 skills snapshot/sync 升级为 runtime skills entries 扫描、desired selection、installed/external/missing 状态和 persistent/ephemeral mode。
- 补齐新建本地 runtime agent 的 managed instructions materialization 和 instructions path 更新边界。
- 增加针对 stdout/stderr 协议、错误归一化、session/usage、loaded skills 和 cancellation 的 contract/workflow tests。

## 待补齐清单

- 补齐 `claude_local` managed HOME/credential 和 skills 注入。
- 补齐 `opencode_local` managed HOME/credential、model requirement 和 skills 注入。
- 继续补齐 `codex_local` 上游运行细节：local agent JWT/API key 兼容入口，以及更完整的 provider/biller 识别。
- 将 environment test 从“配置存在”升级为真实 probe：cwd、command、auth、hello probe、OpenCode model probe、HTTP endpoint probe。
- 将 model discovery 从静态列表升级为 Codex/OpenCode 上游发现与缓存。
- 继续深化 skills snapshot/sync：Codex materialization、private skill 文件化、默认 managed `CODEX_HOME`/`HOME` 注入、credential home sync、runtime env/context 注入、unknown session retry 和 loaded skills 元数据已具备基础闭环；后续还需补齐 Claude/OpenCode run 时 ephemeral mount 的真实注入。
- 补齐新建本地 runtime agent 的 managed instructions bundle materialization 和 instructions path 更新边界。
- 将 adapter quota window probe 从可解释失败结构升级为真实 provider quota 读取。

### Skills 剩余工作拆分

- `codex_local` 已支持 desired bundled/organization/agent-home skill materialize 到 managed `CODEX_HOME/skills`，并在执行结果中返回 `loadedSkills` 元数据，保证 run 记录能说明实际加载了哪些 skill。
- `claude_local` 与 `opencode_local` 当前只做 snapshot/外部安装项检测；后续需要在 run 启动前把 desired skills 以 ephemeral 方式挂载或复制到 CLI 可发现的 skills home，并在 run 结束后按上游语义清理或保留。
- `POST /api/agents/{id}/skills/private` 已落地为 agent home skill 文件，能被 snapshot 发现、enable，并参与 Codex materialization；后续仍需让 Claude/OpenCode 在 run 时 ephemeral mount 这些 desired agent-home skills。
- Organization skills 管理 API 不属于 runtime adapter 本身；Step 14 只消费 `skillsRootPath`、bundled skills 和 future organization skill entries，不负责 organization skill 的创建、编辑、删除和权限治理。
- External skills 当前只读检测为 `external`；Step 14 不做导入或接管。若后续纳入外部 skill 导入，需进入独立 skills 管理步骤。

## 不包含

- `gemini_local`、`cursor`、`pi_local` 本步骤不做。
- `openclaw_gateway`、`hermes_local` 本步骤不做完整执行实现。
- Workspace 生命周期与产物持久化，归 Step 15。
- Workspace runtime service 建立、复用、释放和停止，归 Step 15。
- Cost/budget 治理，归 Step 16。
- Quota window 的归集、展示和治理联动归 Step 16；adapter 侧 quota window probe 属于本步骤。
- 触发 Codex Agent 的最小 conversation/message 链路，归 Step 11F。

## 验收

- `http` adapter 可以通过 heartbeat run 执行，并将成功、非 2xx、超时和网络错误写入兼容 run 结果。
- Runtime environment test API 对 `process`、`codex_local`、`http`、`claude_local`、`opencode_local` 有真实 probe 结果；对 `gemini_local`、`cursor`、`pi_local`、`openclaw_gateway`、`hermes_local` 返回可解释的未纳入结果。
- `codex_local`、`claude_local` 与 `opencode_local` 的执行、取消、日志、进程元数据、session、usage、loaded skills、认证错误、模型错误和失败行为复用 Step 11/13 的 adapter contract 与 run 状态机。
- Runtime model discovery 对 `codex_local` 与 `opencode_local` 有上游兼容发现与缓存，对 `claude_local` 有上游静态模型列表，对未纳入 runtime 有明确未支持结果。
- Skills snapshot、sync、enable、private skill、analytics 对已纳入 runtime 有上游兼容响应结构和 activity 副作用。
- 创建本地 runtime Agent 时，`capabilities`、`desiredSkills`、managed instructions bundle、`SOUL.md` 覆盖和 runtime config 清理行为与上游一致。
- Adapter quota window probe 对支持 runtime 可调用，失败可解释，且不影响普通 run。
- Tests 证明 runtime 差异不会改变业务 API 或 run 状态语义。
