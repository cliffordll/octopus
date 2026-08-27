# Step 30: Auth / Principal / Membership / Access

状态：第一、二批已实现，第三批待开发

## 1. 目标

本步骤建立 Human、Agent 和 System 的认证与访问控制基础，同时保持上游数据库、API 和业务字段兼容。

- Human 继续使用上游 `user` 主体，Agent 继续使用现有 `agents` 主体。
- 不新增统一 `identities` 或 `principals` 数据库表。
- Human 与 Agent 通过同一张 `organization_memberships` 表加入组织。
- Python 使用 `PrincipalRef` 封装 User、Agent 和 System 的主体差异。
- `IdentityContextResolver`、`MemberAccessService`、`AccessPolicyService` 分别负责上下文、成员关系和权限决策。
- 业务数据库和 API 保留 user/agent 分裂字段，Service 通过 Mapper 统一读写。
- Human 支持本地账号 Session，也支持 Epaichat 接口代理传递的短期身份 Token。
- 本地 Agent 不登录，由 Run 启动时自动注入短期 Run Token。
- System 不登录、不成为默认组织成员，只通过受限且可审计的内部上下文执行。

本设计以上游参考实现的现行 Schema、API 和访问语义为兼容基线。Epaichat `ProxyTokenAuth` 是隔离在 Auth Provider 层的 Octopus 接入扩展，不改变上游业务表和权限模型。

## 2. 总体结构

### 数据层

```text
User  ─┐
       ├─ organization_memberships ─ principal_permission_grants
Agent ─┘

System ─ 受控内部上下文，不建立普通 Membership
```

### 代码层

```text
Credential / Internal Invocation
  -> AuthProviderProtocol / SystemIdentityContextFactory
  -> PrincipalRef
  -> IdentityContextResolver
  -> MemberAccessService
  -> AccessPolicyService
  -> Domain Service
```

### 兼容边界

- 数据库保留 `organization_memberships`，Python Schema 类命名为 `OrgMembership`。
- API 和数据库继续使用 `assignee_user_id`、`assignee_agent_id` 等兼容字段。
- Route 和 Domain Service 不直接拼接分裂字段，统一通过 Mapper 或 Context 处理。
- 执行语义中的 `agent_id` 继续指向真实 Agent，不替换为 Principal ID。

## 3. 核心概念

### User（Human）

Human 使用上游 `user` 表。User 保存人的基础资料，登录凭证和 Session 分别存入 Auth 相关表。

### Agent

Agent 继续使用现有 `agents` 表，保存名称、组织、Runtime、状态和执行配置。Agent 的 `id` 仍是 Run、Heartbeat、Wakeup 和 Runtime 的执行引用。

### PrincipalRef（权限主体引用）

`PrincipalRef` 是 Python 领域值对象，不是数据库表：

```python
PrincipalRef(type="user", id="user-123")
PrincipalRef(type="agent", id="agent-456")
PrincipalRef(type="system", id="run_recovery")
```

约束：

- `user` 必须解析到真实 User。
- `agent` 必须解析到真实 Agent。
- `system` 只能由 `SystemIdentityContextFactory` 创建，不能从普通请求参数构造。
- PrincipalRef 不保存角色；角色来自当前组织 Membership 或受控 System capability。

### OrgMembership（组织成员关系）

物理表保留 `organization_memberships`，Python 封装为：

```python
class OrgMembership(Base):
    __tablename__ = "organization_memberships"
```

它回答某个 User 或 Agent 是否属于某个组织，以及在该组织中的成员角色。

### IdentityContext

`IdentityContext` 是请求或后台操作期间的统一访问上下文：

```python
IdentityContext(
    principal=PrincipalRef(...),
    org_id="...",
    membership_id="...",
    membership_role="member",
    permissions=frozenset(...),
    source="session",
    run_id=None,
)
```

它不是持久化实体，也不替代 User、Agent 或 OrgMembership。

## 4. 数据模型

