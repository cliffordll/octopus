# Octopus Ownership

## 1. 文档目标

本文档记录 Step 5「Ownership 与最小内部能力」的执行结果。

目的不是复述 `docs/step-05/A-CONSTRAINTS.md` 的约束本身,而是把这一步在 `packages/database/` 和 `server/` 下实际落地的 ownership 持久化、service 决策语义、guard 链路、后台过滤入口与测试矩阵固化为可回溯的执行记录。

后续阶段要追问「ownership 当前为什么是这样」,先回到本文档查依据。

## 2. 执行范围

本次落地只动以下内容：

- 新增 `packages/database/schema/organization_ownership.py` 基础设施表映射
- 新增 `packages/database/queries/organization_ownership.py` 两个 query 入口
- 新增 `server/services/ownership.py` 含决策枚举 + 服务类（请求 guard 与后台过滤共用同一来源）
- 新增 `server/dependencies/ownership.py` FastAPI Depends 形式的 guard
- 修改 `packages/database/schema/__init__.py` 导出 `OrganizationOwnership`
- 修改 `server/config.py` 增加 `pod_id` 字段（`OCTOPUS_POD_ID` 环境变量,默认 hostname）
- 修改 `server/dependencies/__init__.py` 导出 `require_organization_ownership`
- 新增 `tests/ownership/test_step5_ownership.py` 覆盖 4 类决策 + query + 后台过滤 + HTTP guard

不在本次执行范围内的内容：

- lease 自动续约 loop（A §5.1「不要求实现完整续约 loop」）
- 完整 background framework（A §7.1 只要求过滤入口）
- 改造现有 `/api/orgs` route（A §6.1 board-scoped 非 organization 请求不属于本步）
- failover / 迁移 / wrong-route 强加固（属于 Step 10 hardening）
- 外层 header 替代 DB ownership 真相（A §5.4 明示不能做）
- 任何业务 read / mutation 链路（归 Step 6/7）

## 3. 执行依据

- `docs/step-05/A-CONSTRAINTS.md` 各节约束（ownership source、request guard、background filtering、tests、分层硬约束、B 实现顺序）
- `docs/DESIGN.md` §6.3 Organization Ownership 机制
- `docs/DESIGN.md` §6.10 ownership 校验不能只靠外部路由
- `docs/step-04/A-CONSTRAINTS.md` 分层硬约束（service 不创建 session、query 不返回 HTTP shape）
- `CLAUDE.md` 编码规范 + 分层规范

## 4. 文件结构

```
packages/database/
  schema/
    organization_ownership.py    # OrganizationOwnership 基础设施表
    __init__.py                  # 导出 OrganizationOwnership
  queries/
    organization_ownership.py    # get_ownership_by_org_id, list_ownerships_for_pod

server/
  config.py                      # 加 pod_id 字段
  services/
    ownership.py                 # OwnershipDecision enum + OwnershipService
  dependencies/
    ownership.py                 # require_organization_ownership FastAPI Depends
    __init__.py                  # 导出 require_organization_ownership

tests/ownership/
  __init__.py
  test_step5_ownership.py        # 12 个测试
```

## 5. 关键设计决定

### 5.1 Ownership 表结构

`organization_ownership` 表字段:

| 字段 | 类型 | 说明 |
|---|---|---|
| `organization_id` | `String(36)` PK + FK → organizations.id | 主键即唯一约束,天然满足 A「同一时刻一个 organization 只归一个 pod」要求 |
| `pod_id` | `String(128)` NOT NULL | pod 标识,无字符集约束(可以是 hostname、UUID、Pod ID 等) |
| `lease_version` | `Integer` NOT NULL default 0 | lease 版本号,后续续约 / 迁移使用,本步只持久化不消费 |
| `acquired_at` | `DateTime(timezone=True)` NOT NULL default now | lease 首次获取时间 |
| `last_heartbeat_at` | `DateTime(timezone=True)` NOT NULL default now | 最近续约时间 |
| `expires_at` | `DateTime(timezone=True)` NOT NULL | lease 过期时间,无 default(必须显式指定) |

不混入 `organizations` 业务表(A §5.1 硬约束「ownership 以独立基础设施表承载」)。

### 5.2 OwnershipDecision 枚举

```python
class OwnershipDecision(str, Enum):
    OWNED = "owned"
    FOREIGN = "foreign"
    MISSING = "missing"
    EXPIRED = "expired"
```

- 4 个分支与 A §6.2 拒绝语义一一对应
- `str, Enum` 同时支持类型缩窄和值比较
- 决策语义集中在 service 层,不在 query / dependency 层重复判断

### 5.3 OwnershipService 设计

