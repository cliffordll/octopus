# Step 1: 项目边界与仓库基线

状态：已完成

## 目标

将仓库从泛化工程残留收敛为 Python 服务端兼容重写项目，建立后续所有功能工作的工程与文档基线。

## 实施范围

- 清理与服务端能力无关的 Node workspace、桌面打包和旧工具链假设。
- 整理 Python 项目依赖、开发检查工具与忽略规则。
- 固定顶层文档职责：`CLAUDE.md` 管长期规范，`docs/DESIGN.md` 管总体设计，`docs/FEATURE.md` 管开发主线。
- 保留上游参考源码仅作为本地对照来源，不作为产品模块纳入仓库实现。

## 关键修改

| 位置 | 实施内容 |
| --- | --- |
| `pyproject.toml` | 定义 Python 3.12 项目、Hatchling 构建、运行依赖与 `ruff` / `pyright` / `pytest` 开发依赖 |
| `.gitignore` | 保留 Python、SQLite、缓存、本地配置等忽略规则，移除非本项目产物假设 |
| `CLAUDE.md` | 固定产品定位、兼容约束、分层纪律与提交要求 |
| `docs/DESIGN.md` / `docs/FEATURE.md` | 建立设计与步骤计划的承接关系 |

## 当前工程基线

运行依赖已经覆盖当前已实现服务端基础能力：

- `fastapi` 与 `uvicorn`：HTTP server 与 ASGI 启动。
- `sqlalchemy[asyncio]`、`aiosqlite`、`alembic`：数据库访问与迁移。
- `httpx`、`psutil`、`python-ulid`、`pyyaml`、`jsonschema`：后续兼容服务端能力需要的基础依赖。

开发依赖包含 `ruff`、`pyright`、`pytest` 与 `pytest-asyncio`，作为后续步骤的统一验证工具。

## 决策结果

- 本项目只实现纳入范围的 server 行为，不承载无关客户端、桌面包装或外围工具。
- 所有业务 schema、API shape、枚举和副作用必须以可核对的上游行为为依据。
- 新能力必须进入 `server/`、`packages/`、`tests/` 和相应 Step 任务记录的既有边界，不另造产品概念。

## 验收与后续使用

- `pyproject.toml` 可被 `uv` 解析并提供统一检查入口。
- 顶层文档层级已成为后续文档清理和功能判断依据。
- 本步骤不实现业务 API；服务入口和实际资源行为从 Step 2 开始。
