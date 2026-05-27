# Octopus 设计方案

## 1. 项目定位

Octopus 是上游控制面服务端的 Python 兼容替代实现。

本项目不重新定义产品，也不以 Python 技术栈为理由改变上游既有业务语义。它的目标是：

- 使用 Python 重实现上游 `server` 的核心能力
- 对齐上游现有 API、数据库业务模型、状态流转与关键副作用
- 保留服务端真实承担的执行能力，包括 run、runtime、workspace、恢复与运行记录
- 裁剪与当前服务端重实现目标无关的外围模块
- 不引入上游不存在的新业务前置条件或新产品概念

判断一项能力是否应进入 Octopus 的原则是：

`如果它属于上游 server 的对外契约或服务端业务执行语义，则应按上游实现；如果它只是外围产品、客户端能力或未经上游证实的新架构，则不纳入当前目标。`

## 2. 契约来源

兼容结论必须依据上游参考源码，而不是依据推测或重写偏好。

契约核对顺序如下：

1. 上游数据库 schema 与迁移记录
2. 上游 HTTP route、validator 和共享类型
3. 上游 service 与 workflow 行为
4. 上游测试和面向用户的说明文档

需要对齐的内容包括：

- 表名、列名、约束、索引、外键和枚举值
- API 路径、HTTP method、请求结构和响应结构
- 默认值、排序、过滤、nullability 和错误语义
- 状态流转、activity 记录、运行记录、成本和预算副作用
- issue、approval、chat、run 与 workspace 之间的关系

上游源码已经确认存在的 server 执行能力包括：

- `heartbeat_runs` 及执行事件记录
- heartbeat / wakeup 触发与队列处理
- runtime adapter 调用与结果归一化
- execution workspace 生命周期
- run 并发限制、取消、失败恢复与日志记录

这些能力是服务端兼容范围的一部分，不应被误认为外围基础设施而删除。

## 3. 范围边界

## 3.1 当前应实现的能力

Octopus 的主要实现范围是上游 `server` 对应的控制面与执行面：

- organization 管理
- agent 管理与运行配置
- project、goal 和 issue 工作流
- issue comment、review 与 approval 流程
- chat / messenger 相关服务端契约
- activity、cost、budget 与审计可见性
- heartbeat run、wakeup、runtime adapter 与 execution workspace
- 服务端配置、数据库访问、迁移、后台任务和兼容测试

各能力按 `docs/FEATURE.md` 的阶段逐步落地；Agent 实施阶段应先落地能够真实执行并可由最小消息链路触发的闭环，其中包含首个通用执行路径和 `codex_local` adapter。后续阶段扩展调度恢复、其他 runtime、完整 chat、workspace 与治理能力。尚未进入当前阶段的能力可以保留规划，但不得改写成与上游不同的模型。

## 3.2 当前不以实现为目标的内容

以下内容不属于“Python 重实现上游 server 核心能力”本身，除非后续从上游兼容范围中取得明确证据，否则不应提前设计或实现：

- 桌面端打包与桌面客户端专属能力
- 与 server 契约无关的外围工具链
- 基础设施层的服务进程托管、弹性伸缩与网络流量治理
- 上游不存在的 organization 业务前置条件
- 仅为重写方便而发明的新 HTTP 接口、业务表或状态模型

## 3.3 裁剪与兼容的关系

裁剪模块不等于裁剪上游 server 的真实语义。

- 可以不迁移当前不需要的外围模块
- 可以按阶段延后尚未实施的 server 子系统
- 不可以因为实现复杂而改变已纳入范围的 API 或业务行为
- 不可以将上游存在的 run/workspace 行为替换成另一套简化产品模型

## 4. 设计原则

## 4.1 兼容优先

允许变化：

- 语言从 TypeScript 切换为 Python
- Web 框架、ORM、模块组织和内部实现细节
- Python 内部类型、工具函数和测试实现方式

不允许无证据变化：

- 上游业务表结构
- API 路径、payload 与返回语义
- 枚举字符串和状态值
- 关键事务边界与副作用时机
- 已确认属于 server 的业务执行能力

## 4.2 Organization 是业务作用域

所有组织内对象与流程都必须保持明确的 `org_id` 关系：

- 查询不能跨 organization 泄漏数据
- mutation 不能修改不属于目标 organization 的对象
- 后台动作和 run 必须携带其业务作用域
- activity、cost、budget 与 workspace 记录必须能追溯到对应 organization

Organization scope 是数据和业务隔离边界，不是额外执行分配机制。

## 4.3 数据库是持久化真相

数据库承载上游业务状态和需要恢复的执行状态。内存可以承载短生命周期对象，例如正在运行的子进程句柄或缓存，但不得替代：

