# Database Migrations

本目录现在承载正式的 Alembic 迁移资产。

当前约定：

- schema 定义仍在 `packages/database/schema/`
- Alembic 环境在 `packages/database/migrations/env.py`
- 版本文件在 `packages/database/migrations/versions/`
- 程序内调用入口在 `packages/database/migrations/runner.py`

常用命令：

```powershell
uv run alembic upgrade head
uv run alembic current
uv run alembic revision -m "describe change"
```

数据库连接：

- `OCTOPUS_DATABASE_URL` 控制当前进程连接的数据库。
- 默认值是 instance-scoped 本地 SQLite：`sqlite+aiosqlite:///<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db`。
- PostgreSQL 支持两种部署方式：
  - remote PostgreSQL：连接已有 PostgreSQL 服务，适合生产或共享环境。
  - local PostgreSQL：在本机启动 PostgreSQL 服务，数据目录建议放在 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/postgres/`，以便和 workspace/runtime/storage/logs 同属一个 Octopus instance。
- MySQL 是兼容生产路径。
- 使用 PostgreSQL/MySQL 时，部署配置必须显式绑定 `OCTOPUS_HOME` / `OCTOPUS_INSTANCE_ID`，避免数据库和 workspace/runtime/storage/logs 分属不同 instance。

PowerShell PostgreSQL 示例：

```powershell
$env:OCTOPUS_DATABASE_URL = "postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run server
```

PowerShell 本地 PostgreSQL 示例：

```powershell
$env:OCTOPUS_HOME = ".octopus"
$env:OCTOPUS_INSTANCE_ID = "local-pg"
# 先自行 initdb/pg_ctl 或用本地 PostgreSQL 管理工具启动服务；
# 数据目录建议为 .octopus/instances/local-pg/db/postgres/
$env:OCTOPUS_DATABASE_URL = "postgresql+asyncpg://octopus:PASSWORD@127.0.0.1:5432/octopus"
uv run alembic upgrade head
uv run server
```

macOS / Linux shell PostgreSQL 示例：

```bash
export OCTOPUS_DATABASE_URL="postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME"
export OCTOPUS_AUTO_MIGRATE=1
uv run server
```

macOS / Linux 本地 PostgreSQL 示例：

```bash
export OCTOPUS_HOME="$PWD/.octopus"
export OCTOPUS_INSTANCE_ID=local-pg
# 先自行 initdb/pg_ctl 或用本地 PostgreSQL 管理工具启动服务；
# 数据目录建议为 .octopus/instances/local-pg/db/postgres/
export OCTOPUS_DATABASE_URL="postgresql+asyncpg://octopus:PASSWORD@127.0.0.1:5432/octopus"
uv run alembic upgrade head
uv run server
```

PowerShell MySQL 示例：

```powershell
$env:OCTOPUS_DATABASE_URL = "mysql+asyncmy://USER:PASSWORD@HOST:3306/DBNAME?charset=utf8mb4"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run server
```

macOS / Linux shell MySQL 示例：

```bash
export OCTOPUS_DATABASE_URL="mysql+asyncmy://USER:PASSWORD@HOST:3306/DBNAME?charset=utf8mb4"
export OCTOPUS_AUTO_MIGRATE=1
uv run server
```

生产或共享数据库建议先手动迁移，再启动服务：

```powershell
$env:OCTOPUS_DATABASE_URL = "postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME"
uv run alembic upgrade head
uv run server
```

注意：

- 先在 PostgreSQL 中创建空库，并确保连接账号拥有建表、建索引和写入权限。
- local PostgreSQL 不是 SQLite 单文件模式；它需要独立 PostgreSQL server 进程。当前 Octopus 只消费 `OCTOPUS_DATABASE_URL`，不会自动 `initdb`、分配端口或启动/停止 PostgreSQL。
- MySQL 也需要提前创建空库，字符集建议 `utf8mb4`。
- MySQL 不支持 PostgreSQL/SQLite 的 partial unique index；`issues_open_automation_execution_uq` 在 MySQL migration 中降级为普通非唯一索引，完整等价约束需要后续用 MySQL 专用 generated column 或应用层锁补强。
- 密码中如果包含 `@`、`:`、`/`、`#` 等字符，需要 URL encode 后放入连接串。
- `OCTOPUS_AUTO_MIGRATE=1` 只影响当前启动进程；生产或共享环境更推荐显式执行 `uv run alembic upgrade head`。

运行模式：

- 默认：手动执行 `alembic upgrade head`
- 可选：设置 `OCTOPUS_AUTO_MIGRATE=1` 后，由 `server/lifespan.py` 在启动时调用 runner 自动升级
- 服务启动命令为 `uv run server`；绑定地址、端口和日志等级继续通过 `OCTOPUS_HOST`、`OCTOPUS_PORT` 与 `OCTOPUS_LOG_LEVEL` 配置

`OCTOPUS_AUTO_MIGRATE` 的设置方式：

- 读取位置：`server/config.py` 从进程环境变量读取
- 生效时机：`server.app.create_app()` 加载配置后，在 FastAPI lifespan startup 阶段判断是否自动迁移
- 影响范围：只影响当前启动进程，不会写回仓库配置文件

PowerShell 示例：

```powershell
$env:OCTOPUS_AUTO_MIGRATE = "1"
$env:OCTOPUS_HOME = ".octopus"
uv run server
```

macOS / Linux shell 示例：

```bash
export OCTOPUS_AUTO_MIGRATE=1
export OCTOPUS_HOME="$PWD/.octopus"
uv run server
```

单次命令临时设置示例：

```powershell
$env:OCTOPUS_AUTO_MIGRATE = "1"; uv run server
```

如果不设置，或值不是 `1/true/yes/on`，则默认视为关闭，启动前需要手动执行：

```powershell
uv run alembic upgrade head
```

约束：

- 历史 migration 必须是冻结快照，不直接导入运行时 `Base.metadata` 生成对象
- 新 schema 变更必须同时更新 `schema/` 和新 revision
- `Base.metadata.create_all` 不再承担运行时建表职责
