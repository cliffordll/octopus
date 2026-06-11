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
sqlite+aiosqlite:///<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db
```

如果不设置 `OCTOPUS_HOME` 和 `OCTOPUS_INSTANCE_ID`，默认等价于：

```text
sqlite+aiosqlite:///C:/Users/<user>/.octopus/instances/default/db/octopus.db
```

### SQLite 本地开发

默认可以不设置 `OCTOPUS_DATABASE_URL`。如果需要显式指定 SQLite 文件，PowerShell：

PowerShell：

```powershell
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///C:/Users/<user>/.octopus/instances/default/db/octopus.db"
```

macOS / Linux：

```bash
export OCTOPUS_DATABASE_URL="sqlite+aiosqlite:///$HOME/.octopus/instances/default/db/octopus.db"
```

如果之前设置过 PostgreSQL 或其他外部数据库，清空 `OCTOPUS_DATABASE_URL` 后会切回默认 SQLite。

PowerShell：

```powershell
Remove-Item Env:OCTOPUS_DATABASE_URL -ErrorAction SilentlyContinue
uv run alembic upgrade head
.\.venv\Scripts\python.exe -m server
```

macOS / Linux：

```bash
unset OCTOPUS_DATABASE_URL
uv run alembic upgrade head
.venv/bin/python -m server
```

### PostgreSQL

先在 PostgreSQL 中创建空库，并确保连接账号有建表、建索引和写入权限。

本机 PostgreSQL 示例：

```sql
CREATE USER octopus WITH PASSWORD 'octopus';
CREATE DATABASE octopus OWNER octopus;
\c octopus
GRANT ALL ON SCHEMA public TO octopus;
```

PowerShell：

```powershell
$env:OCTOPUS_HOME = ".octopus"
$env:OCTOPUS_INSTANCE_ID = "local-pg"
$env:OCTOPUS_LOCAL_TRUSTED = "1"
$env:OCTOPUS_AUTO_MIGRATE = "1"
$env:OCTOPUS_DATABASE_URL = "postgresql+asyncpg://octopus:octopus@127.0.0.1:5432/octopus"
.\.venv\Scripts\python.exe -m server
```

macOS / Linux：

```bash
export OCTOPUS_HOME=".octopus"
export OCTOPUS_INSTANCE_ID="local-pg"
export OCTOPUS_LOCAL_TRUSTED=1
export OCTOPUS_AUTO_MIGRATE=1
export OCTOPUS_DATABASE_URL="postgresql+asyncpg://octopus:octopus@127.0.0.1:5432/octopus"
.venv/bin/python -m server
```

使用 PostgreSQL 后不会使用本地 SQLite 文件 `octopus.db`；但 `OCTOPUS_HOME` 仍负责文件侧 instance 数据，例如 workspace、storage、run logs、server logs 和 runtime homes。

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
.\.venv\Scripts\python.exe -m server
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
$env:OCTOPUS_STORAGE_DIR = ".octopus/instances/default/data/storage"
```

如果不设置，默认等价于：

```text
OCTOPUS_STORAGE_PROVIDER=local_disk
OCTOPUS_STORAGE_DIR=<OCTOPUS_HOME>/instances/<instance_id>/data/storage
```

本地对象路径形态：

```text
.octopus/instances/default/data/storage/<orgId>/<namespace>/<yyyy>/<mm>/<dd>/<uuid>-<filename>
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

Windows 本地开发优先使用统一 dev 脚本：

```powershell
.\scripts\dev.ps1
```

脚本会先检查 server/UI 端口是否已被其他进程占用；如果端口被占用，会打印 PID 和命令行并退出，避免误连到其他 checkout 或残留 server。正常启动后，按 `Ctrl+C` 会同时清理由脚本启动的 server 和 UI 子进程树。server/UI 输出会写入 `.octopus/dev-logs/`。

手动启动 server 时也建议直接使用 venv Python。不要优先使用 `uv run server` 或 `uv run python -m server` 做 Windows 本地长期 server 入口；前者会经过 `.venv\Scripts\server.exe` console-script shim，后者仍多一层 `uv.exe` 父进程，Ctrl+C 在某些终端里可能只停外层进程，留下内层 Python server。

最小本地启动流程：

```powershell
$env:OCTOPUS_AUTO_MIGRATE = "1"
$env:OCTOPUS_LOCAL_TRUSTED = "1"
$env:OCTOPUS_STORAGE_PROVIDER = "local_disk"
.\.venv\Scripts\python.exe -m server
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