- 业务对象状态
- run 状态与结果
- workspace 关联信息
- 可恢复的队列、事件、成本或审计记录

## 4.4 只实现有来源的概念

新增模块、表、API 或流程前，必须回答：

1. 上游是否已有对应对象或行为？
2. 它是否属于本项目选择重实现的 server 范围？
3. 如果只是 Python 内部基础设施，是否不改变外部契约？

无法回答清楚的设计不得作为兼容实现前置条件。

## 5. 服务端能力模型

## 5.1 控制面业务

控制面负责组织和工作对象的业务状态：

- organization、agent、project 和 goal
- issue、comment、approval 和 review
- chat / messenger
- activity、cost 和 budget

Route 层解析并验证 HTTP 请求；Service 层实现上游业务语义；Database 层负责持久化映射和查询。

## 5.2 服务端执行流程

上游 `server` 不仅保存业务对象，还负责将 agent 工作推进到实际执行。因此 Octopus 必须逐步重实现：

1. 请求、定时规则或业务事件触发 wakeup
2. 服务端建立或领取 run
3. 服务端按 agent 配置调用对应 runtime adapter
4. runtime 在解析出的 workspace 上执行工作
5. 服务端记录状态、事件、日志摘要、结果和成本
6. 成功、失败、取消或恢复流程更新相关业务对象

这一流程属于 server 内部的业务执行链路，而不是外围基础设施管理。

实施边界上，Agent 阶段不能只停留于 CRUD 和配置存储：它必须建立 wakeup/run/adapter 闭环，并以 `codex_local` 与最小 conversation/message 链路证明 agent 可以被真实交互触发。经上游核对，chat assistant 通过内部 invocation id 直接调用 runtime，不将对话回复伪装为持久化 heartbeat run；最小消息链路仅承担触发执行和保存响应，不代替完整 chat / messenger 子系统。更完整的调度恢复、其他 adapter 类型、workspace 生命周期和成本治理仍按后续阶段扩展。

## 5.3 Runtime adapter

`packages/runtimes/` 承担 runtime 适配边界：

- 定义统一调用 contract
- 按上游 runtime type 接入具体实现
- 归一化输出、usage、session 与错误结果
- 保持外部 runtime id 与上游兼容

`server/services/` 决定何时调用 runtime 以及调用结果如何影响 issue、run、cost 和 activity。Runtime 包自身不定义控制面状态机。

## 5.4 Workspace

Workspace 是执行上下文的一部分。若上游在对应阶段包含 project workspace、execution workspace、operation 或资源关联，Octopus 应按其 schema 和 workflow 实现：

- workspace 的创建、选择与关联
- run 使用 workspace 的规则
- 清理、失败处理和恢复记录
- 与 issue 或 work product 的关系

Workspace 不应被简化为任意本地目录字段，也不应在尚未核对上游行为前自行扩展。

## 5.5 Actor 与访问语义

Actor、认证和授权相关能力只按上游 API 与服务端行为实施：

- 已在目标阶段核对的 board 或 agent 操作边界应落入 contract 和测试
- 未核对的身份模型不得提前替代上游请求语义
- 调用上下文属于请求处理信息，不应擅自改变原始业务 payload

当前阶段尚未实现完整的认证和用户上下文注入，但 organization、issue、approval 等已落地流程必须可以在本地启动服务后调试。因此，在真实 auth 能力落地前，允许提供统一且显式的本地开发 actor：

- 本地开发 actor 默认表达 board 操作主体，例如 `{"type": "board", "id": "local-board"}`
- 它只用于无认证开发阶段的接口调试、activity 记录和已实现工作流验证
- 它必须通过统一的 request context / dependency 边界接入，不允许各 route 分别写死不同 actor
- 当前启用方式为设置环境变量 `OCTOPUS_LOCAL_TRUSTED=1`；未设置时默认关闭
- 启用方式必须是显式开发配置，不能在面向真实部署的默认行为中静默绕过访问校验
- 当对应上游 auth / actor 契约进入实现范围后，应由真实请求 actor 替换本地开发 actor，不改变既有业务 service 的语义

本地开发 actor 不是新身份模型，也不构成对上游权限体系的替代；它是未实施 auth 子系统前，为保持已实现 server 流程可运行、可审计、可测试而设置的阶段性接入边界。

## 5.6 调试数据与兼容数据形态

在功能尚未完整接入真实用户、runtime 或外围资源的开发阶段，可以提供模拟数据，以支持 API 调试、界面联调和工作流验证。但模拟数据只能替代数据来源，不能改变数据结构或业务语义。

模拟数据必须遵守：

