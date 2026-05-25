# Octopus Shared Contract

## 1. 文档目标

本文档记录 Step 3「Shared Contract 层」的执行结果。

目的不是复述 `docs/step-03/A-CONSTRAINTS.md` 的约束本身,而是把这一步在 `packages/shared/` 下实际落地的文件结构、类型/枚举/路径/校验的命名与边界决定、`server/` 接入侧改动以及为后续阶段预留的扩展点固化为可回溯的执行记录。

后续阶段要追问「shared contract 当前为什么是这样」,先回到本文档查依据。

## 2. 执行范围

本次落地只动以下内容：

- 在 `packages/shared/src/` 下建立第一批共享契约文件:`api_paths/` `constants/` `types/` `validators/`
- 在 `pyproject.toml` 把 `packages` 纳入 `[tool.hatch.build.targets.wheel] packages`,让 `packages.shared.src.*` 成为可导入命名空间
- 把 `server/src/routes/orgs.py` 与 `server/src/services/orgs.py` 接到 shared,替换本地 path 字面量和占位 `OrgSummary`
- 在 `tests/contract/` 加 Step 3 契约测试,覆盖路径常量、枚举字面值、validator 行为

不在本次执行范围内的内容：

- `packages/database/`(归 Step 4,A 主导 schema 边界)
- ownership 校验链路(归 Step 5)
- 真实业务 API 实现(归 Step 6 read API / Step 7 mutation)
- chat / runtime 相关共享契约(`A-CONSTRAINTS.md §当前不冻结` 明确暂不进入)
- 任何字段级 schema 映射(归 Step 4 数据库映射)

## 3. 执行依据

- `docs/step-03/A-CONSTRAINTS.md` 第一批资源范围、第一批接口范围、第一批共享状态与枚举、目录约束、类型模型约束、validator 约束、依赖方向约束、验收标准
- `CLAUDE.md` 编码规范关于内聚、封装、契约稳定的要求
- `CLAUDE.md` 「文档流转规范」从 Step 3 起每步以 `A-CONSTRAINTS.md` 作为 B 直接输入
- `docs/DESIGN.md` 第 8.4 节 Shared Contract 层职责定位

## 4. 文件结构

```
packages/
  __init__.py
  shared/
    __init__.py
    src/
      __init__.py
      api_paths/
        __init__.py
        organizations.py    # 2 path 常量,覆盖 4 个路由
        issues.py           # 2 path 常量,覆盖 5 个路由
        approvals.py        # 4 path 常量,覆盖 5 个路由
      constants/
        __init__.py
        organization.py     # OrganizationStatus + 默认值
        issue.py            # IssueStatus / IssuePriority / IssueOriginKind + 默认值
        approval.py         # ApprovalType / ApprovalStatus + 默认值
      types/
        __init__.py
        organization.py     # Summary / Detail / Create / Update Payload
        issue.py            # ListItem / Detail / ListQuery / Create / Update Payload
        approval.py         # ListItem / Detail / ListQuery / Create / Resolve Payload
      validators/
        __init__.py
        organization.py     # validate_create_organization, validate_update_organization
        issue.py            # validate_list_org_issues_query, validate_create_issue, validate_update_issue
        approval.py         # validate_list_org_approvals_query, validate_create_approval, validate_resolve_approval
```

## 5. 关键设计决定

### 5.1 打包方案

`[tool.hatch.build.targets.wheel]` 配置为 `packages = ["server", "packages"]`,把 `packages/` 整个命名空间包纳入 wheel。

效果:
- `from packages.shared.src.api_paths.organizations import ORG_LIST_PATH` 直接可用
- 后续 Step 4 `packages/database/`、Step 8 `packages/runtimes/` 都落在同一构建配置下,不需要再改 hatchling

约束:
- `packages/` 是命名空间包,根 `__init__.py` 保持空
- 每一级子目录都需要 `__init__.py`,保证 import 解析稳定

### 5.2 类型表达统一用 `TypedDict`

所有响应模型、请求 payload、查询参数模型都用 `TypedDict`,理由:

- 与 Step 2 中 A 写的 `OrgSummary` 一致,不引入新风格
- 不需要新依赖(`pydantic` 等),保持 `CLAUDE.md`「依赖最小」基调
- HTTP 契约本质就是 JSON dict,TypedDict 是最直接的契约表达
- `NotRequired` + `total=False` 已经足够区分必填字段、可选字段、partial update 语义

不引入 `pydantic.BaseModel`、`dataclass` 或自定义 schema 框架。如果未来 runtime validation 需求确实需要 `pydantic`,届时由 A 在 A-CONSTRAINTS 中明确再升级。

