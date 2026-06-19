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
- 默认值是本地 SQLite：`sqlite+aiosqlite:///<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db`。
- 未设置 `OCTOPUS_HOME` 时，默认 home 是 `~/.octopus`；未设置 `OCTOPUS_INSTANCE_ID` 时，默认实例是 `default`。
- 外部数据库当前推荐 PostgreSQL。MySQL 尚未作为支持目标验证，现有 query 和 migration 里存在 MySQL 不兼容点，不要直接用于生产或共享数据。

本地开发不同 step 或功能分支时，推荐用不同 `OCTOPUS_INSTANCE_ID` 隔离 SQLite
数据库和文件侧数据。例如把 `dev` 作为 step-29 开发实例：

```powershell
$env:OCTOPUS_HOME = "D:\coding\octopus\.octopus"
$env:OCTOPUS_INSTANCE_ID = "dev"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run server
```

这样默认 SQLite 会写入
`D:\coding\octopus\.octopus\instances\dev\db\octopus.db`。不要让较新分支和较旧分支共用同一个 SQLite instance；较新分支写入的 `alembic_version` 可能引用当前分支不存在的 migration。

如果要从 PostgreSQL 或其他外部数据库切回默认 SQLite，清空 `OCTOPUS_DATABASE_URL` 后重新迁移并启动。

PowerShell：

```powershell
Remove-Item Env:OCTOPUS_DATABASE_URL -ErrorAction SilentlyContinue
uv run alembic upgrade head
uv run server
```

macOS / Linux：

```bash
unset OCTOPUS_DATABASE_URL
uv run alembic upgrade head
uv run server
```

PostgreSQL 连接前需要确保 Python 环境有 async driver：

```powershell
uv add asyncpg
```

PowerShell PostgreSQL 示例：

```powershell
$env:OCTOPUS_DATABASE_URL = "postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run server
```

本机 PostgreSQL 开发示例：

```sql
CREATE USER octopus WITH PASSWORD 'octopus';
CREATE DATABASE octopus OWNER octopus;
\c octopus
GRANT ALL ON SCHEMA public TO octopus;
```

```powershell
$env:OCTOPUS_HOME = ".octopus"
$env:OCTOPUS_INSTANCE_ID = "local-pg"
$env:OCTOPUS_LOCAL_TRUSTED = "1"
$env:OCTOPUS_AUTO_MIGRATE = "1"
$env:OCTOPUS_DATABASE_URL = "postgresql+asyncpg://octopus:octopus@127.0.0.1:5432/octopus"
uv run server
```

使用 PostgreSQL 后不会使用 `<OCTOPUS_HOME>/instances/<instance>/db/octopus.db`；但 `OCTOPUS_HOME` 仍负责文件侧 instance 数据，例如 `organizations/<orgId>/workspaces`、`data/storage`、`data/run-logs`、`logs` 和 runtime homes。

macOS / Linux shell PostgreSQL 示例：

```bash
export OCTOPUS_DATABASE_URL="postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME"
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
uv run server
```

macOS / Linux shell 示例：

```bash
export OCTOPUS_AUTO_MIGRATE=1
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