### 手动启动 UI

前端在 `ui/` 目录运行，Vite 默认将 `/api` 代理到 `http://127.0.0.1:8000`：

```powershell
cd ui
npm run dev -- --host 127.0.0.1 --port 5175
```

访问：

```text
http://127.0.0.1:5175
```

如果 `5174` 已被上游 Rudder 或其他项目占用，不要用它验证 Octopus UI；以当前 Octopus checkout 启动出的端口为准。

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

## 8. Process runtime demo

项目内置了一个最小 process runtime demo，用来验证 Octopus server 可以启动外部进程、等待退出并收集 stdout。

先在项目根目录确认 demo 命令可执行：

```powershell
uv run --no-sync python -m packages.runtimes.process.demo
```

输出会是 JSON，包含 `message`、当前 `cwd`、时间戳和安全的 Octopus 环境变量摘录。

在 UI 创建或编辑 Agent 时：

- Runtime 选择 `process`
- Command 填 `uv`
- Args 填 `run, --no-sync, python, -m, packages.runtimes.process.demo`
- CWD 留空

CWD 留空时，process runtime 使用 server 当前工作目录。只要 server 从项目根目录启动，项目迁移到其他目录后也不需要修改 demo 配置。

该 demo 只证明 process runtime 的最小执行链路：

```text
Octopus -> process runtime -> octopus-process-demo -> stdout -> run result
```

它不是完整 AI agent 对话运行时，也不会从 stdin 读取任务 prompt。

## 9. UI 设置

左下角 `设置` 打开统一设置面板。当前主要分类：

- `供应商`：配置 `llm_providers`、`llm_models`、`llm_provider_bindings` 和 `llm_runtime_defaults` 对应的供应商、模型、运行时绑定与默认模型。
- `心跳`：按智能体查看和切换 scheduler heartbeat 状态。

心跳页面也可以直接打开：

```text
http://127.0.0.1:5175/instance/settings/heartbeats
```

`心跳` 页面控制每个智能体的：

```text
runtimeConfig.heartbeat.enabled
```

它只影响 timer heartbeat。它不是 server 全局 scheduler 总开关，也不会关闭 assignment、manual invoke、retry 或 automation 等非 timer wakeup。非 timer wakeup 由 `runtimeConfig.heartbeat.wakeOnDemand` 控制；具体语义见 `docs/guides/heartbeat-scheduler.md`。

## 10. 运行目录说明

默认运行数据不会写入仓库根目录。未显式设置 `OCTOPUS_HOME` 时，Octopus home 默认是用户目录下的 `.octopus`。

workspace、runtime home、skills 的区别见 `docs/guides/skills.md`；任务队列和 run 调度见 `docs/guides/task-queue.md`。

```text
<OCTOPUS_HOME>/instances/default/db/octopus.db
<OCTOPUS_HOME>/instances/default/data/storage
<OCTOPUS_HOME>/instances/default/data/run-logs
<OCTOPUS_HOME>/instances/default/logs
<OCTOPUS_HOME>/instances/default/organizations
```

含义：