### 新增 9 张表

| 批次 | 表 | 用途 |
| --- | --- | --- |
| 第一批 | `user` | Human 主体 |
| 第一批 | `organization_memberships` | User/Agent 的组织成员关系 |
| 第一批 | `principal_permission_grants` | 主体的显式组织权限 |
| 第一批 | `instance_user_roles` | Human 的实例级管理角色 |
| 第二批 | `session` | Human 服务端登录 Session |
| 第二批 | `account` | 本地密码等账号凭证 |
| 第二批 | `verification` | 验证码或一次性验证材料 |
| 第二批 | `external_user_bindings` | Epaichat 外部用户与本地 User 映射 |
| 第二批 | `invites` | 组织邀请 |

当前不创建：

- `identities`、`principals`、`members`
- `auth_links`、`org_invites`
- `agent_api_keys`
- `server_exchange_redemptions`
- System 专用身份表

以后支持一次性外部凭证换取 Octopus Session 时，再增加 `server_exchange_redemptions`；接入外部 HTTP/Gateway Agent 时，再启用 `agent_api_keys`。

### `user`

核心字段遵循上游 Auth User 契约：

```text
id
name
email
email_verified
image
created_at
updated_at
```

本地开发的 `local-board` 也必须是此表中的真实 User，不能只存在于请求 Middleware。

### `organization_memberships`

```text
id
org_id
principal_type       user / agent
principal_id         User ID / Agent ID
status               pending / active / suspended
membership_role      owner / member
created_at
updated_at
```

唯一约束：

```text
(org_id, principal_type, principal_id)
```

`principal_id` 是多态引用，数据库不能用一条普通外键同时指向 User 与 Agent。`MemberService` 必须在同一事务中验证对应主体存在且组织一致。

### `principal_permission_grants`

```text
org_id
principal_type
principal_id
permission_key
scope
granted_by_user_id
```

唯一约束：

```text
(org_id, principal_type, principal_id, permission_key)
```

Membership Role 提供权限基线，Grant 提供明确的额外能力。首版不设计任意 deny/allow JSON，也不发明上游没有的自定义角色系统。

### `instance_user_roles`

保存 Human 的实例级角色，首版只实现上游已有的 `instance_admin`。Agent 和 System 不通过此表获得实例管理员权限。

### Human Auth 表

- `session`：服务端 Session、User、有效期和客户端元数据。
- `account`：本地账号和密码哈希等 Auth Provider 数据。
- `verification`：一次性验证材料及过期时间。
- `external_user_bindings`：`issuer + subject -> local_user_id` 的唯一映射。
- `invites`：组织、邀请类型、Token 哈希、默认加入配置、过期、撤销和接受时间。

原始密码、Session Cookie、邀请 Token 和代理 Token 均不能写入日志或 Activity。

## 5. 业务字段兼容与封装

### 保留兼容字段

```text
assignee_user_id        assignee_agent_id
reviewer_user_id        reviewer_agent_id
created_by_user_id      created_by_agent_id
author_user_id          author_agent_id
requested_by_user_id    requested_by_agent_id
```

Run、Heartbeat、Wakeup、Agent State、Agent Skill、Runtime 和 Cost 中表示实际执行主体的 `agent_id` 继续保持原义。

### Mapper 封装

Domain Service 不直接维护成对字段。按业务对象建立内聚 Mapper：

```text
IssueAssigneeMapper / IssueReviewerMapper / IssueCreatorMapper
CommentAuthorMapper
ApprovalRequesterMapper
DocumentCreatorMapper
```

Mapper 负责：

- 从兼容字段读取 `PrincipalRef`。
- 将 `PrincipalRef` 写回正确的 user/agent 字段。
- 写入一种主体时原子清空另一种主体字段。
- 拒绝同时设置 user 和 agent。
- 不允许 System 写入只接受 User/Agent 的业务字段。

Membership 和权限检查不放进 Mapper，而由 `MemberAccessService` 与 `AccessPolicyService` 处理，避免持久化转换与业务授权纠缠。

