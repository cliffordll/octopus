# Step 23: Database Portability / Persistence Hardening

状态：开发中

## 背景

当前持久化层已经通过 SQLAlchemy async engine、request-scoped session 和 `packages/database/queries/` 形成统一入口。默认数据库是 SQLite，文档推荐 PostgreSQL；MySQL 目前不是验证目标。

EPAI/POD 写入链路需要生产级数据库能力，不能依赖 SQLite 的单写者锁模型。为避免把数据库差异泄漏到业务 service，本步骤单独收口数据库操作接口、方言兼容和测试矩阵。

另一个需要同步收口的问题是数据库位置与上游 instance layout 对齐。上游 Rudder 默认使用 embedded PostgreSQL，并把数据库 cluster 放在 `<RUDDER_HOME>/instances/<RUDDER_INSTANCE_ID>/db`。Octopus 即使继续支持 SQLite，也应保持同样的 instance-scoped 语义：SQLite 文件默认放在 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db`，而不是随进程 cwd 生成 `./octopus.db`。关键约束是 DB、workspace、runtime home、storage、run logs 和 server logs 必须属于同一个 instance root。

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
  - PostgreSQL：推荐生产路径；支持 remote PostgreSQL，也支持用户自行管理的 local PostgreSQL。
  - MySQL：兼容生产路径。
- 对齐数据库位置和 instance layout：
  - 显式设置 `OCTOPUS_HOME` 时，以显式配置为准。
  - 未设置 `OCTOPUS_HOME` 时，默认 home 仍是用户目录下的 `.octopus`，与上游默认 `~/.rudder` 语义对齐。
  - SQLite 默认 URL 不再是 `sqlite+aiosqlite:///./octopus.db`；应解析为 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db`。
  - 本地开发若显式设置 `OCTOPUS_HOME=.octopus`，SQLite 默认文件应为 `<当前目录>/.octopus/instances/default/db/octopus.db`。
  - 使用 remote PostgreSQL/MySQL 外部连接时，数据库连接不会携带文件侧 instance root；部署配置或启动器必须显式绑定 `OCTOPUS_HOME` / `OCTOPUS_INSTANCE_ID`。
  - 使用 local PostgreSQL 时，PostgreSQL data directory 建议放在 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/postgres/`，但连接仍通过 `postgresql+asyncpg://...` 指向本机 PostgreSQL 服务。
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
- 不在本步骤实现 embedded PostgreSQL 进程管理；local PostgreSQL 需要用户或启动器自行 `initdb`、启动、停止和分配端口。
- 不重做 Step 25 activity、Step 27 cost、Step 28 governance 的业务语义。

## 验收

- SQLite 现有 contract/workflow tests 继续通过。
- PostgreSQL migration smoke 和核心写入测试通过。
- MySQL migration smoke 和核心写入测试通过。
- `agents/chats/issues/skills` 写入接口在三类数据库上使用同一 service/query API。
- SQLite 默认文件位于 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db`；remote PostgreSQL/MySQL 与显式 `OCTOPUS_HOME`、`OCTOPUS_INSTANCE_ID` 的关系有明确文档和测试覆盖；local PostgreSQL 的推荐 data directory 为 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/postgres/`。
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
- migration README 已补充 remote PostgreSQL 与 local PostgreSQL 两种配置方式；local PostgreSQL 目前需要外部进程管理，Octopus 只通过 `OCTOPUS_DATABASE_URL` 连接。
- 新增 `tests/contract/test_step23_database_portability.py` 覆盖默认数据库 URL、SQLite 父目录创建、核心 write returning fallback；更新 workspace path 测试覆盖新 instance db layout。

## 剩余风险 / 后续项

- 尚未对真实 PostgreSQL/MySQL 服务执行 live migration smoke；当前验证仍以 SQLite 和 fallback 单元路径为主。
- `packages/database/queries/` 中仍有 workspace、runtime provider、resources、goals、heartbeat、approvals 等非本轮阻塞面的 `.returning(...)` 调用，若要宣称完整 MySQL 支持，需要继续迁到 dialect helper。
- MySQL 下 `issues_open_automation_execution_uq` 目前不是 partial unique 的语义等价实现；需要后续用 MySQL generated column、函数索引或应用层锁补齐。
