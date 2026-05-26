# Octopus Database Mapping

## 1. 文档目标

本文档记录 Step 4「Database 映射基础层」的执行结果。

目的不是复述 `docs/step-04/A-CONSTRAINTS.md` 或 `docs/step-04/SCHEMA-COMPATIBILITY.md` 的约束本身,而是把这一步在 `packages/database/` 下实际落地的目录结构、ORM 选型、字段映射决定、client/session/transaction 入口、查询层与 service 接入链以及验证方式固化为可回溯的执行记录。

后续阶段要追问「database 当前为什么是这样」,先回到本文档查依据。

## 2. 执行范围

本次落地只动以下内容：

- 新建 `packages/database/` 命名空间下 `schema/` `clients/` `queries/` `migrations/` 四层目录
- 在 `schema/` 落第一批 6 张业务表的 Python 映射:`organizations`、`issues`、`approvals`、`issue_comments`、`issue_approvals`、`activity_log`
- 在 `clients/` 落统一的 async engine / session factory / transaction 入口
- 在 `queries/` 落 organizations / issues / approvals 三资源的最小首批 query 函数
- 在 `migrations/` 仅留入口占位与 README,不集成 alembic
- 修改 `server/config.py` `server/lifespan.py` `server/services/orgs.py` `server/routes/orgs.py` 与 `server/dependencies/`,接入数据库引擎与会话依赖
- 在 `tests/contract/` 加 Step 4 数据库与 service 链路测试

不在本次执行范围内的内容：

- chats / agents / projects / goals / runs 等其它业务表(不在第一批范围)
- ownership 校验链路(归 Step 5)
- alembic 迁移工具集成(等真正部署 PG 时引入)
- 真实业务 service / read API / mutation workflow(归 Step 6/7)
- PostgreSQL 驱动 `asyncpg`(等真正部署时再加)

## 3. 执行依据

- `docs/step-04/A-CONSTRAINTS.md` 各节约束(范围、文件边界、分层硬约束、B 实现顺序)
- `docs/step-04/SCHEMA-COMPATIBILITY.md` 表字段、nullability、默认值、主外键和关键索引
- `docs/step-03/A-CONSTRAINTS.md` 共享枚举字面值(数据库默认值需要与之一致)
- `docs/DESIGN.md` 第 7.3 节 packages/database 目录职责
- `CLAUDE.md` 编码规范关于分层职责、内聚、封装、可扩展的要求
- `CLAUDE.md` 「数据库字段名保持数据库语义」的硬约束(snake_case → camelCase 映射放在 service / shared 层,不在 database 层)

## 4. 文件结构

```
packages/database/
  __init__.py
  schema/
    __init__.py             # 导出 Base / new_uuid 与所有 ORM 模型
    _base.py                # DeclarativeBase + new_uuid 工具
    organizations.py
    issues.py
    approvals.py
    issue_comments.py
    issue_approvals.py
    activity_log.py
  clients/
    __init__.py             # 导出 create_database_engine / create_session_factory / async_transaction
    base.py                 # create_database_engine(url) -> AsyncEngine
    session.py              # create_session_factory(engine) -> async_sessionmaker
    transaction.py          # async_transaction(session) 上下文管理器
  queries/
    __init__.py
    organizations.py        # list_organizations(session)
    issues.py               # list_org_issues(session, org_id)
    approvals.py            # list_org_approvals(session, org_id)
  migrations/
    __init__.py             # 占位
    README.md               # alembic 暂不引入的原因与后续引入建议
```

## 5. 关键设计决定

### 5.1 ORM 选型

继续用 `sqlalchemy[asyncio]>=2.0`(Step 1 已纳入)。

落地方式采用 SQLAlchemy 2.0 modern style：

- `DeclarativeBase` 子类作为所有 ORM 模型的基类
- `Mapped[T]` + `mapped_column(...)` 表达列类型与约束
- 非空字段用 `Mapped[T]`,可空字段用 `Mapped[T | None]`
- 列类型显式声明(`String(36)`、`Boolean`、`JSON`、`DateTime(timezone=True)`、`Text`),避免依赖隐式推断

