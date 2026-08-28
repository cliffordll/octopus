# Step 30：统一身份、角色与权限

## 1. 目标

Octopus 使用一套权限模型管理 Human 与 Agent：

- Human 通过 Session 或可信代理 Token 登录。
- Agent 通过绑定当前 Run 的短期 Token 执行任务。
- Human 与 Agent 都以 `PrincipalRef` 表示权限主体。
- 实例 Root、组织 Owner 和普通 Member 都存入统一的 `roles` 表。
- 额外能力存入统一的 `permissions` 表。
- System 是受控的内部执行上下文，不伪装成用户，也不写入普通 Role。

当前处于开发阶段，允许删除旧数据库重新迁移。本步骤不兼容旧的
`organization_memberships`、`instance_user_roles`、
`principal_permission_grants` 和隐式 `local-board` 数据。

## 2. 数据模型

本步骤新增 8 张表，名称统一使用短的复数形式：

| 表 | 作用 |
| --- | --- |
| `users` | Human 用户 |
| `credentials` | 本地密码或以后扩展的登录凭据 |
| `sessions` | Human 浏览器 Session |
| `verifications` | 邮箱验证、重置密码等一次性验证信息 |
| `external_identities` | Epaichat 等外部身份与本地 User 的绑定 |
| `roles` | 实例级和组织级角色 |
| `permissions` | 主体的显式附加权限 |
| `invites` | 组织邀请 |

`run_tokens` 保留为未来需要主动撤销单个 Token 时的扩展边界，当前不建表；
Run Token 通过签名与 Run 状态实时验证。

认证表必须由数据库保证唯一性：`users.email`、`sessions.token`、
`credentials(provider_id, account_id)` 均设置唯一约束，不能只依赖应用层先查后写。

### `roles`

核心字段：

```text
id
scope_type       instance | organization
scope_id         instance | organization_id
principal_type   user | agent
principal_id
role             root | owner | member
status           pending | active | suspended
reports_to       同组织上级 Role ID；Human 与 Agent 共用
created_at
updated_at
```

唯一约束：

```text
(scope_type, scope_id, principal_type, principal_id)
```

规则：

- `root` 只能授予 User，且只能存在于 `instance / instance` 作用域。
- `owner`、`member` 只能存在于组织作用域。
- Agent 只能拥有所属组织的 Role，不能拥有实例 Role。
- 同一主体在同一作用域只有一个当前 Role；修改角色时更新该行。
- 组织级 Role 同时作为组织成员节点；`reports_to` 表达成员之间的统一汇报关系。
- 组织 Owner 是根节点，不能设置上级；其他成员默认直属组织 Owner。
- Human 和 Agent 都可以成为上级或下属，关系变更必须拒绝跨组织、停用成员和循环引用。
- Agent 的旧 `agents.reports_to` 只保留兼容语义；统一组织架构以 Role 关系为准。

### `permissions`

核心字段：

```text
id
scope_type
scope_id
principal_type
principal_id
permission_key
constraints       可选 JSON 限制条件
granted_by_user_id
created_at
updated_at
```

唯一约束：

```text
(scope_type, scope_id, principal_type, principal_id, permission_key)
```

Role 提供稳定的权限基线，Permission 只表达额外能力。首版支持：

- `agents:create`
- `agents:manage`
- `skills:manage`
- `users:invite`
- `users:manage_permissions`
- `tasks:assign`
- `approvals:decide`
- `organizations:manage`
- `documents:manage`
- `runtime:manage`
- `costs:manage`
- `projects:manage`
- `goals:manage`
- `workspaces:manage`

`constraints` 是后续细粒度授权的扩展点。首版没有对应 evaluator 时，
非空约束按拒绝处理，不能退化为无条件全局授权。

## 3. 身份模型

### `PrincipalRef`

```python
PrincipalRef(type="user", id=user_id)
PrincipalRef(type="agent", id=agent_id)
PrincipalRef(type="system", id=registered_system_id)
```

