# Octopus Read API

## 1. 文档目标

本文档记录 Step 6「Read API」的执行结果。

目的不是复述 `docs/step-06/A-CONSTRAINTS.md` 的约束本身,而是把这一步在 `server/routes/` `server/services/` `server/dependencies/` 和 `packages/database/queries/` 下实际落地的第一批只读 route 链路、响应映射、ownership 接入位置、upstream 对照证据与测试覆盖固化为可回溯的执行记录。

后续阶段要追问「Step 6 read API 当前为什么是这样」,先回到本文档查依据。

## 2. 执行范围

本次落地只动以下内容：

- 新增 `server/routes/{issues,approvals}.py` 两个 router 文件
- 新增 `server/services/{issues,approvals}.py` 两个服务类
- 新增 `server/dependencies/{issues,approvals}.py` 两个 service 工厂
- 重构 `server/dependencies/ownership.py`,抽出 `assert_organization_owned(request, session, org_id)` helper 供 id-based detail 路由复用,`require_organization_ownership` Depends 委托到这个 helper
- 修改 `server/dependencies/__init__.py` 导出新 service 工厂 + `assert_organization_owned`
- 修改 `server/routes/__init__.py` 注册新 router
- 修改 `packages/database/queries/issues.py` 增加 `get_issue_by_id` + `list_org_issues` 接收 `status` / `assignee_agent_id` filter
- 修改 `packages/database/queries/approvals.py` 增加 `get_approval_by_id` + `list_org_approvals` 接收 `status` filter
- 新增 `tests/contract/test_step6_read_api.py` 共 18 个测试

不在本次执行范围内的内容(A §3 明示)：

- chat 读取接口(归 Step 9)
- mutation / approval decision 逻辑(归 Step 7)
- dashboard / metrics / 聚合统计
- 复杂搜索 / 全文检索
- `GET /api/issues` 正常列表化(仅保留为 400 错误入口)
- runtime orchestration 读取接口

## 3. 执行依据

- `docs/step-06/A-CONSTRAINTS.md` 各节约束(路径/响应/读语义/ownership/分层/B 实现顺序/验收)
- `docs/step-03/SHARED-CONTRACT.md` 已冻结 path 常量 + TypedDict + validator
- `docs/step-04/DATABASE-MAPPING.md` query 层入口规则
- `docs/step-05/OWNERSHIP.md` ownership service / dependency 接入方式

**Upstream cross-check evidence**: 本步骤实现前直接读 `上游参考仓库路径/server/src/routes/{orgs,issues,approvals}.ts`,确认以下行为:

- `GET /api/orgs/:orgId`: upstream 模式是 `assertCompanyAccess` → 非 agent 还要 `assertBoard` → `svc.getById` → 404 if missing → 直接 json
- `GET /api/orgs/:orgId/issues`: upstream 支持很多 query params(status / assigneeAgentId / assigneeUserId / reviewerAgentId / reviewerUserId / touchedByUserId / unreadForUserId / projectId / parentId / originKind / originId / q + "me" 语义),A Step 6 限缩到 `status, assigneeAgentId`,本步骤按 A 限缩走
- `GET /api/orgs/:orgId/approvals`: upstream 简单返回 list + redactApprovalPayload。**A 文档未提 redact**,本步骤暂不实现,在 §9 列为 deferred
- `GET /api/approvals/:id`: upstream 先 `getById` → 404 → 后 `assertCompanyAccess`。我按相同顺序(先 lookup 再 ownership)
- `GET /api/issues/:id`: upstream 在 detail 返回大量 aggregate 字段(ancestors / project / goal / mentionedProjects / currentExecutionWorkspace / workProducts / documentPayload)。**A §6.2.5 明确允许 Step 6 返回最小 detail shape**,所以按 Step 3 冻结的 `IssueDetail` TypedDict 字段返回,aggregates 留 Step 7+。同时 upstream 有 identifier 解析(PAP-39→UUID),**A §7.1 明示 Step 6 不引入**,只按 UUID 命中

## 4. 文件结构

