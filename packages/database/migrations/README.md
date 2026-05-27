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
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///./octopus.db"
uv run server
```

macOS / Linux shell 示例：

```bash
export OCTOPUS_AUTO_MIGRATE=1
export OCTOPUS_DATABASE_URL="sqlite+aiosqlite:///./octopus.db"
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