## 6. Auth 架构

```text
server/auth/
  AuthProviderProtocol
  BaseTokenAuth
  LocalPasswordAuth
  SessionAuth
  ProxyTokenAuth
  RunTokenAuth
```

- `AuthProviderProtocol` 统一认证结果。
- `BaseTokenAuth` 只封装 Bearer Token 提取、公共验证错误和安全日志规则。
- `LocalPasswordAuth` 负责密码验证和创建 Session。
- `SessionAuth` 负责后续 Human Cookie 请求。
- `ProxyTokenAuth` 负责 Epaichat 代理短期身份 Token。
- `RunTokenAuth` 负责本地 Agent 的 Run Token。

继承只用于稳定的公共认证模板；身份解析、Membership 和 Access 使用组合，不建立深层继承树。

### 部署模式

| 模式 | Human Auth | 用途 |
| --- | --- | --- |
| `local_trusted` | 无登录页面，使用真实 `local-board` User | 本机单人开发 |
| `authenticated + private` | Session 或可信 Proxy Token | 私有网络 |
| `authenticated + public` | Session 或可信 Proxy Token，并启用严格公开部署检查 | 公网部署 |

`ProxyTokenAuth` 是认证来源，不是新的部署模式。

## 7. Human 流程

### `local_trusted`

启动时幂等确保：

```text
local-board User
  -> instance_admin
  -> 当前组织 owner OrgMembership
```

仅允许在受控本机边界启用。`local_trusted` 不等于所有请求无条件放行。

### 本地密码与 Session

```text
用户名/邮箱 + 密码
  -> LocalPasswordAuth
  -> account 密码哈希
  -> session
  -> HttpOnly Cookie
  -> SessionAuth
```

要求：

- 密码使用成熟的自适应哈希实现，不保存明文或可逆密码。
- Session Cookie 使用 `HttpOnly`、`SameSite`，生产环境使用 `Secure`。
- Session 支持过期、登出和管理员撤销。
- Cookie 状态变更请求具备 CSRF 防护。
- 权限每次以当前 Membership 和 Grant 为准，不永久信任登录时快照。

### Epaichat 接口代理

```text
Human
  -> Epaichat Session
  -> Epaichat Octopus Proxy
  -> ProxyTokenAuth
  -> external_user_bindings
  -> local User
  -> OrgMembership
  -> AccessPolicyService
```

代理 Token 至少验证：

- 签名和允许的签名算法
- `iss`：已配置的 Epaichat issuer
- `aud`：当前 Octopus 实例
- `sub`：稳定的 Epaichat 用户 ID
- `iat` / `exp`：签发和短有效期
- `jti`：审计和撤销定位
- `org_id`：本次请求的目标组织

Octopus 使用 `(issuer, subject) -> external_user_bindings -> user` 映射身份。

安全边界：

- 不信任普通 `X-User-Id` 请求头。
- Epaichat 不能传入最终 Role 或 Permissions 并要求 Octopus 直接采用。
- 没有有效 OrgMembership 的 User 不能访问组织资源。
- Proxy Token 不写入 URL、日志、Activity 或数据库。
- 验签失败、过期、公钥获取失败或组织不一致时失败关闭，不能退回可信 Header。

当前代理调用不创建 Octopus Session。以后如果用户需要直接打开 Octopus UI，再单独实现一次性凭证交换和 `server_exchange_redemptions`。

### 邀请

- 邀请未接受前只存在 `invites`，不提前创建 Membership。
- Token 只保存哈希，支持过期、撤销和单次接受。
- 接受时在事务内验证 User/Agent、邀请状态和组织，并创建或激活 OrgMembership。
- 邀请重放不能创建重复 Membership。

## 8. Agent 执行身份

Agent 不使用 Human 登录页面。

```text
创建 Run
  -> 签发短期 Run Token
  -> Runtime 启动时注入
  -> RunTokenAuth
  -> Agent PrincipalRef
  -> OrgMembership
  -> AccessPolicyService
```