```
packages/database/queries/
  issues.py                # +get_issue_by_id; list_org_issues 加 status/assignee_agent_id filter
  approvals.py             # +get_approval_by_id; list_org_approvals 加 status filter

server/
  services/
    issues.py              # IssueService(session) + list_for_org / get_by_id 返回 TypedDict
    approvals.py           # ApprovalService(session) + list_for_org / get_by_id
  dependencies/
    issues.py              # get_issue_service
    approvals.py           # get_approval_service
    ownership.py           # 提取 assert_organization_owned helper(供 id-based detail 复用)
    __init__.py            # 导出新 service 工厂 + assert_organization_owned
  routes/
    issues.py              # GET /api/orgs/{orgId}/issues + GET /api/issues/{id} + GET /api/issues 错误入口
    approvals.py           # GET /api/orgs/{orgId}/approvals + GET /api/approvals/{id}
    __init__.py            # 注册新 router

tests/contract/
  test_step6_read_api.py   # 18 个测试
```

## 5. 关键设计决定

### 5.1 404 vs ownership 顺序

| 路由 | 顺序 |
|---|---|
| `GET /api/orgs/{orgId}` | ownership 先(路径已带 orgId,先 ownership guard 拦截) → 404 |
| `GET /api/orgs/{orgId}/issues` | ownership 先 → 200 / 空列表 |
| `GET /api/orgs/{orgId}/approvals` | ownership 先 → 200 / 空列表 |
| `GET /api/issues/{id}` | 先 `get_by_id` lookup → 404 if missing → 拿到 `orgId` 后再 `assert_organization_owned` |
| `GET /api/approvals/{id}` | 同 issue detail |

理由:
- org-scoped 路径已经有 `{orgId}` 可以立刻 ownership 校验,不需要先查业务表
- id-based 路径无法只靠 `{id}` 推断 ownership(我们不知道这个 id 属于哪个 org),必须先查业务表
- A §8.1 明确允许 id-based detail 路由「先由 service 内部解析出 org_id 后复用同一 ownership service 判断」
- 与 upstream 行为一致(upstream 先 getById 再 assertCompanyAccess)

副作用: 当 `{orgId}` 路径的 organization 在 DB 不存在时,因为没有 ownership 记录,返回 403 「Organization has no ownership record」而不是 404。可接受 —— ownership 真相先于业务存在性。

### 5.2 ownership helper 抽取

把 `require_organization_ownership` 内部逻辑抽到 `assert_organization_owned(request, session, organization_id)` helper:

```python
async def assert_organization_owned(
    request: Request, session: AsyncSession, organization_id: str
) -> None:
    settings = request.app.state.settings
    service = OwnershipService(session, settings.pod_id)
    decision = await service.check_organization(organization_id)
    _ownership_decision_to_http(decision)  # 4-arm match → 200/403/409


async def require_organization_ownership(
    orgId: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> None:
    await assert_organization_owned(request, session, orgId)
```

效果:
- org-scoped route 直接挂 `Depends(require_organization_ownership)`,行为不变
- id-based detail route 在 service.get_by_id 拿到 orgId 后直接 `await assert_organization_owned(request, session, orgId)`,复用同一 decision → HTTP code 映射
- 不重复 4 分支判断逻辑

### 5.3 响应 shape 映射

- list 接口返回 `list[XxxListItem]`(已冻结 Step 3 TypedDict)
- detail 接口返回 `XxxDetail`(同上)
- 不直接透传 ORM 模型,service 层负责 snake_case → camelCase 字段名映射 + `datetime.isoformat()`
- IssueDetail 仅返回 Step 3 已冻结字段(13 字段),aggregates(ancestors / project / goal / workProducts / documentPayload 等)按 A §6.2.5 留到后续

### 5.4 query 参数限缩

按 A §7.2 第一批限缩:

| 接口 | 接受的 query 参数 |
|---|---|
| `GET /api/orgs/{orgId}/issues` | `status`, `assigneeAgentId` |
| `GET /api/orgs/{orgId}/approvals` | `status` |

