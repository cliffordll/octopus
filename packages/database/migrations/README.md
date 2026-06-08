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
- 外部数据库推荐 PostgreSQL；当前分支同时提供 MySQL/MariaDB 兼容路径，连接串使用 `mysql+asyncmy://...`。

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

macOS / Linux shell PostgreSQL 示例：

```bash
export OCTOPUS_DATABASE_URL="postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME"
export OCTOPUS_AUTO_MIGRATE=1
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

MySQL 手动迁移示例：

```powershell
$env:OCTOPUS_DATABASE_URL = "mysql+asyncmy://USER:PASSWORD@HOST:3306/DBNAME?charset=utf8mb4"
uv run alembic upgrade head
uv run server
```

清除数据库环境变量并切回默认 SQLite：

```powershell
Remove-Item Env:OCTOPUS_DATABASE_URL -ErrorAction SilentlyContinue
uv run alembic upgrade head
```

macOS / Linux shell：

```bash
unset OCTOPUS_DATABASE_URL
uv run alembic upgrade head
```

注意：

- 先在 PostgreSQL、MySQL 或 MariaDB 中创建空库，并确保连接账号拥有建表、建索引和写入权限。
- MySQL/MariaDB 推荐使用 `utf8mb4` 字符集，并在连接串中保留 `?charset=utf8mb4`。
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