### 5.3 枚举值用 `Literal` + tuple 双轨

```python
OrganizationStatus = Literal["active", "paused", "archived"]
ORGANIZATION_STATUSES: tuple[OrganizationStatus, ...] = (
    "active",
    "paused",
    "archived",
)
DEFAULT_ORGANIZATION_STATUS: OrganizationStatus = "active"
```

- `Literal` 别名给 TypedDict 字段做静态类型收窄
- tuple 常量给 validator 做 runtime `value in ALLOWED` 检查
- default 值显式标注为 Literal,避免任何拼写漂移

### 5.4 路径常量形式

字符串字面量,带 FastAPI 风格 `{orgId}` / `{id}` 占位符:

```python
ORG_LIST_PATH = "/api/orgs"
ORG_DETAIL_PATH = "/api/orgs/{orgId}"
```

- FastAPI 注册时 `@router.get(ORG_LIST_PATH)` 直接使用
- 测试可直接断言常量值
- 不引入函数构造路径,保持「path 常量只表达路径,不表达权限、排序、默认行为」(A-CONSTRAINTS §API Path 约束)

### 5.5 13 个路由折成 8 个 path 常量

A-CONSTRAINTS 第一批列出 13 个路由,部分路由共享 path(只是 HTTP method 不同),例如:

- `GET /api/orgs` 与 `POST /api/orgs` 共享 `ORG_LIST_PATH`
- `GET /api/orgs/{orgId}` 与 `PATCH /api/orgs/{orgId}` 共享 `ORG_DETAIL_PATH`

按 A-CONSTRAINTS「path 常量只表达路径」,共享路径只声明一个常量。HTTP method 由 route 注册时的 decorator 决定。

最终 8 个 path 常量:

| 资源 | 常量 | 路径 |
|---|---|---|
| organizations | `ORG_LIST_PATH` | `/api/orgs` |
| organizations | `ORG_DETAIL_PATH` | `/api/orgs/{orgId}` |
| issues | `ORG_ISSUE_LIST_PATH` | `/api/orgs/{orgId}/issues` |
| issues | `ISSUE_DETAIL_PATH` | `/api/issues/{id}` |
| approvals | `ORG_APPROVAL_LIST_PATH` | `/api/orgs/{orgId}/approvals` |
| approvals | `APPROVAL_DETAIL_PATH` | `/api/approvals/{id}` |
| approvals | `APPROVAL_APPROVE_PATH` | `/api/approvals/{id}/approve` |
| approvals | `APPROVAL_REJECT_PATH` | `/api/approvals/{id}/reject` |

`GET /api/issues` 在 Step 3 中继续视为兼容错误入口,不纳入第一批 shared path 常量;等 Step 6 read API 实施时再按错误入口语义单独处理。

### 5.6 Validator 返回 typed 而非 raise-only

每个 validator 签名为:

```python
def validate_create_organization(payload: Mapping[str, Any]) -> CreateOrganizationPayload: ...
```

- 校验失败抛 `ValueError`,带可读 message
- 校验成功 `cast` 原始 payload 到 TypedDict,调用方拿到的对象可直接按字段名取值并享受类型缩窄
- Validator **不**做权限、ownership、事务、状态流转判断(A-CONSTRAINTS §Validator 约束)
- 共享小型 helper 私有化在同文件内(`_check_optional_org_fields` / `_check_status_priority_origin` / `_check_nullable_ref_fields`),不抽公共 `common.py`

route 层接到 `ValueError` 后转 `HTTPException 422`,这是 Step 6 落 mutation 入口时再统一处理的事;Step 3 先要求 validator 文件、命名和契约测试落地,不强制 route 在本步骤完成 validator 接入。

### 5.7 类型字段集采取「最小可接入」原则

A-CONSTRAINTS §当前不冻结明确「全量 API 类型」不要求穷举。本次每个 TypedDict 只放支撑 Step 2 现有 server 接入和 Step 6 read API 起步所需的最少字段。例如:

- `OrganizationSummary` 4 字段(`id`/`urlKey`/`name`/`status`),与 Step 2 中 A 写的 `OrgSummary` 字段集对齐
- `OrganizationDetail` 在 Summary 基础上补 7 个常用字段
- `IssueListItem` 9 字段,`IssueDetail` 再补 12 字段
- `ApprovalListItem` 7 字段,`ApprovalDetail` 再补 5 字段

未覆盖的字段(例如 `assigneeAgentRuntimeOverrides`、`executionWorkspaceSettings` 等复合 JSON 列)等 Step 6 read API 真正消费时,由 A 在 A-CONSTRAINTS 增量冻结后再补。