不引入 SQLAlchemy 1.x 风格(`Column(...)` + classical mappings)或第三方 ORM。

### 5.2 ID 类型用 `String(36)`,默认值由 Python 提供

- ID 列统一 `String(36)`,存 UUID 字符串
- 默认值 `default=new_uuid`(`packages/database/schema/_base.py` 提供的 `new_uuid()` 返回 `str(uuid.uuid4())`)
- 不用 SQLAlchemy 原生 `Uuid` 类型,因为 SQLite / PostgreSQL 行为不一致;字符串方案跨数据库稳定
- 上游 Drizzle schema 也按字符串 UUID 处理,与契约对齐

### 5.3 时间列统一 `DateTime(timezone=True)` + `server_default=func.now()`

- 表达 `timestamptz`,与上游 PG schema 对齐
- 默认值放数据库侧,避免 Python 客户端时区漂移
- `updated_at` 额外加 `onupdate=func.now()` 让 ORM update 触发数据库时间戳刷新

### 5.4 JSON 列用 SQLAlchemy `JSON` 类型

- `organizations.workspace_config`、`approvals.payload`、`activity_log.details` 等
- `JSON` 类型在 SQLite / PG 都能用,差异由 SQLAlchemy 透传
- `approvals.payload` 非空,默认值 `default=dict` 给 Python 端兜底空对象

### 5.5 外键约束只覆盖第一批表

A-CONSTRAINTS 第一批只映射 6 张表,但 SCHEMA-COMPATIBILITY 列的外键涉及更多表(`agents`、`projects`、`goals`、`heartbeat_runs` 等)。

处理方式：

- FK 目标表在本批的:加 `ForeignKey(...)` 约束(`organizations`、`issues`、`approvals` 之间)
- FK 目标表不在本批的:列保留 `String(36)`,**不**加 FK 约束(否则 `Base.metadata.create_all` 在测试 in-memory DB 时会因找不到目标表而失败)
- 后续 step 把对应业务表纳入 schema 范围时,再补 FK 约束

例如:

- `issues.org_id` 有 FK 指向 `organizations.id`
- `issues.parent_id` 有 FK 指向 `issues.id`(自引用)
- `issues.assignee_agent_id`、`issues.checkout_run_id` 等只是 `String(36)`,等 `agents`/`heartbeat_runs` 表落地再补 FK

### 5.6 索引按 SCHEMA-COMPATIBILITY 关键约束清单落

| 表 | 索引 |
|---|---|
| `organizations` | `organizations_url_key_idx`, `organizations_issue_prefix_idx` |
| `issues` | `issues_company_status_idx`, `issues_company_status_board_order_idx`, `issues_identifier_idx` (unique) |
| `approvals` | `approvals_company_status_type_idx` |
| `issue_approvals` | 复合主键 `issue_approvals_pk = (issue_id, approval_id)` |

Step 4 第一版只按 A 当时盘点的索引清单落地。后续在 `docs/step-04/SCHEMA-UPSTREAM-ALIGN.md` 一次性把全部 6 张表的 index / unique / FK 级联 / 列类型与 upstream Drizzle 对照补齐,包括之前延后的 `issues_open_automation_execution_uq` 部分唯一索引(用 `postgresql_where` + `sqlite_where` 表达)。

### 5.7 clients 三文件职责严格分开

按 A-CONSTRAINTS §6.2:

- `base.py` 只负责 engine 工厂,不持有任何全局 engine 单例
- `session.py` 只负责 session factory 包装,接受 engine 返回 `async_sessionmaker`
- `transaction.py` 提供 `async_transaction(session)` 上下文管理器,封装 `async with session.begin()`

不在 `clients/` 持有全局 engine,因为生命周期归 `server/lifespan.py` 管理。`packages/database/` 不应该知道 `server/` 的存在。

### 5.8 queries 层只做 SQL,不做业务