- `<OCTOPUS_HOME>/instances/<instance_id>/db/octopus.db`：默认 SQLite 数据库文件。
- `.octopus/instances/<instance_id>/data/storage`：本地附件、任务产物和 asset 内容；可通过 `OCTOPUS_STORAGE_DIR` 覆盖。
- `.octopus/instances/<instance_id>/data/run-logs`：heartbeat/runtime run 原始执行日志；可通过 `OCTOPUS_RUN_LOG_DIR` 覆盖。
- `.octopus/instances/<instance_id>/logs`：server/app 文件日志；可通过 `OCTOPUS_LOG_DIR` 覆盖。
- `.octopus/instances/<instance_id>/organizations/<org_id>/workspaces`：组织、项目、智能体相关工作区；可通过 `OCTOPUS_HOME` 和 `OCTOPUS_INSTANCE_ID` 调整。
- `.octopus/instances/<instance_id>/organizations/<org_id>/codex-home/agents/<agent_id>`：Codex managed `CODEX_HOME`。
- `.octopus/instances/<instance_id>/organizations/<org_id>/<runtime>-home`：OpenCode/Claude 等 runtime 的 managed home。

路径规则：

- 显式设置 `OCTOPUS_HOME` 时，以 `OCTOPUS_HOME` 为准。
- `OCTOPUS_INSTANCE_ID` 是本地实例 ID，默认值为 `default`，会参与解析 `<OCTOPUS_HOME>/instances/<instance_id>` 下的文件目录。
- 未设置 `OCTOPUS_HOME` 时，Octopus home 默认是 `~/.octopus`。
- 未设置 `OCTOPUS_DATABASE_URL` 时，SQLite 数据库默认放在 `<OCTOPUS_HOME>/instances/<instance_id>/db/octopus.db`。
- 显式设置 `OCTOPUS_DATABASE_URL` 时，数据库连接以该环境变量为准。

例如 Windows 默认路径：

```text
C:\Users\<user>\.octopus\instances\default\db\octopus.db
C:\Users\<user>\.octopus\instances\default\data\storage
```

如果希望使用指定目录，可以同时设置数据库和 home，例如：

```powershell
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///C:/Users/lianaipeng/.octopus/instances/default/db/octopus.db"
$env:OCTOPUS_HOME = "C:/Users/lianaipeng/.octopus"
```

如果要在同一台机器上隔离多个本地实例，设置 `OCTOPUS_INSTANCE_ID` 即可同时影响默认数据库和文件目录。显式设置 `OCTOPUS_DATABASE_URL` 时，数据库连接仍由该环境变量决定。

例如启动一个 `dev` 实例：

```powershell
$env:OCTOPUS_HOME = "D:\coding\octopus\.octopus"
$env:OCTOPUS_INSTANCE_ID = "dev"
$env:OCTOPUS_AUTO_MIGRATE = "1"
$env:OCTOPUS_LOCAL_TRUSTED = "1"
.\.venv\Scripts\python.exe -m server
```

此时本地文件会写入：

```text
<OCTOPUS_HOME>/instances/dev/db/octopus.db
<OCTOPUS_HOME>/instances/dev/data/storage
<OCTOPUS_HOME>/instances/dev/data/run-logs
<OCTOPUS_HOME>/instances/dev/logs
<OCTOPUS_HOME>/instances/dev/organizations
```

这些目录是本地运行产物，不应提交到 Git。

开发不同 step 或功能分支时，不要复用同一个 SQLite instance。迁移版本会写入
`alembic_version`，较新的分支升级过 `default` 后，较旧分支可能因为缺少后续
migration 文件而无法自动迁移。建议约定：

```text
default  稳定分支或主线本地实例
dev      step-29 或正在开发的下一步功能实例
step28   step-28-bug-fix 等旧分支验证实例
```

## 11. 常用验证命令

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

## 12. 清理本地数据

开发阶段如果可以丢弃本地数据，可以删除：

```powershell
Remove-Item -Recurse -Force "$env:USERPROFILE\.octopus\instances\default"
```

如果文件被占用，先停止正在运行的 server、runtime 或测试进程。

