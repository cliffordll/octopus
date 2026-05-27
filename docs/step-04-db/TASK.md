# Step 4: Database 与 Migration

状态：已完成

## 目标

建立 async SQLAlchemy 持久化层和正式 Alembic schema 升级入口，支撑 Step 6-9 已实现资源流程。

## 实施范围

- 创建 `packages/database/schema/`、`clients/`、`queries/` 与 `migrations/`。
- 映射首批 6 张业务表并对照上游修正字段、索引与关联约束。
- 将数据库生命周期与 FastAPI lifespan 接通。
- 建立 Alembic baseline、CLI 使用说明和可选启动自动升级。

## 首批表

| 表 | 当前用途 | 关键关联/索引 |
| --- | --- | --- |
| `organizations` | 业务作用域与组织配置 | `url_key`、`issue_prefix` 唯一索引 |
| `issues` | issue 核心数据和执行预留字段 | `org_id` 关联组织；状态/assignee/project/origin 等索引；open automation 部分唯一索引 |
| `approvals` | 审批对象与 payload/decision | `org_id` 关联组织；组织+状态+类型索引 |
| `issue_comments` | issue 讨论记录 | 关联 organization 与 issue；创建时间索引 |
| `issue_approvals` | issue 与 approval 关系 | 复合主键；删除级联到关系行 |
| `activity_log` | 资源流程副作用审计 | 关联 organization；entity/run 查询索引 |

## 文件边界

| 目录/文件 | 职责 |
| --- | --- |
| `packages/database/schema/*.py` | SQLAlchemy ORM 映射和索引/约束声明 |
| `packages/database/clients/base.py` | async engine 工厂 |
| `packages/database/clients/session.py` | async session factory |
| `packages/database/clients/transaction.py` | transaction context |
| `packages/database/queries/*.py` | 各资源读取和写入操作 |
| `packages/database/migrations/env.py` | Alembic 在线/离线环境 |
| `packages/database/migrations/versions/20260526_000001_baseline.py` | baseline migration 快照 |
| `packages/database/migrations/runner.py` | 应用内调用 `upgrade_to_head()` |

## 关键实现决定

- ORM 使用 SQLAlchemy 2.0 `DeclarativeBase` 与 `Mapped` 风格。
- ID 当前使用 `String(36)` UUID 字符串，以保持 SQLite 本地测试与目标数据库使用的一致入口。
- JSON 字段使用 `JSON().with_variant(JSONB(), "postgresql")`。
- 时间列由数据库 `server_default=func.now()` 建立，更新行为由应用 mutation 明确驱动。
- query 只返回/修改持久化对象，不负责 HTTP response 或业务状态机。
- 目标表尚未进入当前范围的外键字段保留标识值，待对应资源步骤映射表时再对照补充约束。

## Migration 行为

- 正式升级命令：`uv run alembic upgrade head`。
- `alembic.ini` 提供 CLI 配置；`packages/database/migrations/README.md` 记录使用方式。
- 默认服务启动不隐式建表；设置 `OCTOPUS_AUTO_MIGRATE=1` 时，`server/lifespan.py` 在初始化 engine 前调用 `upgrade_to_head(settings.database_url)`。
- 迁移 revision 是冻结快照，schema 变化需要新增 revision，而不是运行时从 `Base.metadata` 替代迁移历史。

## Server 接入

- `server/config.py` 从 `OCTOPUS_DATABASE_URL` 读取连接地址，默认 SQLite 本地文件。
- `server/lifespan.py` 管理 engine/session factory 和可选迁移。
- `server/dependencies/database.py` 提供 request session。
- resources service 通过 query 层访问数据库，并在 service 内转换成 shared response。

## 验收证据

- `tests/contract/test_step4_database.py` 覆盖表映射、migration baseline、session/query 链路和不存在额外业务表的约束。
- `tests/contract/test_lifespan_schema_bootstrap.py` 覆盖开启/关闭 `OCTOPUS_AUTO_MIGRATE` 的启动行为。
- `packages/database/migrations/README.md` 说明手工升级和环境变量设置方式。

## CLI 验收 Demo

本步骤验收对象是 schema migration，不以 `curl` 作为主入口。先对一个新的 SQLite 数据库执行升级：

```powershell
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///./octopus-demo.db"
uv run alembic upgrade head
uv run alembic current
```

预期 `current` 显示 baseline revision `20260526_000001 (head)`。随后可使用该数据库启动 server：

```powershell
$env:OCTOPUS_AUTO_MIGRATE = "0"
uv run uvicorn server.app:app --host 127.0.0.1 --port 8000
```

如需以启动流程验收自动迁移，可删除测试用空库后使用新的文件名执行：

```powershell
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///./octopus-auto-demo.db"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run uvicorn server.app:app --host 127.0.0.1 --port 8000
```

当前 HTTP 正向资源写入仍受运行时开发 actor 未接入影响，见 Step 5。

## 未纳入

- projects、goals、agents、heartbeat runs 和 workspace 等表将在其对应业务步骤按证据纳入。
