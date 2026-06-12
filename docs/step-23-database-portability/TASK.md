# Step 23: Database Portability / Persistence Hardening

状态：开发中

## 背景

当前持久化层已经通过 SQLAlchemy async engine、request-scoped session 和 `packages/database/queries/` 形成统一入口。默认数据库是 SQLite，文档推荐 PostgreSQL；MySQL 目前不是验证目标。

EPAI/POD 写入链路需要生产级数据库能力，不能依赖 SQLite 的单写者锁模型。为避免把数据库差异泄漏到业务 service，本步骤单独收口数据库操作接口、方言兼容和测试矩阵。

另一个需要同步收口的问题是数据库位置与上游 instance layout 对齐。上游 Rudder 默认使用 embedded PostgreSQL，并把数据库 cluster 放在 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db`。Octopus 即使继续支持 SQLite，也应保持同样的 instance-scoped 语义：SQLite 文件默认放在 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db`，而不是随进程 cwd 生成 `./octopus.db`。关键约束是 DB、workspace、runtime home、storage、run logs 和 server logs 必须属于同一个 instance root。详细路径问题记录见 `docs/analyze/agent-runtime-bugs.md` 的 Bug 12。

## 目标

在保持 routes/services 调用方式稳定的前提下，使持久化层能通过 `OCTOPUS_DATABASE_URL` 选择 SQLite、PostgreSQL 或 MySQL，并用少量 database dialect helper 处理底层差异。

目标分层：

```text
routes
  -> services
    -> packages/database/queries 统一数据操作接口
      -> packages/database dialect/helper 处理方言差异
        -> SQLite / PostgreSQL / MySQL
```

## 任务

- 明确数据库支持矩阵：
  - SQLite：local/dev/demo。
  - PostgreSQL：推荐生产路径。
  - MySQL：兼容生产路径。
- 对齐数据库位置和 instance layout：
  - 显式设置 `OCTOPUS_HOME` 时，以显式配置为准。
  - 未设置 `OCTOPUS_HOME` 时，默认 home 仍是用户目录下的 `.octopus`，与上游默认 `~/.rudder` 语义对齐。
  - SQLite 默认 URL 不再是 `sqlite+aiosqlite:///./octopus.db`；应解析为 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db`。
  - 本地开发若显式设置 `OCTOPUS_HOME=.octopus`，SQLite 默认文件应为 `<当前目录>/.octopus/instances/default/db/octopus.db`。
  - 使用 PostgreSQL/MySQL 外部连接时，数据库连接不会携带文件侧 instance root；部署配置或启动器必须显式绑定 `OCTOPUS_HOME` / `OCTOPUS_INSTANCE_ID`。
  - 文档需要说明数据库连接和文件侧 instance root 的关系，避免 DB 在一个位置、workspace/runtime home 在另一个位置。
- 检查已有绝对路径迁移风险：
  - `agents.agent_runtime_config.instructionsRootPath`、`instructionsFilePath` 等 managed path 可能已持久化旧 home。
  - 数据库位置或 home 规则修正后，需要保留或补强 reconcile 逻辑，确保 managed instructions、agent workspace home、workspace browser 读取同一 canonical path。
- 增加 MySQL async driver 依赖和连接串文档，例如 `mysql+asyncmy://...`。
- 扩展 engine factory：
  - SQLite 设置必要 pragma。
  - PostgreSQL 使用 asyncpg 生产配置。
  - MySQL 设置 charset、pool pre-ping、pool recycle 等连接稳定性配置。
- 新增 database dialect helper，统一处理：
  - `RETURNING` 支持差异。
  - update/delete 后返回 row 的跨方言实现。
  - JSON/JSONB 类型差异。
  - partial index 或条件唯一约束差异。
  - timezone datetime 行为。
  - boolean/default/server_default 行为。
- 改造 `packages/database/queries/` 中 MySQL 不稳定或不支持的 `.returning(...)` 调用，保持 service 层接口不变。
- 检查 Alembic migration 对 PostgreSQL/MySQL/SQLite 的兼容性，必要时按 dialect 分支实现等价约束。
- 增加数据库测试矩阵，至少覆盖：
  - migration smoke。
  - agents/chats/issues/organization skills 写入。
  - activity query。
  - transaction rollback。
  - cross-org scope。

## 边界