删除后重新启动：

```powershell
$env:OCTOPUS_AUTO_MIGRATE = "1"
$env:OCTOPUS_LOCAL_TRUSTED = "1"
.\.venv\Scripts\python.exe -m server
```

## 13. 常用环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `OCTOPUS_HOST` | `127.0.0.1` | server 绑定地址 |
| `OCTOPUS_PORT` | `8000` | server 端口 |
| `OCTOPUS_LOG_LEVEL` | `info` | uvicorn 日志等级 |
| `OCTOPUS_LOG_DIR` | `<OCTOPUS_HOME>/instances/<instance_id>/logs` | server/app 文件日志目录 |
| `OCTOPUS_DATABASE_URL` | `sqlite+aiosqlite:///<OCTOPUS_HOME>/instances/<instance_id>/db/octopus.db` | 数据库连接 |
| `OCTOPUS_AUTO_MIGRATE` | `false` | 启动时是否自动执行 Alembic 迁移 |
| `OCTOPUS_LOCAL_TRUSTED` | `false` | 本地调试 actor 注入 |
| `OCTOPUS_HOME` | `~/.octopus` | Octopus instance home 根目录 |
| `OCTOPUS_INSTANCE_ID` | `default` | Octopus 本地实例 ID，用于隔离默认数据库和文件侧数据目录 |
| `OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED` | `true` | 是否启动 server 全局 heartbeat scheduler；UI 设置里的 `心跳` 不修改该环境变量 |
| `OCTOPUS_HEARTBEAT_SCHEDULER_INTERVAL_SECONDS` | `5` | scheduler 周期，单位秒 |
| `OCTOPUS_STORAGE_PROVIDER` | `local_disk` | 文件存储 provider，可选 `local_disk`、`minio`、`s3` |
| `OCTOPUS_STORAGE_DIR` | `<OCTOPUS_HOME>/instances/<instance_id>/data/storage` | local disk 存储目录 |
| `OCTOPUS_RUN_LOG_DIR` | `<OCTOPUS_HOME>/instances/<instance_id>/data/run-logs` | heartbeat/runtime run 日志目录 |
| `OCTOPUS_STORAGE_ENDPOINT` | 空 | MinIO/S3-compatible endpoint |
| `OCTOPUS_STORAGE_BUCKET` | 空 | MinIO/S3 bucket |
| `OCTOPUS_STORAGE_ACCESS_KEY` | 空 | MinIO/S3 access key |
| `OCTOPUS_STORAGE_SECRET_KEY` | 空 | MinIO/S3 secret key |
| `OCTOPUS_STORAGE_REGION` | `us-east-1` | MinIO/S3 region |
| `OCTOPUS_STORAGE_FORCE_PATH_STYLE` | MinIO 默认为 `true` | 是否使用 path-style S3 地址 |

## 14. 延伸文档

按问题类型继续阅读：

- 项目定位与架构边界：`docs/DESIGN.md`
- 开发步骤总览：`docs/FEATURE.md`
- 服务启动与配置阶段说明：`docs/step-02-server/TASK.md`
- 数据库迁移：`packages/database/migrations/README.md`
- 数据库开发阶段说明：`docs/step-04-db/TASK.md`
- 本地 actor / scope：`docs/step-05-scope/TASK.md`
- 组织创建与管理：`docs/step-06-orgs/TASK.md`
- 任务队列、queued run、claim、preflight：`docs/guides/task-queue.md`
- 心跳 scheduler 与 wakeup 语义：`docs/guides/heartbeat-scheduler.md`
- 文件存储、附件、MinIO/S3：`docs/step-19-storage/TASK.md`
- 组织技能、智能体技能、`.agents/skills` 区别：`docs/guides/skills.md`
- runtime provider / model 配置：`docs/guides/runtime-provider-model-design.md`
- OpenCode provider / model 配置：`docs/guides/opencode-provider-models.md`