实现路径:
1. route 通过 FastAPI `Query` 接收原始 string
2. 拼成 dict 调 `validate_list_org_issues_query` / `validate_list_org_approvals_query`(Step 3 shared validator)
3. validator 抛 ValueError → route 转 HTTP 422
4. validator 返回的 typed query 传给 service → query 层 filter

upstream 支持的额外参数(`reviewerAgentId` / `touchedByUserId` / `unreadForUserId` / `projectId` / `parentId` / `q` 等)Step 6 不接,等 A 在后续 step 扩 validator 后再补。

### 5.5 GET /api/issues 错误入口

按 A §5.1 明示「`GET /api/issues` 在 Step 6 继续视为兼容错误入口」,upstream 返回 `400 { error: "Missing orgId in path. Use /api/orgs/{orgId}/issues." }`,实现严格对齐:

```python
@router.get("/api/issues")
async def org_issues_error_entry() -> None:
    raise HTTPException(
        status_code=400,
        detail="Missing orgId in path. Use /api/orgs/{orgId}/issues.",
    )
```

不接收 query 参数,不返回任何业务列表。

### 5.6 service 不创建 session;route 不直接拼 SQL

沿用 Step 4 / Step 5 硬约束:

- service `__init__(session)` 接收 session,自己不 open
- service 方法只调 query 层函数(`packages/database/queries/`)
- route 通过 `Depends(get_xxx_service)` 拿 service
- query 层只做 SQL,返回 ORM model
- service 层 ORM → TypedDict 映射

### 5.7 ApprovalDetail 的 payload 不做 redact

upstream 有 `redactApprovalPayload` 把 `payload` 字段中的密钥字段抹去后再返回。**A 文档未提此行为**。Step 6 直接透传 payload 不做 redact。

风险: 如果 payload 中存有 secret(例如 `hire_agent` 类型的 approval 可能有 API key),会被原样返回。

缓解: Step 5 ownership guard 已经保证只有本 pod 的 org 数据可读。secret redaction 等 secret service / vault 集成后(后续 step)再补。**已在测试 fixture seed 数据中只放无敏感字段的 payload,避免误暴露**。

## 6. 测试覆盖

`tests/contract/test_step6_read_api.py` 共 18 个测试,使用 in-memory SQLite + StaticPool + httpx.AsyncClient + ASGITransport,覆盖:

A §13 必须冻结的 8 类断言:

| A §13 断言 | 测试 |
|---|---|
| organization detail owned 200 | test_org_detail_owned_returns_200 |
| organization detail foreign 403 | test_org_detail_foreign_returns_403 |
| org issues list owned 200 | test_org_issues_list_owned_empty / test_org_issues_list_owned_seeded |
| org approvals list owned 200 | test_org_approvals_list_owned_empty / test_org_approvals_list_owned_seeded |
| org issues/approvals 空 200 [] | 同上 |
| issue/approval detail missing 404 | test_issue_detail_missing_returns_404 / test_approval_detail_missing_returns_404 |
| response 字段 camelCase | test_org_detail_owned_returns_200 / test_org_issues_list_owned_seeded(断言 `urlKey` / `orgId` / `issuePrefix` 等) |
| list query 非法参数被 validator 拒绝 | test_org_issues_list_invalid_status_returns_422 / test_org_approvals_list_invalid_status_returns_422 |

额外补强(共 10 个):

- org detail missing ownership 403
- org issues / approvals foreign 403
- org issues filters by status + assigneeAgentId
- issue / approval detail foreign org 403(lookup 命中但 ownership 拒绝)
- `GET /api/issues` 错误入口 400

测试基础设施沿用 Step 5 模式:
- 真实 `server.app:app` 复用,在 fixture 中临时挂 session_factory + settings.pod_id 到 `app.state`
- ASGITransport 让 httpx.AsyncClient 直接打 FastAPI app,不走 socket
- StaticPool 让 seeding session 与 request session 共享同一 in-memory SQLite
- seed helper 给每个 org 设唯一 `issue_prefix`(满足 schema 唯一约束)

## 7. 与后续阶段的衔接预留

