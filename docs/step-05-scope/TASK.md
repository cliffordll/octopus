# Step 5: 开发 Actor、Scope 与首批读取边界

状态：已完成

## 目标

在完整认证与授权尚未实现之前，建立可供开发和测试使用的 actor 输入边界，并固定 organization-scoped 资源读取的基本规则。

## 实施范围

- 建立 board-scoped organization API 的 actor guard 语义。
- 建立 database session 与资源 service 的 dependency 注入边界。
- 接通 organization、issue 与 approval 的首批读取路径。
- 接通 issue/comment/review/approval 已实现 mutation 的统一 actor 与 organization scope 边界。
- 提供显式本地可信模式，为真实认证落地前的 API 调试注入兼容 board actor。
- 通过测试 fixture/middleware 注入与预期 actor 结构一致的调试身份数据。

## Actor 与 Scope 行为

当前代码以 `request.state.actor` 作为请求身份输入：

- organization 管理路由使用 `require_board_access()` 检查 board actor。
- 缺少 actor context 返回 `503`；存在但不具备 board 身份返回 `403`。
- `server/middleware/actor.py` 在 `OCTOPUS_LOCAL_TRUSTED=1` 时统一注入 `{"type": "board", "id": "local-board"}`。
- `server/dependencies/access.py` 统一解析 actor identity，并执行 board 与 organization access 校验。
- activity 写入从统一 actor identity 取得主体，不在 route 中写死身份。
- tests 通过 middleware 注入例如 `{"type": "board", "id": "test-board"}` 的调试 actor。

当前实现没有引入真实登录会话、token 验证或正式用户模型；这些能力归 Step 22。

## 首批读取接口

| Method | Path | 行为 |
| --- | --- | --- |
| `GET` | `/api/orgs` | board-scoped organization 列表 |
| `GET` | `/api/orgs/{orgId}` | board-scoped organization 详情 |
| `GET` | `/api/orgs/{orgId}/issues` | 指定组织下 issue 列表及过滤 |
| `GET` | `/api/issues/{id}` | issue 详情 |
| `GET` | `/api/orgs/{orgId}/approvals` | 指定组织下 approval 列表及状态过滤 |
| `GET` | `/api/approvals/{id}` | approval 详情，并应用 payload 脱敏 |

## 分层位置

| 位置 | 已实现职责 |
| --- | --- |
| `server/dependencies/database.py` | 为每次请求提供 `AsyncSession` |
| `server/middleware/actor.py` | 在显式本地可信模式中注入开发 board actor |
| `server/dependencies/access.py` | 解析 actor 并执行 board/organization scope 校验 |
| `server/dependencies/orgs.py` | 注入 `OrgService` 并解析组织详情 |
| `server/dependencies/issues.py` | 注入 `IssueService` |
| `server/dependencies/approvals.py` | 注入 `ApprovalService` |
| `packages/database/queries/*.py` | 按 `org_id` 与过滤字段查询资源 |
| `server/services/*.py` | 将数据库模型映射为 shared response |

## 重要边界

- organization 是业务资源范围；已存在的 organization 可直接承接 issue 和 approval 流程。
- seed/fixture 只为测试提供数据和 actor 来源，不改变 payload、枚举、状态或数据库关系。
- `GET /api/issues` 与误写的 `GET /api/orgs/issues` 不作为无作用域列表接口；均返回提示必须使用 `/api/orgs/{orgId}/issues`。
- Issue 与 approval 已实现的读取和 mutation 在统一 access 边界校验 organization scope。
- Step 22 只替换真实认证/授权数据来源，不再改变当前 service 使用的 actor 结构。

## 验收证据

- `tests/contract/test_step6_read_api.py` 验证首批组织、issue、approval 读取，filter 校验、缺失资源和 approval payload 脱敏行为。
- `tests/contract/test_step5_actor_scope.py` 验证本地可信 actor、跨组织拒绝、activity identity 与 malformed issue path。
- `tests/contract/test_step7_org_management.py` 与 `tests/contract/test_step9_approval_management.py` 验证 board actor guard 行为。

## Curl 验收 Demo 与当前限制

启动一个已完成 migration 的本地服务：

```powershell
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///./octopus-demo.db"
$env:OCTOPUS_AUTO_MIGRATE = "1"
$env:OCTOPUS_LOCAL_TRUSTED = "1"
uv run server
```

上述配置下，请求以本地开发 board actor `local-board` 执行，可直接创建 organization：

```powershell
$org = curl.exe -s -X POST "http://127.0.0.1:8000/api/orgs" `
  -H "Content-Type: application/json" `
  -d '{"name":"Curl Org"}' | ConvertFrom-Json
$env:ORG_ID = $org.id
```

关闭开发 actor并重启服务后，可验证需要身份上下文的接口被拒绝：

```powershell
Remove-Item Env:OCTOPUS_LOCAL_TRUSTED
curl.exe -i http://127.0.0.1:8000/api/orgs
```

未启用时预期返回 `503` 和 actor context 未配置错误。`OCTOPUS_LOCAL_TRUSTED=1` 仅用于本地调试，不表示实现了正式登录或授权来源。

## 未纳入

- 配置化的生产身份来源与完整认证/授权；真实来源在 Step 22 替换开发 actor。
- run、runtime 与后台执行中的 scope 传递，归后续运行步骤。