它只描述“谁在操作”，不携带可长期信任的权限快照。

### `IdentityContext`

一次请求解析得到：

```text
principal
org_id
role_id
role
permissions
permission_constraints
source
run_id
is_root
```

权限每次根据数据库当前状态解析。禁用 Role、结束 Run 或停用 Agent 后，
后续请求立即失效，不等待 Token 自然过期。

## 4. 登录与执行流程

### Human 本地登录

```text
email + password
  -> credentials 验证密码哈希
  -> sessions 创建随机 Session
  -> HttpOnly Cookie
  -> Middleware 还原 User
  -> IdentityContextResolver 读取当前 Role 和 Permission
```

Session Cookie 必须经过 Origin/CSRF 检查。新注册 User 不自动成为 Root，
也看不到其他用户的组织。User 创建组织后，自动获得该组织的 Owner Role。

### 首个 Root

全新数据库通过离线命令显式创建：

```powershell
uv run python -m cli root create `
  --name "Root" `
  --email "root@example.com"
```

命令会安全提示输入密码，并在一个事务中创建：

```text
users
+ credentials
+ roles(instance, instance, user, root)
```

如果邮箱已经注册，命令先验证该本地账户密码，再为原 User 增加 Root Role；
不会创建重复 User，也不能在不知道原密码时直接提升账户。

`OCTOPUS_LOCAL_TRUSTED=1` 只保留本地开发所需能力，不再创建匿名
`local-board`，也不绕过 Human 登录。

### Epaichat 代理登录

```text
Epaichat 签发代理 Token
  -> Octopus 验证签名、issuer、audience、exp、jti
  -> external_identities 查找本地 User
  -> 验证 Token 中组织与 User 的 active Role
  -> 生成 IdentityContext
```

Epaichat 不能直接指定 Octopus 最终 Role 或 Permission。

### Agent Run Token

```text
RunDispatchService 创建并启动 Run
  -> 为 Agent 签发绑定 agent/org/runtime/run 的短期 Token
  -> Adapter 注入 Token
  -> API 每次检查 Run、Agent、组织 Role
```

Run 终态、Agent 暂停或终止、Role 被禁用、组织不匹配时立即拒绝。
Agent 不能凭 Token 冒充 Human 或访问其他组织。

### System

Heartbeat、RunDispatch、RunRecovery、RunFinalization 使用注册过的
`SystemIdentityContextFactory`。System capability 在代码中显式登记，包含
调用原因和目标实体，不建立普通 Role，不通过外部请求头伪造。

## 5. 分层与模块边界

```text
HTTP Route / FastAPI Dependency
        |
        v
AccessScopeResolver[T]            抽象资源如何归属组织
  |- AgentAccessScopeResolver
  |- ApprovalAccessScopeResolver
  `- 后续 Issue/Chat/Run Resolver
        |
        v
IdentityContextResolver           解析当前主体、Role、Permission
        |
        v
AccessPolicyService               只做授权决策
        |
        +--> RoleAccessService    查询 active Role
        +--> RoleService          Role 校验和持久化
        `--> PermissionService    Permission 校验和持久化
        |
        v
database queries                  只负责 SQL
```

约束：

- Route 只声明依赖、解析输入和映射 HTTP 错误。
- 资源归属查询放进 `AccessScopeResolver[T]` 子类，避免每个路由复制代码。
- `AccessPolicyService` 不查询数据库。
- `RoleService` 不处理 HTTP。
- Query 层不包含业务授权规则。
- 继承只用于稳定的“资源到作用域”模板；Role、Permission 和 Auth 通过组合
  协作，避免深层继承和职责纠缠。

## 6. 权限决策顺序

组织请求统一按以下顺序：

1. 认证 User、Agent 或受控 System。
2. 确定目标资源所属组织。
3. 检查认证声明的组织是否允许访问目标组织。
4. Root 可访问所有组织。
5. 非 Root 必须具有目标组织的 active Role。
6. Owner 自动拥有组织级管理权限。
7. Member/Agent 的高风险操作必须具有明确 Permission。