- `list_organizations(session)` 返回 `Sequence[Organization]`(ORM 模型对象)
- `list_org_issues(session, org_id)` 按 `org_id` 过滤
- `list_org_approvals(session, org_id)` 按 `org_id` 过滤
- 不返回 TypedDict、不组装 API response shape、不做权限判断、不做状态机
- snake_case → camelCase 的字段名映射归 service 层(`OrgService.list` 把 `Organization` 转成 `OrganizationSummary`)

### 5.9 service → query → client/session 演示链

`OrgService` 改造为接收 `AsyncSession` 入参:

```python
class OrgService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list(self) -> list[OrganizationSummary]:
        rows = await list_organizations(self._session)
        return [
            OrganizationSummary(
                id=row.id,
                urlKey=row.url_key,
                name=row.name,
                status=cast(OrganizationStatus, row.status),
            )
            for row in rows
        ]
```

route 通过独立 dependency 模块间接拿 service：

```python
def get_org_service(session: AsyncSession = Depends(get_session)) -> OrgService:
    return OrgService(session)
```

`get_session` 与 `get_org_service` 不定义在 route 文件里,而是放到 `server/dependencies/` 下,避免 route 直接碰数据库 session 细节。

service 不直接调 session_factory(满足 A-CONSTRAINTS 硬约束「service 不得直接创建 session」)。

### 5.10 lifespan 集中管理 engine 生命周期

`server/lifespan.py` 在 startup 创建 engine + session_factory,挂到 `app.state`;shutdown 调用 `engine.dispose()` 释放连接池。

满足 DESIGN.md §7.2.3 lifespan 职责定位,也满足 A-CONSTRAINTS「server/services 不得直接创建连接或 session」。

### 5.11 配置项

`server/config.py` 新增 `database_url` 字段，从 `OCTOPUS_DATABASE_URL` 环境变量读，默认 `sqlite+aiosqlite:///./octopus.db`。

- 开发本地无配置时自动写到 cwd 下的 `./octopus.db`(已 gitignored 的 `*.db` pattern 覆盖)
- 测试用 `sqlite+aiosqlite:///:memory:`,通过 fixture 覆盖
- 生产部署设置 `OCTOPUS_DATABASE_URL=postgresql+asyncpg://...` 切到 PG,但 Step 4 不预先装 `asyncpg`,等真正部署时再加依赖

### 5.12 migrations 暂不集成 alembic

`packages/database/migrations/` 仅保留 `__init__.py` 占位 + `README.md` 说明：

- Step 4 仅落映射,测试用 `Base.metadata.create_all` 直接建表
- 生产 PG 迁移工具链等 Step 5 或之后部署形态确定时再统一引入
- 优先候选 alembic(与 SQLAlchemy 同源)

避免提前引入而被 A 在 step-04/A-CONSTRAINTS.md 之外的范围卡。

## 6. server 接入侧改动

### 6.1 `server/config.py`

- 新增 `database_url: str` 字段
- `from_env` 读 `OCTOPUS_DATABASE_URL`,默认 `sqlite+aiosqlite:///./octopus.db`

### 6.2 `server/lifespan.py`

- startup: `create_database_engine(settings.database_url)` + `create_session_factory(engine)`,挂 `app.state.engine` / `app.state.session_factory`
- shutdown: `await engine.dispose()`

### 6.3 `server/routes/orgs.py`

- route 只保留 board access guard 与 endpoint
- `get_session(request)` 放在 `server/dependencies/database.py`
- `get_org_service(...)` 放在 `server/dependencies/orgs.py`,返回 `OrgService(session)`
- Step 2 的 `require_board_access` guard 行为完全保留,仍在 service / session 解析前判断

### 6.4 `server/services/orgs.py`

- `OrgService.__init__` 接收 `AsyncSession`
- `OrgService.list()` 调 `list_organizations(self._session)`,把 ORM 模型映射到 `OrganizationSummary` TypedDict
- 不再返回空列表,真实读取数据库内容

## 7. 测试覆盖