- 不拆成多套 service 实现；service 层不得出现业务级 `if mysql/postgres/sqlite` 分支。
- 不把 MySQL 作为唯一生产推荐；PostgreSQL 仍是优先生产路径。
- 不迁移线上数据；本步骤只提供代码和迁移兼容能力。
- 不把数据库 URL 当作完整 instance 隔离方案；SQLite/PostgreSQL/MySQL 都必须与文件侧 instance root 绑定清楚。
- 不重做 Step 25 activity、Step 27 cost、Step 28 governance 的业务语义。

## 验收

- SQLite 现有 contract/workflow tests 继续通过。
- PostgreSQL migration smoke 和核心写入测试通过。
- MySQL migration smoke 和核心写入测试通过。
- `agents/chats/issues/skills` 写入接口在三类数据库上使用同一 service/query API。
- SQLite 默认文件位于 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db`，外部 PostgreSQL/MySQL 与显式 `OCTOPUS_HOME`、`OCTOPUS_INSTANCE_ID` 的关系有明确文档和测试覆盖。
- 切换 home 或数据库位置后，已有 managed instructions 绝对路径不会导致 workspace browser、agent workspace home 和 runtime 读取目录分裂。
- 文档说明 `OCTOPUS_DATABASE_URL` 三类连接串、推荐生产路径和已知限制。

## 当前交付记录

- 默认 SQLite URL 已改为 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db`，`OCTOPUS_HOME` 默认回到用户目录 `.octopus`，不再从数据库 URL 反推。
- engine factory 已按 dialect 配置 SQLite/PostgreSQL/MySQL：SQLite 自动创建父目录并保留 pragma，PostgreSQL/MySQL 启用连接健康检查，MySQL 使用 `utf8mb4` 和连接 recycle。
- 已加入 MySQL async driver：`asyncmy`。
- 已新增 `packages/database/queries/_compat.py`，用于 query 层收口跨数据库 `RETURNING` 差异。
- 已改造当前阻塞面核心写路径：agents、chats、issues、organization skills，以及 issue counter / checkout issue。
- MySQL migration 已处理 baseline partial unique index 的直接兼容问题：MySQL 路径降级为普通非唯一索引，并在 migration README 记录等价约束待补。
- README、UI README、CLI README、migration README 和相关历史分析文档已同步默认 SQLite layout、PostgreSQL/MySQL 连接串和外部数据库与 instance root 的关系。
- 新增 `tests/contract/test_step23_database_portability.py` 覆盖默认数据库 URL、SQLite 父目录创建、核心 write returning fallback；更新 workspace path 测试覆盖新 instance db layout。

## 剩余风险 / 后续项

- 尚未对真实 PostgreSQL/MySQL 服务执行 live migration smoke；当前验证仍以 SQLite 和 fallback 单元路径为主。
- `packages/database/queries/` 中仍有 workspace、runtime provider、resources、goals、heartbeat、approvals 等非本轮阻塞面的 `.returning(...)` 调用，若要宣称完整 MySQL 支持，需要继续迁到 dialect helper。
- MySQL 下 `issues_open_automation_execution_uq` 目前不是 partial unique 的语义等价实现；需要后续用 MySQL generated column、函数索引或应用层锁补齐。

## Step 23B: Runtime Provider Scope & Defaults

状态：待开发

### 背景

当前 runtime provider/model 配置已经落地为 `runtime_providers` 和 `runtime_models`，但两张表实际是 organization scoped：唯一约束包含 `org_id`，API 也挂在 `/api/orgs/{orgId}/runtime-providers` 下。

这会造成一个明显的使用问题：用户在一个 organization 里录入 provider、api key、base URL 和 models 后，切换到另一个 organization 还需要重新录入。provider/model 连接配置本质上可以在当前 Octopus instance 内复用，而 organization 更适合只保存默认选择或私有覆盖。

本子步骤不引入真实 user scope。真实用户、权限和 secret store 仍归 Step 29；本步骤只先建立 `global + organization + agent override` 的数据模型和解析规则。

### 目标

把 runtime provider/model 从单一 organization scope 升级为两层可见性：

```text
global: 当前 Octopus instance 内所有用户、所有 organization 可见
organization: 仅当前 organization 可见
```

默认模型解析规则：

```text
run/request override
  > agent override
  > organization default
  > global default
  > setup required
```

### Schema 规划

现有表改名，显式表达 organization scope：

```text
runtime_providers -> runtime_organization_providers
runtime_models    -> runtime_organization_models
```

