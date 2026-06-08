# Step 23: Database MySQL Compatibility

状态：开发中

## 背景

当前持久化层已经通过 SQLAlchemy async engine、request-scoped session 和 `packages/database/queries/` 形成统一入口。`step-23-runtime-extras` 已经收口 runtime/provider scope、默认 SQLite instance layout 和请求级 session cleanup。本步骤在该基础上只追加 MySQL 适配。

EPAI/POD 写入链路需要生产级数据库能力，不能依赖 SQLite 的单写者锁模型。为避免把数据库差异泄漏到业务 service，本步骤单独收口数据库操作接口、方言兼容和测试矩阵。

## 目标

在保持 routes/services 调用方式稳定的前提下，使持久化层能通过 `OCTOPUS_DATABASE_URL` 连接 MySQL，并用少量 database dialect helper 处理 MySQL 与 SQLite/PostgreSQL 的底层差异。

目标分层：

```text
routes
  -> services
    -> packages/database/queries 统一数据操作接口
      -> packages/database dialect/helper 处理方言差异
        -> SQLite / PostgreSQL / MySQL
```

## 任务

- 增加 MySQL async driver 依赖和连接串文档，例如 `mysql+asyncmy://...`。
- 扩展 engine factory：
  - SQLite 设置必要 pragma。
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
- 不修改默认 SQLite layout；该能力归 `step-23-runtime-extras`。
- 不重做 Step 25 activity、Step 27 cost、Step 28 governance 的业务语义。

## 验收

- SQLite 现有 contract/workflow tests 继续通过。
- MySQL migration smoke 和核心写入测试通过。
- `agents/chats/issues/skills` 写入接口在 MySQL 下复用同一 service/query API。
- 文档说明 MySQL 连接串、推荐生产路径和已知限制。

## 当前交付记录

- engine factory 已按 dialect 配置 SQLite/PostgreSQL/MySQL：SQLite 自动创建父目录并保留 pragma，PostgreSQL/MySQL 启用连接健康检查，MySQL 使用 `utf8mb4` 和连接 recycle。
- 已加入 MySQL async driver：`asyncmy`。
- 已新增 `packages/database/queries/_compat.py`，用于 query 层收口跨数据库 `RETURNING` 差异。
- 已改造当前阻塞面核心写路径：agents、chats、issues、organization skills，以及 issue counter / checkout issue。
- MySQL migration 已处理 baseline partial unique index 的直接兼容问题：MySQL 路径降级为普通非唯一索引，并在 migration README 记录等价约束待补。
- migration README 和相关历史分析文档已同步 MySQL 连接串和外部数据库限制。
- 新增 `tests/contract/test_step23_database_portability.py` 覆盖 MySQL migration 约束、SQLite 父目录创建、核心 write returning fallback。

## 剩余风险 / 后续项

- 尚未对真实 MySQL 服务执行 live migration smoke；当前验证仍以 SQLite 和 fallback 单元路径为主。
- `packages/database/queries/` 中仍有 workspace、runtime provider、resources、goals、heartbeat、approvals 等非本轮阻塞面的 `.returning(...)` 调用，若要宣称完整 MySQL 支持，需要继续迁到 dialect helper。
- MySQL 下 `issues_open_automation_execution_uq` 目前不是 partial unique 的语义等价实现；需要后续用 MySQL generated column、函数索引或应用层锁补齐。