`tests/contract/test_step4_database.py` 共 11 个测试：

- 2 个 schema 元数据测试(metadata 含 6 张表、所有模型表名正确)
- 1 个 issues 索引范围测试
- 1 个 route 不直接定义数据库依赖的分层测试
- 1 个 session factory 测试
- 1 个 async_transaction 测试(写入 + 读取 + 默认值)
- 2 个 list_organizations 测试(空 + 已 seed)
- 1 个 list_org_issues 测试(按 org_id 过滤)
- 1 个 list_org_approvals 测试(按 org_id 过滤)
- 1 个 service → query → client 链路测试(seed organization,通过 OrgService.list 拿到 OrganizationSummary)

fixture 用 `sqlite+aiosqlite:///:memory:` engine + `Base.metadata.create_all`,每个测试独立隔离。

加上 Step 2 / Step 3 已有的 30 个测试,`tests/contract/` 现共 41 个测试全部通过。

## 8. 与后续阶段的衔接预留

| 后续阶段 | 在 database 层的接入位 |
|---|---|
| Step 5 ownership | `packages/database/schema/` 新增 ownership lease 等基础设施表;ownership 校验通过 query 层访问 ownership 表 |
| Step 6 read API | service 直接消费现有 query 函数;新增 read 需要新 query 时在对应资源文件追加,不在 server 层散写 SQL |
| Step 7 mutation workflow | service 用 `async_transaction` 包写操作,保证事务边界;新增 mutation 需要的 insert/update query 在对应资源 query 文件追加 |
| Step 8 runtime orchestration | 不直接接 database,通过 service 层间接;`heartbeat_runs` 表等运行时表落地时按本文 §5.5 规则补 FK 约束 |
| 真正部署 PG | 加 `asyncpg` 依赖到 pyproject,设置 `OCTOPUS_DATABASE_URL=postgresql+asyncpg://...`,引入 alembic 处理迁移 |

所有衔接点都不需要回头重写 schema / clients / queries 的现有内容,扩展只会：

- 在现有 schema 文件追加字段(若上游表演化)
- 在 schema/ 新建文件(若新表落入第一批之外的资源)
- 在 queries/ 现有文件追加 query 函数
- 在 queries/ 新建文件(若新资源)

## 9. 当前阶段不做的内容

- 不引入 `asyncpg` 或其它 PG 驱动(部署阶段再加)
- 不集成 alembic(本文 §5.12 已说明)
- 不映射 chat / agents / projects / goals / heartbeat_runs 等其它业务表(不在第一批范围)
- 不在 query 层做业务判断(A-CONSTRAINTS 硬约束)
- 不在 query 层组装 API response DTO(A-CONSTRAINTS 硬约束)
- 不在 service 层创建 session(A-CONSTRAINTS 硬约束)
- 不实现部分唯一索引 `issues_open_automation_execution_uq`(等 Step 6/7 用到 automation execution 流转时再补)
- 不引入读写分离、连接池调优、多租户连接拓扑(A-CONSTRAINTS §6.4 明确)

## 10. 验证方式

按 `CLAUDE.md` 默认本地验证顺序：

- `ruff check . --fix`
- `ruff format .`
- `pytest`
- `pyright`

启动 server 端到端验证：

- `uv run uvicorn server.app:app --host 127.0.0.1 --port 8000`
- `curl http://127.0.0.1:8000/api/orgs` → HTTP 503 + `{"detail":"Actor context is not configured for board-scoped org listing"}`(Step 2 board guard 行为完整保留,session 路径未被触达)

数据库层端到端验证（已通过 `tests/contract/test_step4_database.py` 覆盖）：

- in-memory SQLite engine 创建 + 6 张表 create_all 成功
- session factory 工作
- async_transaction 写入并立即读回
- service.list() 拿到的 `OrganizationSummary` 字段名为 camelCase,值与 seeded 数据一致

全仓 grep 上游项目名残留,确认本次新增的代码 / 文档 / 配置均未引入字面值。