- 使用与上游一致的业务表、字段名、关联关系、enum 和状态值
- 通过当前已实现的 schema、validator、service 或公开 API 写入，不维护一套仅供调试使用的替代 payload
- actor、organization、issue、approval、activity 等记录之间的关系必须与真实流程一致
- 若某项上游字段在当前步骤尚未实现，应按阶段文档明确缺口，而不是使用本地专用字段填补
- runtime、workspace、cost 或 chat 的模拟记录在进入对应实施阶段后，也必须服从其上游 contract

调试支持允许包括：

- 确定性的 seed 数据
- 测试 fixture 与本地演示数据集
- 受配置控制的本地开发 actor
- 对尚未连接真实 runtime 的兼容结果样本

调试支持不允许包括：

- 只在 Python 版本存在的业务字段或表
- 为绕过未实现业务规则而创建的快捷接口
- 与上游状态机不一致的假状态或假副作用
- 使测试通过但无法与上游对照的简化数据模型

因此，调试阶段的目标不是“先用一套临时结构跑起来”，而是“先用上游兼容结构中的模拟内容跑通已实现范围”。真实接入完成后，只替换数据来源，不返工数据模型。

## 6. 代码结构

目录结构以服务端兼容实现为中心：

```text
octopus/
  server/
    routes/
    services/
    dependencies/
    background/
    storage/
    observability/
    resources/
  packages/
    database/
      schema/
      queries/
      migrations/
    shared/
    runtimes/
  tests/
    contract/
    workflows/
    scope/
  docs/
  ui/
```

`ui/` 仅在兼容验证或后续明确迁移需求下使用，不是当前 server 实现的优先路径。

## 6.1 `server/`

`server/` 对应上游服务端实现，负责：

- 应用启动、配置和生命周期
- API 路由注册与请求验证
- 业务 workflow 与事务编排
- run、wakeup、恢复和后台执行
- 调用 database、shared contract 与 runtime adapter

启动边界保持拆分：`server/__init__.py` 只提供 `uv run server` 命令包装并读取绑定配置，`server/app.py` 保留 FastAPI 应用工厂与底层 ASGI `app` 对象，供测试和部署加载。

## 6.2 `packages/database/`

数据库包负责：

- 映射上游业务 schema
- 维护 SQLAlchemy session 和 query 边界
- 通过 Alembic 管理 Python 实现需要的迁移

原则是优先映射上游已有表。只有不改变业务契约且确实服务于 Python 运行机制的持久化结构，才允许作为明确记录的基础设施扩展。

## 6.3 `packages/shared/`

Shared contract 包负责稳定复用的契约内容：

- enum 与状态值
- request / response schema
- validators
- API path 常量

它的衡量标准是契约一致性，而不是 Python 类型设计的新颖程度。

## 6.4 `packages/runtimes/`

Runtime 包按上游提供的 runtime 种类分离实现，避免将不同 adapter 的行为揉入单一模块。

Python 导入路径可使用下划线；对外兼容的 runtime id、数据库值和 API 表达必须以实际上游契约为准。

## 7. 分层职责

## 7.1 Route 层

Route 层负责：

- 匹配上游 API path 与 HTTP method
- 校验输入并解析必要调用上下文，包括当前阶段统一注入的本地开发 actor
- 调用 service
- 输出兼容响应和错误状态

Route 层不实现跨对象状态机或复杂副作用，也不得在单个路由中临时写死 actor 身份。

## 7.2 Service 层

Service 层是兼容行为核心，负责：

- organization、issue、approval、chat 和 run 生命周期
- 业务状态转移与权限语义
- transaction 边界
- activity、cost、budget 等副作用
- runtime 调用与 workspace 流程衔接

服务实现必须可由上游 route/service/test 证据解释。

## 7.3 Persistence 层

Persistence 层负责数据读写、join、过滤与存储映射，不负责解释“审批意味着什么”或“某次执行何时应触发恢复”。

## 7.4 Background 层

Background 层只实现上游 server 需要的异步或周期性处理，例如：

- heartbeat scheduling
- queued run 推进
- interrupted run recovery
- budget 检查
- 受约束的清理任务

每类任务必须有明确的业务作用域、幂等策略、失败行为和测试依据。

## 8. 数据兼容策略

## 8.1 业务表

已纳入重实现范围的上游业务表应按源实现映射，包括但不限于：

- `organizations`
- `agents`
- `projects`
- `goals`
- `issues`
- `issue_comments`
- `approvals`
- `heartbeat_runs`
- chat、activity、cost、budget 与 workspace 相关表

字段、索引、外键和行为应以所对齐的上游版本为准。

## 8.2 Migration

Alembic 用于管理 Octopus 的 Python schema 演进。Migration 必须服务于已确认的兼容模型：

- baseline 应仅包含当前已确认纳入范围的表
- 后续阶段新增的上游业务表以迁移形式落地
- 不为未经上游确认的模型新增业务表
- 本地测试数据库可按开发文档说明重建；生产迁移需要单独验证兼容路径