```python
class OwnershipService:
    def __init__(
        self,
        session: AsyncSession,
        pod_id: str,
        now: Callable[[], datetime] = _default_now,
    ) -> None: ...

    async def check_organization(self, organization_id: str) -> OwnershipDecision:
        # 1. 取 ownership 行;没有 → MISSING
        # 2. pod_id 不匹配 → FOREIGN
        # 3. expires_at <= now → EXPIRED
        # 4. 否则 → OWNED

    async def list_owned_organization_ids(self) -> list[str]:
        # 取本 pod 所有 ownership 行,过滤 expires_at > now,返回 organization_id 列表
```

设计要点:
- `session`、`pod_id`、`now` 三项都通过构造函数注入,符合 A 硬约束「service 不得直接创建 session」
- `now` 默认值 `lambda: datetime.now(UTC)`,测试时注入 fake clock 控制时间
- 请求 guard 与后台过滤复用**同一**真相来源（A §7.1 硬约束）

### 5.4 时区处理

`DateTime(timezone=True)` 在 SQLite + aiosqlite 下可能返回 naive datetime,在 PostgreSQL 下返回 aware datetime。

通过 `_as_aware_utc(value)` 辅助函数把 naive 当作 UTC 处理后再比较,保证 SQLite 测试与 PG 生产行为一致：

```python
def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
```

### 5.5 FastAPI Guard 链路

```python
async def require_organization_ownership(
    orgId: str,                                    # 自动绑定 path 参数 {orgId}
    request: Request,                              # 取 app.state.settings
    session: AsyncSession = Depends(get_session), # 复用 Step 4 的 session dependency
) -> None:
    settings = request.app.state.settings
    service = OwnershipService(session, settings.pod_id)
    decision = await service.check_organization(orgId)
    match decision:
        case OwnershipDecision.OWNED:    return                              # 放行
        case OwnershipDecision.EXPIRED:  raise HTTPException(409, "...")    # 已过期
        case OwnershipDecision.FOREIGN:  raise HTTPException(403, "...")    # 跨 pod
        case OwnershipDecision.MISSING:  raise HTTPException(403, "...")    # 无记录
```

边界要点:
- guard 在业务 service 之前拦截（A §8 硬约束）
- 不在 route handler 里散写 ownership 判断（A §6.5）
- 不让 query 层产生 HTTP shape（A §8）
- `orgId` 与 shared api_paths 的 `{orgId}` 占位对齐（Step 3 已冻结的命名）

### 5.6 拒绝语义与状态码

按 A §6.2 拒绝语义表:

| 决策 | HTTP code | detail |
|---|---|---|
| `OWNED` | 200（继续业务）| - |
| `FOREIGN` | 403 | `Organization is owned by another pod` |
| `MISSING` | 403 | `Organization has no ownership record` |
| `EXPIRED` | 409 | `Organization ownership lease has expired` |

FOREIGN 与 MISSING 都返回 403,但 detail 文案不同,满足 A §6.2「必须能区分 wrong pod / lease expired / ownership stale」。文案可在后续阶段按实际错误码定文档需要继续微调。

### 5.7 Pod identity 配置

`server/config.py` 新增 `pod_id: str` 字段:

```python
pod_id=os.environ.get("OCTOPUS_POD_ID", socket.gethostname())
```

- 生产部署设置 `OCTOPUS_POD_ID` 显式指定（与外层系统的 pod 名一致）
- 本地启动默认用 hostname,避免开发体验阻塞
- pod_id 由 Settings 持有,经 `app.state.settings` 透传到 guard 与后台,不允许 request 参数伪造（A §6.5 硬约束）

### 5.8 后台过滤入口

`OwnershipService.list_owned_organization_ids()` 同时服务:
- 请求 guard 决策依据来源（间接,通过 check_organization）
- 后台任务的「先列 owned 再处理」过滤入口

A §7.1 硬约束「请求入口和后台任务必须使用同一 ownership 真相来源」通过共享 service 实现,不存在两套 ownership 判断代码。

后续真正落地 background framework 时,直接消费此入口即可,无需额外抽象。

## 6. 测试覆盖

`tests/ownership/test_step5_ownership.py` 共 12 个测试,完整覆盖 A §12 的 5 类必须冻结断言:

| A §12 断言 | 对应测试 | 测试形态 |
|---|---|---|
| owned organization request success | `test_guard_owned_returns_200` | HTTP guard 端到端 |
| foreign organization rejected with 403 | `test_guard_foreign_returns_403` | HTTP guard 端到端 |
| missing ownership rejected with 403 | `test_guard_missing_returns_403` | HTTP guard 端到端 |
| expired lease rejected with 409 | `test_guard_expired_returns_409` | HTTP guard 端到端 |
| background only receives owned | `test_list_owned_organization_ids_excludes_foreign_and_expired` | service 层单元 |