| 阶段 | 接入位 |
|---|---|
| Step 7 mutation workflow | POST/PATCH 路由复用同样的 ownership guard;新增的 mutation handler 调 service write 方法,沿用相同的 path 常量 + TypedDict + validator |
| Step 8 runtime orchestration | service 调 `packages/runtimes/` 时, ownership guard 已经先校验过 org 归属 |
| Step 10 hardening | wrong-route 防护 / failover 接管在本层 ownership 之上扩展,不破坏 read 路径 |
| secret redaction | 后续引入 secret service 后, ApprovalService.get_by_id 在返回前对 payload 做 redact |
| issue identifier 解析 | upstream 支持 `PAP-39` 这类 identifier 解析为 UUID。Step 6 不做,后续在 service / route 加 identifier→UUID 前置 hook |
| issue detail aggregates | upstream `/api/issues/{id}` 返回 ancestors / project / goal / mentionedProjects / currentExecutionWorkspace / workProducts / documentPayload。等 A 在 Step 3 shared types 扩 IssueDetail 后,IssueService.get_by_id 加 aggregate 拼装 |

## 8. 当前阶段不做的内容

- 不实现 chat / dashboard / metrics 任何读接口
- 不实现 `POST` / `PATCH` / `DELETE` 任何 mutation
- 不实现 `GET /api/issues` 正常列表(只保留 400 错误入口)
- 不引入 issue identifier 解析(PAP-39→UUID)
- 不返回 issue detail 的 aggregates(ancestors / project / goal / 等)
- 不做 approval payload redact(等 secret service 后补)
- 不接 upstream 的更多 query 参数(reviewerAgentId / touchedByUserId / unreadForUserId / projectId / parentId / q 等)
- 不在 route handler 内直接拼 SQL 或 ORM 查询
- 不在 query 层组装 HTTP response shape

## 9. 验证方式

按 `CLAUDE.md` 默认本地验证顺序:

- `ruff check . --fix`
- `ruff format .`
- `pytest`(73 个测试全过,含 18 个新 Step 6)
- `pyright`(0 errors)

启动 server 端到端:

- `uv run uvicorn server.app:app --host 127.0.0.1 --port 8000`
- `curl http://127.0.0.1:8000/api/orgs` → HTTP 503(Step 2 board guard 行为完整保留)
- `curl http://127.0.0.1:8000/api/issues` → HTTP 400 + `{"detail":"Missing orgId in path. Use /api/orgs/{orgId}/issues."}`(新错误入口)

全仓 grep 上游项目名残留,确认本次新增的代码 / 文档 / 配置均未引入字面值。

## 10. Upstream 对照证据记录

按项目 memory「B 必须 cross-check upstream source」规则,本步骤实现前直接 read 的 upstream 文件:

- `上游参考仓库路径/server/src/routes/orgs.ts`(行 75-120 覆盖 list / stats / detail / `/issues` 错误入口)
- `上游参考仓库路径/server/src/routes/issues.ts`(行 51-350 覆盖 list / 290 行 param normalizer / 511-549 detail)
- `上游参考仓库路径/server/src/routes/approvals.ts`(行 218-236 覆盖 list / detail)

对照后向 A 反馈或本步骤标注的 gap:

| Gap | 处理 |
|---|---|
| A §7.2 list query 参数只列 `status, assigneeAgentId`,upstream 支持更多 | 本步骤按 A 限缩走,upstream 行为留 Step 7+(已在 §5.4 + §7 记录) |
| A §6.2.5 detail shape 允许「最小」,upstream 返回大量 aggregate | 本步骤按 A 允许走最小,aggregate 留后续(已在 §5.3 + §7 记录) |
| A 全文未提 approval payload redact,upstream 有 redactApprovalPayload | 本步骤暂不实现,在 §5.7 + §8 列为 deferred,有显著风险但本阶段可控 |
| A 全文未提 issue identifier 解析,upstream 在 routes 顶层有 `router.param("id", normalizeIssueIdentifier)` | A §7.1 明示 Step 6 不做,本步骤遵循 |