## 8.3 并发和事务

Organization scope 不能替代事务正确性。对 checkout、approval decision、run claim、budget stop 等并发敏感动作，需要根据上游语义使用：

- 事务
- 唯一约束或条件更新
- 状态校验
- 幂等与重试规则

## 9. API 兼容策略

API 实现至少必须对齐：

- 路由路径和 HTTP method
- query、body 与 response shape
- 字段命名、默认值、nullability 和 enum
- 排序、过滤与分页行为
- 关键错误状态和副作用

Octopus 不应为本地实现便利增加上游没有的 HTTP 业务接口。内部工具函数或数据库抽象可以变化，但面向调用方的 server 契约必须可对照验证。

## 10. 测试与验收

## 10.1 Contract 测试

Contract 测试验证：

- schema 与迁移内容符合当前已确认范围
- API path、payload 与返回结构符合上游
- enum、nullability、默认行为和错误语义一致
- seed、fixture 和本地演示数据只使用当前已确认的上游兼容结构

## 10.2 Workflow 测试

Workflow 测试验证端到端服务语义，例如：

- organization 创建后进入 issue 与 approval 流程
- issue 创建、评论、review 和状态流转
- approval 决策及 activity 副作用
- run 创建、执行、结果持久化、cost 与 budget 处理
- workspace 选取、释放和失败恢复
- 使用模拟数据驱动的流程与后续真实数据来源复用同一套 service 和 contract

## 10.3 Scope 与并发测试

需要验证：

- organization 数据边界
- actor 语义与阶段内已实现的访问限制
- 无认证开发阶段启用本地开发 actor 后，organization、issue 与 approval 已实现流程可以一致调试并记录同一 actor 来源
- 未启用本地开发 actor 且未提供真实 actor 时，需要身份上下文的路径按当前契约拒绝访问
- run claim、checkout 或审批决策的并发行为
- 失败恢复不会产生重复副作用

## 10.4 对照验证

每个功能阶段结束前，都应对照上游对应 schema、route、service 或测试记录结论。若本地规划与上游源码冲突，以兼容目标范围内的上游实现为准，并先更新文档再继续编码。

## 11. 实施阶段

具体工作拆分以 `docs/FEATURE.md` 和各 `docs/step-*` 文档为准。总体顺序保持为：

1. 固定项目边界、契约清单和 server 骨架
2. 建立 shared contract、database schema 与 migration 基础
3. 实现 organization-scoped read API、核心 mutation workflow、统一本地开发 actor 接入与兼容 seed 数据
4. 实现 issue、approval、activity 等控制面语义
5. 以 agent 为入口建立 wakeup、run、`codex_local` runtime adapter 与最小消息触发/响应闭环
6. 扩展运行恢复、其他 runtime 覆盖、完整 chat、workspace、cost 与 budget 等服务端流程
7. 完成恢复、并发、可观测性和上游兼容回归

阶段性裁剪必须服从两条规则：

- 不提前实现不属于当前阶段的功能
- 不永久删除已确认属于目标 server 的上游语义

## 12. 主要风险

## 12.1 误把重写变成重设计

表现包括新增上游不存在的业务对象、状态机或访问前置条件。防护方式是每个模型与流程都提供上游对照证据。

## 12.2 误删服务端执行语义

只关注 CRUD API 而忽略 heartbeat、runtime、workspace、run recovery，会导致 Python 版本无法替代上游 server。Agent 首次交付必须包含可由消息触发的 `codex_local` 可运行闭环；完整 chat 与其他执行面能力再按后续阶段扩展。

## 12.3 契约漂移

字段、错误码、默认值或副作用的微小差异也会破坏兼容性。需要持续维护 contract 和 workflow 回归测试。

## 12.4 Scope 与并发错误

跨 organization 读写、重复执行或错误恢复都可能造成严重数据问题。需要在查询、service、后台任务与并发测试中同时约束。

## 13. 结论

Octopus 的设计结论是：

- 它是上游控制面 `server` 的 Python 兼容替代实现
- 数据模型、API 和关键业务语义以纳入范围的上游源码为准
- organization、issue、approval、chat、run、cost、budget、activity 等服务端能力应分阶段重实现
- heartbeat、runtime adapter、workspace、执行恢复与日志记录属于应保留的 server 执行能力
- 与当前 server 兼容目标无关的外围模块可以裁剪
- 上游不存在的新业务约束和新架构概念不得被引入为实现前提

最终验收标准不是“Python 服务能够运行”，而是：

`在已选择重实现的 server 能力范围内，调用方不需要因为后端从上游技术栈切换为 Python 而改变其业务使用方式。`
