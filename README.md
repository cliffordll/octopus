# Octopus

Octopus 是上游控制面 `server` 的 Python 兼容重实现。当前仓库主要提供 FastAPI server、数据库迁移、运行时编排、组织/任务/智能体/对话等服务端能力。

本文档只覆盖本地启动项目必须掌握的基础操作：依赖安装、数据库配置和迁移、服务启动、文件存储配置、常用验证与本地数据清理。

如需理解项目定位和完整开发计划，先看：

- `CLAUDE.md`：项目协作和工程约束。
- `docs/DESIGN.md`：整体架构设计。
- `docs/FEATURE.md`：整体开发计划。

## 1. 环境准备

要求：

- Python `>= 3.12`
- `uv`
- Windows PowerShell，或 macOS/Linux shell

安装依赖：

```powershell
uv sync
```

如果使用 PostgreSQL，需要安装 async driver：

```powershell
uv add asyncpg
```

默认可以直接使用 SQLite，不需要额外数据库服务。

## 2. 数据库配置

server 通过 `OCTOPUS_DATABASE_URL` 读取数据库连接。

详细迁移说明见 `packages/database/migrations/README.md`，阶段开发说明见 `docs/step-04-db/TASK.md`。

默认值：

```text
sqlite+aiosqlite:///./octopus.db
```

这表示数据库文件会创建在当前启动目录下：

```text
octopus.db
```

### SQLite 本地开发

PowerShell：

```powershell
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///./octopus.db"
```

macOS / Linux：

```bash
export OCTOPUS_DATABASE_URL="sqlite+aiosqlite:///./octopus.db"
```

### PostgreSQL

先在 PostgreSQL 中创建空库，并确保连接账号有建表、建索引和写入权限。

PowerShell：

```powershell
$env:OCTOPUS_DATABASE_URL = "postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME"
```

macOS / Linux：

```bash
export OCTOPUS_DATABASE_URL="postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME"
```

如果密码中包含 `@`、`:`、`/`、`#` 等字符，需要 URL encode 后再写入连接串。

## 3. 数据库创建与更新

本项目使用 Alembic 管理数据库 schema。服务启动默认不会隐式建表。

更多 Alembic 使用约束见 `packages/database/migrations/README.md`。

首次启动前执行：

```powershell
uv run alembic upgrade head
```

查看当前迁移版本：

```powershell
uv run alembic current
```

新建迁移文件：

```powershell
uv run alembic revision -m "describe change"
```

### 自动迁移模式

本地开发可以设置 `OCTOPUS_AUTO_MIGRATE=1`，让 server 启动时自动执行 `upgrade head`：

```powershell
$env:OCTOPUS_AUTO_MIGRATE = "1"
```

macOS / Linux：

```bash
export OCTOPUS_AUTO_MIGRATE=1
```

生产或共享数据库更建议显式执行：

```powershell
uv run alembic upgrade head
uv run server
```

## 4. 本地调试 Actor

当前真实认证系统尚未作为本地启动前置条件。调试需要启用本地可信 actor：

actor / scope 设计背景见 `docs/DESIGN.md` 和 `docs/step-05-scope/TASK.md`。

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
```

启用后，server 会注入本地 `board` actor，便于创建组织、智能体、审批和任务。

未启用且没有真实 actor 来源时，部分 API 会返回 actor context 未配置错误。

## 5. 文件存储配置

server 通过 storage provider 保存附件、任务产物和运行时输出引用。

更完整的 storage provider、MinIO 和 S3-compatible 说明见 `docs/step-19-storage/TASK.md`。

默认使用本地磁盘：

```powershell
$env:OCTOPUS_STORAGE_PROVIDER = "local_disk"
$env:OCTOPUS_STORAGE_DIR = ".octopus/storage"
```

如果不设置，默认等价于：

```text
OCTOPUS_STORAGE_PROVIDER=local_disk
OCTOPUS_STORAGE_DIR=.octopus/storage
```

本地对象路径形态：

```text
.octopus/storage/<orgId>/<namespace>/<yyyy>/<mm>/<dd>/<uuid>-<filename>
```

### MinIO / S3-Compatible

MinIO：

```powershell
$env:OCTOPUS_STORAGE_PROVIDER = "minio"
$env:OCTOPUS_STORAGE_ENDPOINT = "http://127.0.0.1:9000"
$env:OCTOPUS_STORAGE_BUCKET = "octopus"
$env:OCTOPUS_STORAGE_ACCESS_KEY = "minioadmin"
$env:OCTOPUS_STORAGE_SECRET_KEY = "minioadmin"
$env:OCTOPUS_STORAGE_REGION = "us-east-1"
$env:OCTOPUS_STORAGE_FORCE_PATH_STYLE = "1"
```

其他 S3-compatible 服务：

```powershell
$env:OCTOPUS_STORAGE_PROVIDER = "s3"
$env:OCTOPUS_STORAGE_ENDPOINT = "https://s3.example.com"
$env:OCTOPUS_STORAGE_BUCKET = "octopus"
$env:OCTOPUS_STORAGE_ACCESS_KEY = "<access-key>"
$env:OCTOPUS_STORAGE_SECRET_KEY = "<secret-key>"
$env:OCTOPUS_STORAGE_REGION = "us-east-1"
$env:OCTOPUS_STORAGE_FORCE_PATH_STYLE = "0"
```

bucket 需要提前创建；当前 server 不负责自动创建 bucket。

## 6. 启动服务

最小本地启动流程：

```powershell
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///./octopus.db"
$env:OCTOPUS_AUTO_MIGRATE = "1"
$env:OCTOPUS_LOCAL_TRUSTED = "1"
$env:OCTOPUS_STORAGE_PROVIDER = "local_disk"
$env:OCTOPUS_STORAGE_DIR = ".octopus/storage"
uv run server
```

服务默认监听：

```text
http://127.0.0.1:8000
```

可通过环境变量修改：

```powershell
$env:OCTOPUS_HOST = "127.0.0.1"
$env:OCTOPUS_PORT = "8000"
$env:OCTOPUS_LOG_LEVEL = "info"
```

健康检查：

```powershell
curl.exe http://127.0.0.1:8000/api/health
```

## 7. 创建一个组织

启动服务后，可以用以下命令创建本地调试组织：

组织管理 API 的完整说明见 `docs/step-06-orgs/TASK.md`。

```powershell
$org = curl.exe -s -X POST http://127.0.0.1:8000/api/orgs `
  -H "Content-Type: application/json" `
  -d '{"name":"Demo Org","description":"local development","budgetMonthlyCents":12000}' | ConvertFrom-Json
$env:ORG_ID = $org.id
$org
```