Run Token 至少绑定：

```text
agent_id
org_id
run_id
adapter_type
issued_at
expires_at
issuer
audience
token_id
```

必须拒绝跨 Run、跨组织、冒充其他 Agent、Agent 或 Membership 已停用、Run 已终态、Token 已撤销或过期等情况。

外部 Agent API Key 不在当前开发批次；等 HTTP/Gateway Runtime 接入时，再实现上游兼容的 `agent_api_keys`。

## 9. System 上下文

System 不登录，不创建普通 OrgMembership。Heartbeat、RunDispatch、RunRecovery、RunFinalization 等后台流程通过：

```python
SystemIdentityContextFactory.create(
    system_id="run_recovery",
    org_id=org_id,
    reason="recover_orphan_run",
    entity_type="run",
    entity_id=run_id,
)
```

System Context 必须包含固定 System ID、organization scope、已注册 capability、操作原因、关联实体和调用来源。

禁止实现：

```python
if principal.type == "system":
    allow_everything()
```

## 10. 权限决策

`AccessPolicyService` 按顺序判断：

1. Principal 是否有效。
2. organization scope 是否匹配。
3. User/Agent 是否存在 active OrgMembership。
4. Membership Role 是否提供基础能力。
5. Permission Grant 是否提供目标权限和 scope。
6. 资源本身是否允许该操作。
7. 高风险动作是否还需要 Approval 或实例管理员权限。

Human 与 Agent 使用同一 Membership 和 Grant 机制，但同级成员不代表默认拥有完全相同的高风险能力。差异必须由明确 Permission 或业务规则表达，不能散落为随意的 `if user` / `if agent`。

首版组织角色只保留上游的 `owner` / `member`；实例级只保留 `instance_admin`。

## 11. 模块边界

```text
packages/database/schema/
  auth.py
  organization_memberships.py
  access.py
  external_user_bindings.py

packages/database/queries/
  users.py
  organization_memberships.py
  access.py

server/auth/
  protocol.py
  base.py
  local_password.py
  session.py
  proxy_token.py
  run_token.py

server/identity/
  principal.py
  context.py
  resolver.py
  system_context.py

server/membership/
  service.py
  access.py

server/access/
  policy.py
  permissions.py
  errors.py
```

分层规则：

- Route 只解析输入、选择 Auth Provider 和注入 IdentityContext。
- Auth 只回答“凭证对应哪个 Principal”。
- Identity 只封装 Principal 和请求上下文。
- Membership 只回答“主体是否属于组织”。
- Access 只回答“主体能否执行目标动作”。
- Mapper 只处理兼容字段与 PrincipalRef 的转换。
- Query 只处理持久化，不定义业务权限。
- Runtime Adapter 只消费 Run Context 和解析后的 Secret。

## 12. 失败与并发规则

必须覆盖：

- 并发创建同一 Membership：唯一约束只允许一条，冲突后读取胜者。
- `principal_type` 与真实主体不匹配：拒绝创建 Membership。
- Agent 的 `org_id` 与 Membership 组织不一致：拒绝并记录契约错误。
- 最后一个 active owner 被撤销或降级：拒绝操作。
- 同一外部用户并发首次绑定：`(issuer, subject)` 唯一，不能创建两个 User。
- Proxy Token 有效但没有 Membership：不自动加入组织。
- Session 有效但 User、Membership 或权限已撤销：按当前状态拒绝。
- Run Token 有效但 Run 已终态：拒绝继续操作。
- System 后台重试保持幂等，不伪造成 User 或 Agent。
- 跨组织资源 ID 探测不泄漏目标是否存在。
- SQLite 使用既有写协调层；PostgreSQL 使用唯一约束、事务和必要行锁。

## 13. 开发批次

### 第一批：Principal / Membership / Access