新增 global catalog 和默认选择表：

```text
runtime_global_providers
runtime_global_models
runtime_model_defaults
```

`runtime_global_providers` 保存 instance 内共享 provider 连接配置：

```text
id
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
unique(runtime_type, provider_id)
```

`runtime_global_models` 保存 global provider 下的共享 model catalog：

```text
id
runtime_type
provider_id
model_id
display_name
metadata
enabled
created_at
updated_at
unique(runtime_type, provider_id, model_id)
```

`runtime_organization_providers` 和 `runtime_organization_models` 保留当前 organization-only 配置语义，字段与现有表基本一致，唯一约束继续包含 `org_id`。

`runtime_model_defaults` 保存“默认选择指针”，不保存 provider 连接信息：

```text
id
scope_type              -- global | organization | agent
scope_id                -- global 用空字符串；organization/agent 为对应 id
runtime_type
provider_scope_type     -- global | organization
provider_id
model_id
created_at
updated_at
unique(scope_type, scope_id, runtime_type)
```

### API / Service 行为

- 保留现有 organization runtime provider API，但返回列表应包含：
  - global providers/models。
  - 当前 organization providers/models。
  - 每项带 `scope: "global" | "organization"`。
- 创建 provider/model 时，默认建议创建到 global scope；UI/API 允许显式选择 organization-only。
- organization 可以设置自己的 default model，覆盖 global default。
- agent 仍可通过 `agentRuntimeConfig.model` 覆盖默认；后续可把 agent default 迁入 `runtime_model_defaults(scope_type="agent")`。
- runtime 执行前统一调用 provider/model resolver，避免 chat、heartbeat、adapter 各自解析。
- API response 继续 redaction `apiKey`，并保留 `hasApiKey`。

### 迁移策略

- 将现有 `runtime_providers` 重命名为 `runtime_organization_providers`。
- 将现有 `runtime_models` 重命名为 `runtime_organization_models`。
- 更新 ORM、queries、routes、tests 和文档中的表名引用。
- 现有 organization-scoped 数据不自动提升到 global，避免意外扩大 secret 可见范围。
- 可以提供后续“promote to global”操作，把某个 organization provider/model 复制到 global scope。

### 边界

- 不实现真实 user-level provider/model。
- 不实现 secret store、secret rotation 或 user credential isolation；这些归 Step 29。
- 不把 global 理解为跨 instance 或跨部署共享；global 只表示当前 Octopus instance 内共享。
- 不重做 Step 27 cost 或 Step 28 quota/governance。

### 验收

- 在一个 organization 创建 global provider/model 后，切换到另一个 organization 能直接看到并选择。
- organization-only provider/model 不会出现在其他 organization。
- organization default 覆盖 global default。
- agent override 覆盖 organization/global default。
- `codex_local`、`claude_local`、`opencode_local` 执行时仍能正确注入 provider apiKey/baseURL/model。
- provider API key 在 response、activity、revision 和日志中继续脱敏。
- migration 后既有 organization provider/model 数据仍可被原 organization 使用。

## Step 23C: Instance Filesystem Layout & Legacy Path Migration

状态：已完成

详细设计与实施要求见 `docs/analyze/agent-runtime-bugs.md` 的 Bug 12。

验收摘要：

- 上游对齐路径下能看到 organization workspace、agent workspace home、runtime managed home、storage、run logs 和 server logs。
- `.octopus/runtime-homes/...` 和 `.octopus/instances/<instance>/runtime-homes/...` 不再作为目标目录；访问对应 runtime 时 lazy migration 到 organization-scoped runtime home。
- `.octopus/instances/<instance>/workspaces` 不再作为目标目录；organization workspace 始终位于 `organizations/<orgId>/workspaces`。
- 测试覆盖 legacy runtime home、legacy organization workspace、错误 instance workspaces、storage/logs legacy layout。

交付记录：

- runtime managed home 支持从 `.octopus/runtime-homes/...` 和 `.octopus/instances/<instance>/runtime-homes/...` lazy migration 到 organization-scoped runtime home。
- organization workspace 支持从 legacy organization layout、home-level workspaces 和 instance-level workspaces lazy migration 到 canonical `organizations/<orgId>/workspaces`。
- heartbeat run logs 改为通过 ensure 入口读取，默认迁移 `.octopus/run-logs` 到 instance `data/run-logs`。
- Step 17 instructions 测试不再写 `.octopus/test-tmp`。