额外补充覆盖（提高边界稳定性）：

- 4 个 service decision 分支独立单元测试（绕过 HTTP 层，直接验证决策逻辑）
- 2 个 query 入口测试（`get_ownership_by_org_id` present/missing）
- 1 个 `list_ownerships_for_pod` query 测试（验证按 `pod_id` 过滤）

测试基础设施:
- in-memory SQLite + `StaticPool`,保证 fixture 端 seeding 与 ASGITransport 端 request 共享同一 in-memory db（无 StaticPool 时每个连接会拿到独立 :memory: 实例）
- 用 `httpx.AsyncClient` + `ASGITransport`,无需 sync TestClient,与 pytest-asyncio auto mode 自然组合
- 测试自建最小 FastAPI app + `/probe/{orgId}` 临时 route,不污染生产 server 路由（A §6.1 不要求改 board route）

## 7. server 接入侧改动

### 7.1 `server/config.py`

- 新增 `pod_id: str` 字段
- `from_env()` 读 `OCTOPUS_POD_ID`,默认 `socket.gethostname()`

### 7.2 `server/dependencies/__init__.py`

- 新增导出 `require_organization_ownership`

### 7.3 `server/dependencies/ownership.py`

- 新文件,FastAPI Depends 形式 guard
- 复用 Step 4 的 `get_session` dependency,不重新打开 session 工厂
- 通过 `request.app.state.settings.pod_id` 拿 pod identity

### 7.4 现有 `/api/orgs` route 不动

- A §6.1 明示 board-scoped 非 organization 请求不属于本步
- Step 2 的 `require_board_access` 503 guard 行为完全保留
- 启动 `uvicorn` 后 `curl /api/orgs` 仍返回 HTTP 503

## 8. 与后续阶段的衔接预留

| 后续阶段 | 在 ownership 层的接入位 |
|---|---|
| Step 6 read API | 第一批 org-scoped route（例如 `/api/orgs/{orgId}/issues`）在 dependency 列表里挂 `require_organization_ownership`,decision 由本步 service 给出 |
| Step 7 mutation workflow | mutation route 与 read route 共用同一 guard;wrong pod / expired 拒绝在 service 之前完成,事务与状态机不会触达非本 pod 数据 |
| Step 8 runtime orchestration | runtime 调用前在 server 侧已确保 ownership,runtime 适配层不感知 ownership 概念 |
| Step 10 hardening | failover 续约 loop、ownership lease 接管策略、跨 pod 迁移在本表基础上扩展;新增 query / service 方法不破坏现有 decision 语义 |
| Background tasks | 任何后台任务直接 `await OwnershipService(...).list_owned_organization_ids()` 拿 owned 列表后再进入业务扫描 |

所有衔接点都不需要回头重写本步交付的 schema / service / dependency,扩展只会:
- 在 service 增加新方法（例如续约 / 接管）
- 在 dependency 增加新 guard 变体（例如 require_organization_ownership_with_lease_check）
- 在 schema 增加索引或字段以支撑续约 loop 性能

## 9. 当前阶段不做的内容

- 不实现 lease 自动续约 loop / heartbeat 推进
- 不引入完整 background scheduler 框架
- 不实现 ownership 接管 / failover 策略
- 不改造现有 board `/api/orgs` route
- 不在 query 层写 HTTP 拒绝语义
- 不让 service 直接创建 session
- 不依赖外层代理 header 替代 DB ownership 真相
- 不引入完整 auth / actor 验证体系（沿用 Step 2 的 board guard）
- 不实现 wrong-route 强加固防御（属于 Step 10 hardening）

## 10. 验证方式

按 `CLAUDE.md` 默认本地验证顺序：

- `ruff check . --fix`
- `ruff format .`
- `pytest`
- `pyright`

启动 server 端到端验证：

- `uv run uvicorn server.app:app --host 127.0.0.1 --port 8000`
- `curl http://127.0.0.1:8000/api/orgs` → HTTP 503 + 原 detail（Step 2 board guard 行为完整保留,未触达 ownership 链路）

ownership 端到端验证（已通过 `tests/ownership/test_step5_ownership.py` 12 个测试覆盖）：

- 4 类 service decision 全部对应正确枚举值
- 2 个 query 入口返回值符合预期
- 1 个 pod 过滤 query 只返回匹配行
- 1 个后台过滤入口排除 foreign + expired
- 4 个 HTTP guard 端到端返回 200 / 403 / 403 / 409

全仓 grep 上游项目名残留,确认本次新增的代码 / 文档 / 配置均未引入字面值。