- 新增 `user`、`organization_memberships`、`principal_permission_grants`、`instance_user_roles`。
- 实现 `PrincipalRef`、`IdentityContext` 和兼容字段 Mapper。
- 实现 `IdentityContextResolver`、`MemberService`、`MemberAccessService`、`AccessPolicyService`。
- 将 `local-board` 收口为真实 User、实例管理员和组织 Owner Membership。
- 接入关键组织访问路径，但不实现登录 UI。

验收重点：User/Agent 使用同一 Membership，跨组织访问被拒绝，现有 API 字段不变，执行型 `agent_id` 语义不变。

### 第二批：Human Auth 与成员管理

状态：已实现，待用户验收。

- 新增 `session`、`account`、`verification`、`external_user_bindings`、`invites`。
- 实现 `LocalPasswordAuth`、`SessionAuth`、`ProxyTokenAuth`。
- `ProxyTokenAuth` 通过 `OCTOPUS_PROXY_AUTH_SECRET`、`OCTOPUS_PROXY_AUTH_ISSUER`、`OCTOPUS_PROXY_AUTH_AUDIENCE` 启用；未完整配置时不接受代理 Token。
- Human Session 使用 HttpOnly、SameSite Cookie，Cookie 写请求执行同源校验；匿名请求不建立认证数据库事务。
- 实现 Epaichat 外部身份绑定、邀请和成员管理。
- 完成本地登录与成员管理 UI；代理调用不重复展示 Octopus 登录页面。

验收重点：Session 安全、代理 Token 验证、外部身份唯一映射、邀请单次接受、权限变更即时生效。

### 第三批：Agent / System / Secret

状态：待开发。

- 实现 `RunTokenAuth` 和 Runtime Token 注入。
- 将 System Context 接入 Heartbeat、RunDispatch、RunRecovery、RunFinalization。
- 实现受控 Secret 解析边界并接入 Runtime Context。
- 移除生产访问链中的开发 Actor 权限旁路。

验收重点：Token 与 Agent/Run/org 强绑定，Run 终态失效，System 无全局旁路，Secret 不泄漏。

每批流程：

```text
实现
  -> 本批专项测试
  -> 分层和兼容性审查
  -> 用户验收
  -> 用户明确要求后提交
```

默认不运行全量测试；只有用户明确要求“执行全量测试”时，才运行完整验证并闭环修复。

## 14. 本步骤明确不做

- 新增 `identities` 或统一 Identity 外键。
- 将兼容业务字段改成 `assignee_id`、`reviewer_id`。
- 自定义复杂角色编辑器。
- 默认允许 System 访问所有组织。
- 未接入 Runtime 的外部 Agent API Key。
- Microsoft、Google、GitHub、Keycloak 等 OIDC Provider。
- 为旧开发数据保留长期双写或在线迁移。

开发阶段使用全新数据库验证，不擅自删除用户现有数据库。

## 15. 总体验收标准

- User、Agent 和 System 都能解析为明确 PrincipalRef，但不新增统一主体表。
- User 与 Agent 通过同一 OrgMembership 和 Permission Grant 参与组织权限判断。
- 数据库表名、API 字段、枚举和值保持上游兼容。
- Service 不散落 user/agent 成对字段判断，统一通过 Mapper 和 Context。
- Epaichat 只能证明用户身份，不能直接授予 Octopus 角色和权限。
- Local Password/Session、Proxy Token、Run Token 三条认证链互不混淆。
- `local_trusted` 使用真实 local-board User 和 Membership，不是无限制匿名旁路。
- Run Token 不能跨 Run、跨 Agent、跨组织使用，Run 终态后失效。
- System 操作显式携带组织、capability、原因和关联实体。
- SQLite 与 PostgreSQL 均覆盖 Membership 唯一性、并发绑定和跨组织拒绝测试。
- Runtime、日志、API、Activity 和 Work Product 不泄漏密码、Session、Token 或 Secret。
- 文档、Shared Contract、Database Schema、Service、UI 和专项测试保持一致。