查询组织：

```powershell
curl.exe -s "http://127.0.0.1:8000/api/orgs/$env:ORG_ID"
```

如果这里返回 actor 相关错误，通常是没有设置：

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
```

## 8. 运行目录说明

从仓库根目录启动时，运行期文件默认写入：

workspace、runtime home、skills 的区别见 `docs/guides/skills.md`；任务队列和 run 调度见 `docs/guides/task-queue.md`。

```text
octopus.db
.octopus/storage
.octopus/run-logs
.octopus/workspaces
.octopus/runtime-homes
```

含义：

- `octopus.db`：默认 SQLite 数据库文件。
- `.octopus/storage`：本地附件、任务产物和 asset 内容。
- `.octopus/run-logs`：heartbeat/runtime run 日志。
- `.octopus/workspaces`：组织、项目、智能体相关工作区。
- `.octopus/runtime-homes`：Codex/OpenCode/Claude 等 runtime 的 managed home。

这些目录是本地运行产物，不应提交到 Git。

## 9. 常用验证命令

提交前执行四步验证：

```powershell
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv run pyright .
```

如果 Windows 上 `uv run` 因正在运行的 server 锁定 `.venv\Scripts\server.exe`，先停止 server，或使用已同步环境：

```powershell
uv run --no-sync pyright .
```

## 10. 清理本地数据

开发阶段如果可以丢弃本地数据，可以删除：

```powershell
Remove-Item -Force .\octopus.db
Remove-Item -Recurse -Force .\.octopus
```

如果文件被占用，先停止正在运行的 server、runtime 或测试进程。

删除后重新启动：

```powershell
$env:OCTOPUS_AUTO_MIGRATE = "1"
$env:OCTOPUS_LOCAL_TRUSTED = "1"
uv run server
```

## 11. 常用环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `OCTOPUS_HOST` | `127.0.0.1` | server 绑定地址 |
| `OCTOPUS_PORT` | `8000` | server 端口 |
| `OCTOPUS_LOG_LEVEL` | `info` | uvicorn 日志等级 |
| `OCTOPUS_DATABASE_URL` | `sqlite+aiosqlite:///./octopus.db` | 数据库连接 |
| `OCTOPUS_AUTO_MIGRATE` | `false` | 启动时是否自动执行 Alembic 迁移 |
| `OCTOPUS_LOCAL_TRUSTED` | `false` | 本地调试 actor 注入 |
| `OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED` | `true` | 是否启动 heartbeat scheduler |
| `OCTOPUS_HEARTBEAT_SCHEDULER_INTERVAL_SECONDS` | `5` | scheduler 周期，单位秒 |
| `OCTOPUS_STORAGE_PROVIDER` | `local_disk` | 文件存储 provider，可选 `local_disk`、`minio`、`s3` |
| `OCTOPUS_STORAGE_DIR` | `.octopus/storage` | local disk 存储目录 |
| `OCTOPUS_STORAGE_ENDPOINT` | 空 | MinIO/S3-compatible endpoint |
| `OCTOPUS_STORAGE_BUCKET` | 空 | MinIO/S3 bucket |
| `OCTOPUS_STORAGE_ACCESS_KEY` | 空 | MinIO/S3 access key |
| `OCTOPUS_STORAGE_SECRET_KEY` | 空 | MinIO/S3 secret key |
| `OCTOPUS_STORAGE_REGION` | `us-east-1` | MinIO/S3 region |
| `OCTOPUS_STORAGE_FORCE_PATH_STYLE` | MinIO 默认为 `true` | 是否使用 path-style S3 地址 |

## 12. 延伸文档

按问题类型继续阅读：

- 项目定位与架构边界：`docs/DESIGN.md`
- 开发步骤总览：`docs/FEATURE.md`
- 服务启动与配置阶段说明：`docs/step-02-server/TASK.md`
- 数据库迁移：`packages/database/migrations/README.md`
- 数据库开发阶段说明：`docs/step-04-db/TASK.md`
- 本地 actor / scope：`docs/step-05-scope/TASK.md`
- 组织创建与管理：`docs/step-06-orgs/TASK.md`
- 任务队列、queued run、claim、preflight：`docs/guides/task-queue.md`
- 文件存储、附件、MinIO/S3：`docs/step-19-storage/TASK.md`
- 组织技能、智能体技能、`.agents/skills` 区别：`docs/guides/skills.md`
- runtime provider / model 配置：`docs/guides/runtime-provider-model-design.md`
- OpenCode provider / model 配置：`docs/guides/opencode-provider-models.md`