### 5.8 Approval status 字面值选 `revision_requested`

A-CONSTRAINTS §第一批共享状态与枚举写明 `revision_requested`;`docs/step-07/WORKFLOW-NOTES.md` 部分位置仍写 `needs_revision`。本次按 Step 3 主输入 (`A-CONSTRAINTS`) 走 `revision_requested`,等 A 收口 `WORKFLOW-NOTES.md` 后两边一致。

## 6. server 接入侧改动

### 6.1 `server/src/routes/orgs.py`

- 删 `APIRouter(prefix="/api/orgs", ...)`,改为 `APIRouter(tags=["orgs"])` + 路由 decorator 直接传 shared path 常量
- `@router.get(ORG_LIST_PATH)` 替代原来的 `@router.get("")`
- 返回类型从 `list[dict[str, Any]]` 升为 `list[OrganizationSummary]`(经由 service 层)
- `require_board_access` guard 行为保留不变(Step 2 已锁定)

### 6.2 `server/src/services/orgs.py`

- 删除本地 `OrgSummary` TypedDict
- `from packages.shared.src.types.organization import OrganizationSummary` 替代
- `OrgService.list()` 返回类型变为 `list[OrganizationSummary]`,占位行为(返回 `[]`)不变

字段集与原 `OrgSummary` 对齐(都是 `id`/`urlKey`/`name`/`status`),响应 shape 完全等价,不影响 Step 2 的 503 guard 测试。

## 7. 测试覆盖

`tests/contract/test_step3_shared_contract.py` 共 28 个测试,覆盖:

- 8 个 API path 常量字面值
- 6 组枚举常量(organization status, issue status / priority / origin kind, approval type / status)和对应默认值
- 8 个 validator 的成功路径与典型失败路径

加上 Step 2 已有的 2 个 server skeleton 测试,`tests/contract/` 当前共 30 个测试全部通过。

## 8. 与后续阶段的衔接预留

| 后续阶段 | 在本契约层的接入位 |
|---|---|
| Step 4 database | `packages/database/src/schema/` 字段命名按 shared `Literal` 类型对齐;查询返回值与 shared TypedDict 字段名映射(snake_case → camelCase) |
| Step 5 ownership | ownership 校验中间层在 route 入口拦截,不污染 shared 契约;ownership 相关请求模型如有需要,在 shared 中独立添加,不混入业务 payload |
| Step 6 read API | route 在 path 常量上挂 read 实现;service 返回 shared TypedDict;按需求增补 Summary / Detail 字段 |
| Step 7 mutation | 当前 `validate_create_issue` / `validate_update_issue` 等只做契约层校验,route 接到 `ValueError` 转 422;权限 / 状态机 / 副作用判断由 service / workflow 层承担 |
| Step 8 runtime | `packages/runtimes/` 落地时如有共享 result / transcript 类型,新建 `packages/shared/src/types/run.py` 等独立模块,不入侵当前 3 个资源类型 |

所有衔接点都不需要回头重写 `api_paths/` / `constants/`,扩展只会:
- 在现有文件追加字段(extends TypedDict / 加 Literal 字面值)
- 在 `constants/` / `types/` / `validators/` 增加新文件(例如 chats / runs)

## 9. 当前阶段不做的内容

- 不引入 `pydantic` / `attrs` 等运行时校验框架(`CLAUDE.md` 编码规范「依赖最小」)
- 不引入 chat / runtime 共享契约(`A-CONSTRAINTS.md §当前不冻结`)
- 不引入 `packages/database/` 字段映射(归 Step 4)
- 不把 validator 与 service 业务流程混合
- 不在 route 层强制做 validator 接入(等 Step 6 mutation 入口落地时统一处理)
- 不把 `GET /api/issues` 当成第一批正常列表 path 常量
- 不补 step-03/A-CONSTRAINTS.md 之外的 path / 枚举 / 类型

## 10. 验证方式

- `uv sync --frozen` 解析通过,无新依赖增加
- `uv run python -c "from packages.shared.src.api_paths.organizations import ORG_LIST_PATH; print(ORG_LIST_PATH)"` 输出 `/api/orgs`,确认命名空间包链路通
- `uv run pytest tests/contract -q` 通过 30 个测试(28 Step 3 + 2 Step 2)
- `uv run ruff check .` / `uv run ruff format --check .` / `uv run pyright .` 全绿
- `uv run uvicorn server.src.app:app --host 127.0.0.1 --port 8000` 启动后 `curl /api/orgs` 仍返回 503 (Step 2 guard 行为未变,确认 server 接入未破坏现有契约)
- 全仓 grep 上游项目名残留,确认本次新增的代码 / 文档均未引入字面值