### 路由权限矩阵

| 能力域 | 权限 |
| --- | --- |
| 实例插件、全局 LLM 配置 | Root |
| Agent 创建、配置、唤醒 | `agents:create` / `agents:manage` |
| 组织技能 | `skills:manage` |
| Runtime Provider、模型密钥、环境诊断 | `runtime:manage` |
| 任务创建、分派、执行与评审结论 | `tasks:assign` |
| 文档、交付物、附件 | `documents:manage` |
| 项目、目标 | `projects:manage` / `goals:manage` |
| Git 工作区、合并、提交、推送、清理 | `workspaces:manage` |
| 预算与预算事件处理 | `costs:manage` |
| 审批决定 | `approvals:decide` |
| 组织资料与资源 | `organizations:manage` |

普通读操作仍以 active Role 为边界；签名 Webhook 使用其自身签名验证，
不冒充 Human 或 Root。插件工具和 UI Action 在首版保持 Root-only。后续只有
在 Agent Run Token、执行工作区与服务端生成的插件 context 完成绑定后，才向
Agent 开放；客户端提交的 `cwd` 不能作为可信授权范围。
8. 业务服务仍可施加额外规则，例如 Agent 只能读取自己的 Inbox。

不存在 `board` 特判，也不能仅凭 URL 中的 `orgId` 授权。

## 7. 失败与并发规则

- 并发创建同一 Role：唯一约束只允许一行，冲突后读取胜者。
- Agent 与组织不一致：拒绝写入 Role。
- Proxy Token 有效但没有 active Role：拒绝，不自动加入组织。
- Session 有效但 Role 或 Permission 已撤销：按当前状态拒绝。
- 多个外部身份绑定到同一 User：允许。
- 同一 issuer/subject 绑定不同 User：拒绝。
- 邀请重复接受：返回既有结果，不创建重复 Role。
- 数据库写入统一使用事务协调层，SQLite 串行化写入，PostgreSQL 保留并发。

## 8. 实施批次

### 第一批：统一数据库与领域服务

- 新表和破坏性迁移。
- `RoleService`、`RoleAccessService`、`RoleManagementService`。
- `PermissionService`。
- `IdentityContextResolver`、`AccessPolicyService`。
- Root 离线初始化。
- 删除旧 Membership、Grant、实例管理员和 `local-board` 实现。

### 第二批：旧接口统一接入

- 按组织 ID 的接口使用组织权限依赖。
- Agent、Approval 等资源 ID 接口使用具体 Scope Resolver。
- 实例级诊断和全局管理接口只允许 Root。
- 删除所有 Board-only 分支。

### 第三批：UI 与外部认证

- 未登录首页跳转登录页。
- 登录、注册、退出和 Session 缓存隔离。
- 组织成员 Role/Permission 管理。
- 邀请流程。
- Epaichat Proxy Token 接口边界。

## 9. 验收标准

- 全新数据库只出现统一短名表，不出现旧权限表。
- 新注册 User 看不到历史组织数据。
- User 创建组织后成为 Owner，可管理该组织的 Agent、审批、成员和设置。
- 普通 Member 只能执行显式授权能力。
- Root 可管理实例和全部组织。
- Agent 仅能通过有效 Run Token 在所属组织执行。
- 关闭 `local_trusted` 与开启时都不存在隐式管理员。
- SQLite 与 PostgreSQL 覆盖 Role 唯一性、权限替换和跨组织拒绝测试。
- Route、Scope Resolver、Policy、Domain Service、Query 层职责清晰。

## 10. 暂不实现

- OAuth/OIDC 完整交互流程。
- LDAP、SAML 和 SCIM。
- 自定义 Role 模板。
- Permission deny 规则。
- 持久化 `run_tokens` 撤销表。
- Epaichat 实际接入；只保留 Proxy Token 和 External Identity 接口。
