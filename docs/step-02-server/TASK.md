# Step 2: Server 骨架与配置

状态：已完成

## 目标

建立可启动、可挂载路由、可承接数据库和上下文依赖的 FastAPI 服务骨架。

## 实施范围

- 创建应用工厂、模块级应用入口、配置读取和 lifespan 生命周期。
- 建立 `routes`、`services`、`dependencies` 的服务端分层位置。
- 通过兼容接口 `/api/orgs` 验证服务入口和 board actor 前置边界。

## 主要文件

| 文件 | 职责 |
| --- | --- |
| `server/__init__.py` | `uv run server` 命令入口，读取绑定配置并启动 ASGI 服务 |
| `server/app.py` | `create_app()` 与 `app` 入口，加载配置并注册 routes |
| `server/config.py` | `Settings` 与环境变量读取，包括 host、port、日志、数据库 URL 和自动迁移开关 |
| `server/lifespan.py` | 启动时执行可选迁移并初始化 engine/session factory，关闭时释放 engine |
| `server/routes/__init__.py` | 集中注册资源路由 |
| `server/routes/orgs.py` | 首个资源路由以及 board actor guard |
| `server/services/orgs.py` | organization 服务边界，随后由数据库与管理步骤扩充 |

## 配置行为

当前 `Settings.from_env()` 支持：

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `OCTOPUS_HOST` | `127.0.0.1` | server 绑定地址 |
| `OCTOPUS_PORT` | `8000` | server 端口 |
| `OCTOPUS_LOG_LEVEL` | `info` | 日志等级 |
| `OCTOPUS_DATABASE_URL` | `sqlite+aiosqlite:///./octopus.db` | 数据库连接；外部数据库当前推荐 `postgresql+asyncpg://...` |
| `OCTOPUS_AUTO_MIGRATE` | `false` | 启动前是否执行 Alembic `upgrade head` |
| `OCTOPUS_HEARTBEAT_SCHEDULER_ENABLED` | `true` | Step 13 起是否启动 heartbeat scheduler |
| `OCTOPUS_HEARTBEAT_SCHEDULER_INTERVAL_SECONDS` | `5` | Step 13 起的 scheduler 周期秒数 |

## 关键行为

- `uv run server` 通过 `server:main` 启动服务，并加载 `OCTOPUS_HOST`、`OCTOPUS_PORT` 和 `OCTOPUS_LOG_LEVEL` 配置。
- `server.app:app` 保留为底层 ASGI 应用入口。
- lifespan 管理启动资源、释放流程及后续步骤注册的后台服务生命周期；业务规则仍保留在 service 层。
- `/api/orgs` 使用已选定的资源路径，不增加独立产品接口。
- board-scoped 请求没有 actor context 时返回 `503`，非 board actor 返回 `403`；这避免在认证能力尚未接入时伪造成功访问。

## 与后续步骤的接口

- Step 3 以 `packages/shared` 替换 route/service 内部的临时契约表达。
- Step 4 将数据库 engine/session 与 queries 接入 lifespan 和 services。
- Step 22 将以真实 actor/access 来源替换当前请求上下文输入边界。

## 验收证据

- `tests/contract/test_step2_server_skeleton.py` 验证 app 已注册 `/api/orgs`，且无 actor context 时返回预期错误。
- 后续数据库和资源接口测试继续复用本步骤创建的应用与依赖分层。

## Curl 验收 Demo

PowerShell 使用 `curl.exe`，避免 `curl` 被解析为 PowerShell 别名。

启动服务：

```powershell
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///./octopus.db"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run server
```

如需连接外部 PostgreSQL，先确保已安装 async driver，再替换连接串：

```powershell
uv add asyncpg
$env:OCTOPUS_DATABASE_URL = "postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run server
```

在另一个 PowerShell 窗口调用 board-scoped 入口：

```powershell
curl.exe -i http://127.0.0.1:8000/api/orgs
```

当前可验证结果：

```text
HTTP/1.1 503 Service Unavailable
{"detail":"Actor context is not configured for board-scoped org listing"}
```

该响应证明服务已启动且组织路由已注册，同时准确反映当前尚未接入运行时开发 actor 的事实。
