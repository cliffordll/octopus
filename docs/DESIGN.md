# Octopus 设计方案

## 1. 文档目标

本文档定义 Octopus 的整体设计方案。

Octopus 的目标不是重新发明一个新产品，而是用 Python 对 上游参考实现 的服务端做一次兼容式重写。在这次重写中，核心约束已经非常明确：

- 保持 上游参考实现 现有数据库表结构不变
- 保持 上游参考实现 现有 API 接口不变
- 保持 上游参考实现 现有控制面语义不变
- 支持多个 pod 连接同一个数据库
- 每个 pod 只处理自己独占的一组 organization，绝不交叉
- pod 控制、organization 分配、外层代理服务由其他项目实现，不在 Octopus 项目内实现
- auth 相关能力由外层系统负责，本项目不实现完整认证与鉴权体系
- 仓库目录结构尽量参考 上游参考实现，允许轻微改名，但不重造一套完全不同的结构

因此，Octopus 的本质不是新系统设计，而是一次带有明确兼容边界的重写工程。

## 2. 背景与问题定义

上游参考实现 当前是一个以 Node/TypeScript 为主的控制平面系统，负责组织、agent、issue、chat、approval、run、cost、budget、activity 等核心对象的编排与治理。

现在的目标是：

- 用 Python 替换现有服务端实现
- 不要求前端跟着重写
- 不要求数据库做业务层迁移
- 不要求用户理解一个新的系统模型

换句话说，Octopus 必须尽可能表现得像今天的 上游参考实现：

- 前端照常调用
- 现有数据库照常使用
- API 返回结构不变
- 状态机和副作用语义不变

同时，Octopus 的部署又不是纯单机：

- 多个 pod 会同时运行
- 所有 pod 共享同一个数据库
- 但 organization 在 pod 之间是独占分配的
- 组织归属、pod 启停、任务代理注入由外层系统协调

这意味着系统既不能简单按“单机玩具项目”去实现，也没必要上来就按“全局分布式多写协调”去实现。正确的定位是：

`按 organization 分区的单写控制平面`

## 3. 设计原则

## 3.1 兼容优先，而不是重设计优先

这次重写必须遵循“先保兼容，再谈优化”。

允许变化的内容：

- 编程语言
- Web 框架
- ORM 或数据访问实现
- 内部模块划分
- 后台任务实现方式
- runtime adapter 的内部实现

不允许随意变化的内容：

- API 路径
- 请求参数
- 响应 JSON 结构
- 数据库业务表结构
- 枚举值和状态值
- 核心控制面语义
- 前端依赖的行为

## 3.2 以 上游参考实现 为契约源，而不是以 Python 习惯为契约源

Octopus 的契约来源不是“Python 世界里怎么写更优雅”，而是：

1. 上游参考实现 当前数据库 schema
2. 上游参考实现 当前 API 行为
3. 上游参考实现 当前产品语义

Python 只是新的实现语言，不是新的产品定义权。

## 3.3 Organization 是第一层隔离边界

上游参考实现 的业务天然是 organization-scoped。Octopus 必须保持这一点：

- 所有业务对象属于 organization
- 所有请求都必须先过 organization 边界
- 所有后台任务只处理当前 pod 拥有的 organization
- 所有运行时动作都不能越过 organization 边界

## 3.4 在 organization 内采用单写心智

因为你已经明确要求：

- 每个 pod 只处理自己独占的 organization
- organization 不会被多个 pod 同时处理

所以 Octopus 的核心设计不应朝“同一 organization 上的全局分布式竞争”去复杂化，而应采用：

- organization 内单写
- organization 间水平分区

这会极大降低 issue checkout、chat generation、run scheduling、budget enforcement 这类流程的并发复杂度。

## 3.5 持久化真相仍然在数据库

尽管 organization 在 pod 级别独占，数据库仍然是持久真相来源。

内存里可以放：

- 缓存
- 短生命周期运行态
- 当前 pod 的本地调度状态

但不能只放在内存里：

- 持久业务状态
- organization ownership 真相
- 需要跨进程恢复的重要状态

## 3.6 Octopus 只适配 pod 运行环境，不实现外层编排系统

Octopus 的设计必须考虑自己运行在多 pod 环境中，但不应在本项目内实现以下能力：

- pod 创建
- pod 销毁
- pod 扩缩容
- organization 分配到 pod
- 外层业务代理入口
- 外层运维编排系统

这些能力由别的项目负责。

Octopus 在当前项目中的职责应保持收敛：

- 感知自己的 pod identity
- 知道自己拥有哪些 organization
- 拒绝处理不属于自己的 organization
- 提供 上游参考实现 兼容业务 API
- 消费外层注入的 actor/context，而不是自己实现完整 auth 体系

## 4. compatibility-preserving rewrite 在本项目中的具体含义

“compatibility-preserving rewrite” 在本项目中的准确含义是：

`重写实现，但保持外部契约不变。`

落到 Octopus 上，就是：

- 可以把 Node/TypeScript 实现替换为 Python
- 可以把 Express 替换成 FastAPI
- 可以把 Drizzle 风格的数据访问改成 SQLAlchemy 风格
- 可以重写内部 service、route、background 的代码

但必须尽量保持这些东西不变：

- 现有数据库可以直接继续使用
- 现有前端可以直接继续调用
- API 路由不变
- 请求与响应结构不变
- 关键状态机不变
- 关键副作用不变

从工程视角看，这不是“新系统从零设计”，而是“兼容替代实现”。

## 5. Octopus 的系统定位

Octopus 继承 上游参考实现 的产品定位：

- 它是 agent work 的控制平面
- 它不是通用聊天应用
- 它不是纯 runtime 执行器
- 它不是 Jira/GitHub 的完全替代品

它负责的仍然是：

- organization 管理
- agent 注册与编排
- issue 和 comment 生命周期
- chat intake 与转 issue
- approval 与治理动作
- heartbeat run 与执行状态跟踪
- 成本与预算
- activity 与可审计可见性

这个定位必须在重写中保持清晰，否则很容易在 Python 重写过程中把系统做偏。

## 6. 部署模型设计

## 6.1 基本部署模型

Octopus 的运行环境为：

- 一个外层控制系统或代理系统
- 多个 server pod
- 一个共享 PostgreSQL 数据库
- 每个 pod 独占一组 organization

但该外层系统不在 Octopus 项目内实现。

这里最重要的不是“多个 pod”，而是“每个 organization 在同一时刻只归一个 pod 管”。

这意味着：

- 默认情况下，同一 organization 的业务请求通过外层系统代理到 owning pod
- 在必要场景下，也允许直接访问 owning pod
- 同一 organization 的后台任务必须只在 owning pod 执行
- 同一 organization 的 run/chat/issue/budget 变更必须只由 owning pod 处理

## 6.2 为什么这不是普通单机

虽然每个 organization 可以按单写思路处理，但整个系统仍然不是普通单机，原因是：

- 多个 pod 共用数据库
- pod 可能重启
- organization 归属可能迁移
- 错误路由仍然可能发生
- 后台扫描若写错，很容易误处理别的 organization

所以真正的系统模型应理解为：

`external control plane + shared database + org-level ownership + pod-local single-writer execution`

## 6.3 Organization Ownership 机制

Octopus 需要明确的 organization 归属机制。

推荐使用持久化 ownership 或 lease 记录，例如：

- organization_id
- pod_id
- lease_version
- acquired_at
- last_heartbeat_at
- expires_at

它的职责是：

- 标识某个 organization 当前归哪个 pod
- 支持 pod 周期性续约
- 支持 pod 失效后接管
- 支持 server 在收到请求时校验自己是否有权处理该 organization

这类表属于基础设施状态，不属于 上游参考实现 的业务表重构，因此不违背“业务表结构保持不变”的要求。

## 6.4 外层系统的职责边界

Octopus 之外通常会存在一个外层控制系统，它不是 上游参考实现 业务语义的实现层，而是 Octopus 的外层编排与代理层。

它通常负责：

- 管理 pod 启停
- 分配 organization -> pod ownership
- 维护 organization 到 pod 的路由映射
- 代理业务任务注入到正确 pod
- 做 pod 健康监测
- 做 drain、迁移、failover

它不应该负责：

- 直接改 上游参考实现 业务表
- 直接执行业务状态机
- 直接绕过 Octopus service 写入 issue/chat/approval/run 等业务对象

正确边界是：

- 外层系统负责编排与路由
- Octopus 负责 上游参考实现 兼容业务语义

## 6.5 业务任务注入模型

你已经明确要求业务任务通常会通过外层系统代理注入，但 pod 仍需保持独立访问能力。

因此，推荐的注入模型是“双入口、单语义”：

- 标准入口：经外层系统代理
- 保留入口：直接访问目标 pod

这两种入口都必须进入同一套业务实现。

典型业务任务包括：

- 新建 issue
- 发起 chat
- 创建 approval
- 触发某个 agent run

这些动作在工程上都应通过 Octopus 的业务 API 落地，而不是由外层系统直接写业务表。

原因：

- 需要保留 validator
- 需要保留 activity log
- 需要保留 organization 边界检查
- 需要保留 ownership 校验
- 需要保留 上游参考实现 原本的状态机语义

## 6.6 代理访问与直连访问

### 6.6.1 代理访问

代理访问是推荐的标准路径：

1. 调用方请求外层系统
2. 外层系统根据 organization_id 查 owning pod
3. 外层系统转发请求给目标 pod
4. 目标 pod 执行正常 上游参考实现 兼容逻辑

适用场景：

- 正常生产业务接入
- 平台任务注入
- 多 organization 路由
- failover 后透明切换

### 6.6.2 直连访问

直连访问仍然需要保留。

原因：

- 便于调试
- 便于回放
- 便于运维
- 便于在已知归属关系的场景下降低代理层依赖

但直连访问并不意味着越权访问。直连访问必须满足：

- 请求明确携带 organization 语义
- pod 本地校验 organization ownership
- 若 organization 不属于当前 pod，则直接拒绝
- 仍然走同一套 route -> service -> db -> activity 逻辑

## 6.7 双入口一致性原则

无论请求来源于：

- 外层系统代理
- 还是直接访问 pod

都必须遵守相同的业务处理链路：

- 相同的 payload validator
- 相同的调用上下文解析
- 相同的 organization 边界检查
- 相同的 ownership 校验
- 相同的 service 层
- 相同的 activity log
- 相同的错误码语义

严禁出现两套业务实现：

- 一套给代理请求
- 一套给直连请求

否则文档层面说的是一个系统，实际运行会变成两个行为不同的系统。

## 6.8 外层代理转发时应携带的上下文

外层系统代理请求时，建议向 Octopus 透传明确的上下文信息，例如：

- organization_id
- target_pod_id
- forwarded_by=control-service
- request_id / trace_id
- 原始调用方身份信息
- 是否为平台注入任务

这些上下文的作用是：

- 提升日志可读性
- 便于调试 ownership 问题
- 便于平台审计
- 便于后续增加平台级策略控制

但这些上下文只是辅助信息，不能替代 pod 本地的 ownership 校验。

## 6.9 接口命名与接口边界

Octopus 的 HTTP 接口命名必须与 上游参考实现 保持一致。

这不仅包括对外业务接口，也包括任何需要通过 HTTP 暴露的接口面命名约束：

- 不新增一套 Octopus 自定义命名风格
- 不引入 `/internal/...` 这类 上游参考实现 中不存在的新接口名前缀
- 不把运维、代理、调试诉求直接固化成新的 HTTP 接口名

Octopus 当前应承诺的接口面只有一类：

- 上游参考实现 已有契约中的接口

例如：

- `/api/orgs/...`
- `/api/issues/...`
- `/api/chats/...`
- `/api/approvals/...`

这些接口：

- 可以被 Control Service 代理调用
- 也可以被直接访问
- 但都必须执行 ownership 校验和同一套业务逻辑

对于 drain 控制、后台扫描触发、ownership 迁移、健康探测等需求：

- 如果 上游参考实现 已有对应接口，则继续复用 上游参考实现 的接口名
- 如果 上游参考实现 没有对应接口，则当前设计阶段不在 Octopus 中新增新的 HTTP 接口名
- 这些能力是否最终需要通过别的机制暴露，应交由外层系统设计决定，而不是在当前项目中先引入一套新命名

## 6.10 为什么 ownership 校验不能只靠外部路由

即使入口层已经把请求按 organization 路由到对应 pod，应用内仍然要做 ownership 校验，原因包括：

- 路由规则可能配置错误
- 外层系统转发逻辑可能出错
- pod 故障切换期间可能出现短暂双主认知
- 手工请求可能绕过预期入口
- 后台任务最容易越界扫描

因此，应用内 ownership 校验属于必要防线，而不是可选优化。

## 7. 目录与文件结构设计

你明确要求目录结构参考 上游参考实现，因此 Octopus 不应创造一套完全 Python 化但与 上游参考实现 无关的结构。

正确的做法不是简单保留几个一级目录名字，而是：

- 一级目录尽量与 上游参考实现 一致
- 二级、三级目录按职责清晰拆开
- 入口文件位置稳定
- 契约层、数据库层、服务层、测试层边界明确

推荐结构如下：

```text
octopus/
  server/
    pyproject.toml 或 requirements 相关文件
    src/
      app.py
      config.py
      lifespan.py
      routes/
      services/
      middleware/
      background/
      storage/
      observability/
      lib/
    resources/
      skills/
        bundled/
          conversation-to-skill/
          skill-creator/
      plugins/
      mcp/
    tests/
  packages/
    database/
      schema/
      clients/
      queries/
      migrations/
    shared/
      constants/
      types/
      validators/
      api_paths/
    runtimes/
      shared/
      claude_local/
      codex_local/
      opencode_local/
      openclaw_gateway/
  ui/
  docs/
  tests/
```

这里使用 `docs/` 是因为你明确要求设计文档放在 `docs/` 下。除此之外，整体骨架仍然尽量贴近 上游参考实现。

## 7.1 顶层目录设计

### 7.1.1 `server/`

作用：

- Python 服务端主实现

这是整个仓库最核心的目录，对应 上游参考实现 的 `server/`。

它不只是一个 HTTP API 层，而是整个控制平面执行中枢，负责：

- route 注册与请求处理
- 调用上下文解析
- organization ownership 校验
- 业务 service 协调
- run/chat/approval 等流程执行
- background loops
- 调用 runtimes 包
- activity side effect

`server/` 负责决定何时调用 runtime，以及调用后在 上游参考实现 业务上意味着什么。
它不负责沉淀 runtime adapter 的通用实现细节。

### 7.1.2 `packages/database/`

作用：

- 数据库映射与数据库边界实现

它对应 上游参考实现 的 `packages/db/` 这一职责边界，但在 Octopus 中目录名统一使用 `packages/database/`，因为这个名字更直观。

这一层的目标不是重新设计 schema，而是：

- 用 Python 正确映射当前 上游 schema
- 提供统一 DB session 与事务能力
- 隔离数据库细节，避免 server/service 到处散 SQL

### 7.1.3 `packages/shared/`

作用：

- 共享契约层

它对应 上游参考实现 的 `packages/shared/`，在 Octopus 中仍然有必要保留。

其职责是：

- 承载枚举
- 承载常量
- 承载 request/response schema
- 承载 validator
- 承载 API path 常量

这层的目标不是“Python 类型体操”，而是“契约固定”。

### 7.1.4 `packages/runtimes/`

作用：

- runtime 适配边界

这一层应参考 上游参考实现 当前的真实实现方式：按 runtime 类型拆成多个包，而不是做成一个大一统目录。

它负责定义 Octopus 如何与不同 agent runtime 通信，而不负责决定这些调用在 上游参考实现 业务上意味着什么。

其职责应包括：

- 各 runtime 包的 server 侧适配
- 各 runtime 包的 ui 侧适配
- 各 runtime 包的 cli 侧适配
- 共享 runtime contract
- transcript 或运行结果的归一化

这样可以把“怎么和 runtime 说话”与“什么时候调用 runtime、调用后如何修改业务状态”分开，也更利于和 上游参考实现 的现有 runtime 包逐个对照迁移。

这里需要额外明确一条 Python 迁移规则：

- Python 包目录名使用下划线，例如 `claude_local/`
- 上游兼容 runtime id、配置值、数据库语义、接口语义保持横杠，例如 `claude-local`
- 两者不能混为一体，必须通过集中 registry 或 mapping 进行对齐

### 7.1.5 `ui/`

作用：

- 保持与 上游参考实现 一致的前端边界

即使第一阶段不重写 UI，也建议保留该目录，因为：

- 上游参考实现 仓库本来有该层级
- 未来可能需要前端联调
- 有些兼容测试会天然依赖 UI 端接口认知

### 7.1.6 `docs/`

作用：

- 设计说明
- 架构说明
- 迁移与兼容计划
- 关键决策文档

当前阶段先确认方案，因此 `docs/` 是当前最主要的目录之一。

### 7.1.7 `tests/`

作用：

- 仓库级兼容测试
- 跨模块工作流回归测试
- organization ownership 安全测试

这里的 `tests/` 是仓库级测试目录，不代替 `server/tests/` 或局部包内测试。

它主要放跨边界测试，而不是每个模块自己的细碎单元测试。

## 7.2 `server/` 详细结构

推荐结构：

```text
server/
  src/
    app.py
    config.py
    lifespan.py
    routes/
      __init__.py
      orgs.py
      agents.py
      goals.py
      projects.py
      issues.py
      approvals.py
      chats.py
      activity.py
      costs.py
    services/
      __init__.py
      orgs.py
      agents.py
      goals.py
      projects.py
      issues.py
      approvals.py
      chats.py
      activity.py
      costs.py
      budgets.py
      ownership.py
      heartbeat_runs.py
      proxy_context.py
    middleware/
      request_id.py
      error_handler.py
      request_context.py
    background/
      scheduler.py
      budget_checks.py
      run_recovery.py
      ownership_renewal.py
    storage/
      base.py
      local_disk.py
      s3.py
    observability/
      logging.py
      metrics.py
      tracing.py
    lib/
      time.py
      ids.py
      paging.py
      errors.py
  resources/
    skills/
      bundled/
        conversation-to-skill/
        skill-creator/
    plugins/
    mcp/
  tests/
    test_routes/
    test_services/
    test_background/
```

### 7.2.1 `server/app.py`

作用：

- 应用入口
- 创建 FastAPI app
- 注册 middleware
- 注册 routes
- 初始化全局依赖

这相当于 上游控制面服务端启动入口的 Python 版本。

### 7.2.2 `server/config.py`

作用：

- 环境变量读取
- 配置模型定义
- deployment mode、database、storage、ownership 相关配置入口

不要把配置散在各模块里。

### 7.2.3 `server/lifespan.py`

作用：

- server 启停生命周期管理
- 初始化 DB 连接
- 启动 background loops
- 注册资源释放逻辑

这样可以避免把后台任务启动逻辑塞进主入口文件。

### 7.2.4 `server/routes/`

作用：

- 上游参考实现 兼容业务 API 路由层

目录设计建议按资源面拆分，而不是按技术动作拆分。

例如：

- `orgs.py`
- `agents.py`
- `issues.py`
- `chats.py`

这样更容易与 上游参考实现 的 route surface 对齐，也更利于接口盘点。

这一层只承载 上游参考实现 兼容业务接口，不混入外层系统专用管理接口。

### 7.2.5 `server/services/`

作用：

- 核心业务语义实现层

这是最重要的目录之一。推荐按领域对象拆分：

- orgs
- agents
- issues
- approvals
- chats
- heartbeat_runs
- budgets
- ownership
- proxy_context

这里不只是 CRUD 层，而是控制面语义层。

### 7.2.6 `server/middleware/`

作用：

- 通用请求中间件

适合承载：

- request id
- 错误包装
- request context 注入
- logging hook
- 代理来源上下文注入

不应把复杂业务规则放在 middleware 中。

### 7.2.7 调用上下文边界

本项目不实现完整 auth 体系，因此不单独设计 `server/auth/`。

Octopus 只需要消费外层系统传入的调用上下文，例如：

- actor 标识
- actor 类型
- organization 标识
- 代理来源标记

Octopus 在本项目内要处理的是：

- 调用上下文解析
- organization 边界检查
- organization ownership 校验

而不是：

- 登录体系
- session 体系
- API key 发放与管理
- 完整权限系统

### 7.2.8 `server/background/`

作用：

- organization-scoped 后台任务

建议独立目录承载：

- heartbeat scheduling
- budget checks
- run recovery
- ownership renewal

原因是后台任务是这次部署模型中最容易越权的部分，必须结构上独立可审查。

注意：

`background/` 可以调用 `packages/runtimes/`，但不应在这里重复实现 runtime adapter 本身。

### 7.2.9 `server/storage/`

作用：

- 附件与对象存储边界

例如：

- local disk
- s3

chat attachment、artifact、generated file 等能力都需要这个边界。

### 7.2.10 `server/observability/`

作用：

- 日志、指标、追踪

这层虽然不是第一阶段最先实现的功能，但结构上建议预留，因为：

- 兼容调试需要可观测性
- 多 pod ownership 问题需要日志证据
- 外层代理链路需要追踪证据

### 7.2.11 `server/lib/`

作用：

- 无业务语义的基础 helper

只允许放真正通用的内容，例如：

- 时间处理
- ID helper
- 分页 helper
- 通用错误对象

不要把领域逻辑塞进 `lib/` 逃避归类。

### 7.2.12 `server/resources/`

作用：

- 服务端运行时资源

推荐在这里按资源类型分层，而不是把所有内容平铺：

- `skills/bundled/`
- `plugins/`
- `mcp/`

其中：

- `skills/bundled/` 用于内置 skills
- `plugins/` 用于未来插件资源
- `mcp/` 用于未来 MCP 相关资源或配置

额外约束：

- `skills/bundled/` 只是资源归档路径
- 其中每个具体 skill 目录名保持上游 skill id 语义，继续使用横杠，例如 `conversation-to-skill/`
- skill 目录不是 Python 包，不需要为了 import 合法性改成下划线
- 如果后续代码需要从 skill id 找到本地资源路径，应通过集中 mapping 或扫描逻辑处理，而不是重写 skill id 本身

这样可以为后续扩展留出清晰边界，而不必在后面再做一次资源目录重构。

### 7.2.13 `server/tests/`

作用：

- server 层内部测试

推荐放：

- routes 测试
- services 测试
- background 测试

这里偏向模块内与局部集成测试，不替代仓库根部 `tests/` 的兼容回归职责。

## 7.3 `packages/database/` 详细结构

推荐结构：

```text
packages/database/
  src/
    schema/
      organizations.py
      agents.py
      goals.py
      projects.py
      issues.py
      approvals.py
      chats.py
      activity.py
      costs.py
      ownership.py
      __init__.py
    clients/
      engine.py
      session.py
      transactions.py
    queries/
      org_queries.py
      issue_queries.py
      chat_queries.py
      run_queries.py
    migrations/
      versions/
```

### 7.3.1 `packages/database/schema/`

作用：

- 数据库对象定义

应尽量按 上游参考实现 的领域拆分，而不是做成一个大文件。

重点原则：

- 业务表与 上游参考实现 对齐
- 若新增基础设施表，例如 ownership，也单独清晰定义

### 7.3.2 `packages/database/clients/`

作用：

- DB 引擎、session、事务边界

这个目录应只处理数据库接入基础设施，不处理业务查询。

### 7.3.3 `packages/database/queries/`

作用：

- 复用型查询拼装

当某些查询跨多个 service 共享，或者 SQL 很复杂时，适合在这里沉淀。

注意：

- 这里适合放“查询”
- 不适合放“业务决策”

### 7.3.4 `packages/database/migrations/`

作用：

- 数据库迁移

重点原则：

- 不改 上游参考实现 现有业务表结构
- 只为 Python 重写新增必要基础设施表时使用

## 7.4 `packages/shared/` 详细结构

推荐结构：

```text
packages/shared/
  src/
    constants/
      api.py
      chat.py
      issues.py
      approvals.py
    types/
      orgs.py
      agents.py
      goals.py
      projects.py
      issues.py
      approvals.py
      chats.py
      runs.py
    validators/
      orgs.py
      agents.py
      goals.py
      projects.py
      issues.py
      approvals.py
      chats.py
    api_paths/
      routes.py
```

### 7.4.1 `packages/shared/constants/`

作用：

- 稳定常量定义

包括：

- 默认分页配置
- 枚举字面值常量
- route 相关常量
- 业务共享键名

### 7.4.2 `packages/shared/types/`

作用：

- 契约级 payload 模型

虽然 Python 不会直接复制 TypeScript 的类型系统，但这一层仍然有必要，因为它承载的是“契约对象划分”。

### 7.4.3 `packages/shared/validators/`

作用：

- request/response validator

例如：

- create issue payload
- update chat payload
- approval decision payload

这层建议按资源拆，不要做成一个超级 validator 文件。

### 7.4.4 `packages/shared/api_paths/`

作用：

- API 路径常量

上游参考实现 有共享 API path 的概念，Octopus 应保留这个边界，避免 route path 在前后端或测试中散落。

## 7.5 `packages/runtimes/` 详细结构

推荐结构：

```text
packages/runtimes/
  shared/
    src/
      base.py
      transcript.py
      results.py
  claude_local/
    src/
      server/
      ui/
      cli/
      index.py
  codex_local/
    src/
      server/
      ui/
      cli/
      shared/
      index.py
  opencode_local/
    src/
      server/
      ui/
      cli/
      index.py
  openclaw_gateway/
    src/
      server/
      ui/
      cli/
      shared/
      index.py
```

### 7.5.1 为什么这里按 runtime 分目录

参考 上游参考实现 现有实现，runtime 不是“一个总包 + 一堆文件”，而是：

- 每个 runtime 一套边界
- 每个 runtime 内再区分 server / ui / cli

这样做的好处是：

- 运行时差异不会全塞进一个大目录
- 顶层前端可以按 runtime 消费对应的 ui 适配
- server 可以按 runtime 消费对应的 server 适配
- 以后新增新 runtime 时，边界天然清楚

因此，Octopus 不应把所有 runtime 直接平铺到一个 `src/` 目录中，而应按 runtime 分包组织。

### 7.5.2 `packages/runtimes/shared/`

作用：

- 运行时共享 contract 和归一化逻辑

推荐结构：

```text
packages/runtimes/shared/
  base.py
  transcript.py
  results.py
  registry.py
```

这层承载：

- 统一 runtime 接口
- transcript 通用模型
- 运行结果通用模型
- Python 包路径与兼容 runtime id 的集中映射

`registry.py` 或等价模块必须承担一项职责：

- 把 `claude-local` 映射到 `packages.runtimes.claude_local`
- 把 `codex-local` 映射到 `packages.runtimes.codex_local`
- 把 `opencode-local` 映射到 `packages.runtimes.opencode_local`
- 把 `openclaw-gateway` 映射到 `packages.runtimes.openclaw_gateway`

这种映射必须集中管理，不能在各处用临时字符串替换推导。

### 7.5.3 `packages/runtimes/claude_local/`

作用：

- Claude 本地 runtime 适配包

推荐结构：

```text
packages/runtimes/claude_local/
  server/
  ui/
  cli/
  index.py
```

说明：

- `server/` 给 Octopus server 侧调用
- `ui/` 给顶层前端消费 runtime-specific 的前端适配逻辑
- `cli/` 给 CLI 或调试工具消费
- 目录名 `claude_local` 只是 Python 包路径；兼容 runtime id 仍然应保持 `claude-local`

### 7.5.4 `packages/runtimes/codex_local/`

作用：

- Codex 本地 runtime 适配包

推荐结构：

```text
packages/runtimes/codex_local/
  server/
  ui/
  cli/
  shared/
  index.py
```

说明：

参考 上游参考实现 的真实结构，`codex_local` 这类 runtime 包内部可能还需要自己的 `shared/`，用于该 runtime 独有但又会被 server/ui/cli 共同消费的逻辑。
兼容 runtime id 仍然应保持 `codex-local`，不能把下划线路径直接当成外部标识。

### 7.5.5 `packages/runtimes/opencode_local/`

作用：

- OpenCode 本地 runtime 适配包

推荐结构：

```text
packages/runtimes/opencode_local/
  server/
  ui/
  cli/
  index.py
```

兼容 runtime id 仍然应保持 `opencode-local`。

### 7.5.6 `packages/runtimes/openclaw_gateway/`

作用：

- OpenClaw Gateway runtime 适配包

推荐结构：

```text
packages/runtimes/openclaw_gateway/
  server/
  ui/
  cli/
  shared/
  index.py
```

说明：

像 gateway 型 runtime，往往会有额外共享逻辑，因此允许保留 runtime 自己的 `shared/` 目录。
兼容 runtime id 仍然应保持 `openclaw-gateway`。

### 7.5.7 每个 runtime 包内部的 `server/ui/cli` 分工

这里的 `ui` 不是“顶层前端应用”，而是“给顶层前端应用消费的 runtime 前端适配层”。

关系应理解为：

- 顶层前端应用负责页面、交互、路由
- `packages/runtimes/*/ui/` 负责该 runtime 的前端侧适配

例如：

- 构建 runtime config
- 解析 runtime stdout/transcript
- 提供 runtime-specific 的前端展示辅助

同理：

- `server/` 负责 runtime 的服务端适配
- `cli/` 负责 runtime 的命令行侧适配

### 7.5.8 `packages/runtimes/shared/base.py`

作用：

- 定义统一 runtime 接口

建议在这里定义统一的 runtime contract，例如：

- invoke
- status
- cancel

这一层只定义运行时交互能力，不定义 上游参考实现 业务语义。

### 7.5.9 `packages/runtimes/shared/transcript.py`

作用：

- transcript 标准化

适合放：

- stdout/stderr/transcript 归一化
- runtime 输出到控制平面可消费结构的转换

### 7.5.10 `packages/runtimes/shared/results.py`

作用：

- runtime 结果模型和结果归一化

这层的目标是把不同 runtime 的返回整理成 Octopus 可统一消费的结构。

## 7.6 `ui/` 详细定位

如果第一阶段 UI 不重写，`ui/` 可以暂时只承担以下角色：

- 占位边界
- 前端兼容说明
- 与 API contract 对照的必要夹层

如果后续需要前端代码迁移，则建议继续保持和 上游参考实现 相近的结构，而不是突然改成另一种完全不同的前端组织方式。

## 7.7 `docs/` 详细结构

推荐结构：

```text
docs/
  DESIGN.md
  FEATURE.md
  step-03/
    A-CONSTRAINTS.md
  step-04/
    SCHEMA-COMPATIBILITY.md
  step-07/
    A-CONSTRAINTS.md
    B-SPEC.md
    B-PLAN.md
```

这些文档的角色分别是：

- `DESIGN.md`
  总体设计说明
- `FEATURE.md`
  开发顺序、步骤边界和阶段验收说明
- `step-03/A-CONSTRAINTS.md`
  shared contract 层步骤约束
- `step-04/SCHEMA-COMPATIBILITY.md`
  现有业务表与字段兼容清单
- `step-07/A-CONSTRAINTS.md`
  组织管理步骤约束
- `step-07/B-SPEC.md`
  组织管理设计规格
- `step-07/B-PLAN.md`
  组织管理实施计划

当前阶段先写 `DESIGN.md` 是合理的，后续文档再逐步补齐。

## 7.8 `tests/` 详细结构

推荐结构：

```text
tests/
  contract/
    test_api_compatibility.py
    test_schema_compatibility.py
  workflows/
    test_issue_lifecycle.py
    test_approval_flow.py
    test_chat_to_issue.py
    test_budget_enforcement.py
  ownership/
    test_wrong_pod_rejected.py
    test_lease_expiry.py
```

### 7.8.1 `tests/contract/`

作用：

- 对照 上游参考实现 的契约兼容测试

### 7.8.2 `tests/workflows/`

作用：

- 核心工作流回归测试

### 7.8.3 `tests/ownership/`

作用：

- organization ownership 安全测试

## 7.9 第一阶段必须落地的目录

在第一阶段，不必把全部目录都填满，但下列目录最好从一开始就确立：

- `server/routes/`
- `server/services/`
- `server/background/`
- `server/middleware/`
- `packages/database/schema/`
- `packages/database/clients/`
- `packages/shared/types/`
- `packages/shared/validators/`
- `packages/runtimes/shared/`
- `packages/runtimes/claude_local/server/`
- `packages/runtimes/codex_local/server/`
- `packages/runtimes/opencode_local/server/`
- `packages/runtimes/openclaw_gateway/server/`
- `docs/`
- `tests/contract/`

这是最小但足够清晰的第一阶段结构。

## 7.10 第一阶段不必过早细化的目录

以下目录可以先保留设计位，不必一开始填太多：

- `server/observability/`
- `server/resources/skills/bundled/`
- `server/resources/plugins/`
- `server/resources/mcp/`
- `packages/runtimes/*/ui/`
- `packages/runtimes/*/cli/`
- `ui/`
- `tests/workflows/` 的所有细分文件

原因不是它们不重要，而是它们不应阻塞兼容重写的第一步。

## 8. 内部层次设计

## 8.1 Route 层

Route 层负责：

- 接收 HTTP 请求
- 解析和校验 payload
- 解析调用上下文
- 解析代理上下文
- 校验 organization 边界
- 校验 organization ownership
- 调用 service
- 返回兼容响应

Route 层不应该承担：

- 复杂业务状态机
- 跨对象流程拼装
- 深层数据库更新逻辑

原因很简单：如果把语义散落在路由里，兼容性会极难维护。

## 8.2 Service 层

Service 层是 Octopus 最关键的兼容实现层。

它应该承担：

- issue 生命周期语义
- approval 语义
- chat 生命周期语义
- run 生命周期语义
- cost / budget 语义
- activity log 触发时机
- transaction 边界
- 代理请求与直连请求的一致行为

换句话说，Route 层决定“请求进来了”，Service 层决定“上游参考实现 语义是什么”。

## 8.3 Persistence / Repository 层

Persistence 层负责：

- query 组织
- row 读取与写入
- join 查询
- lower-level hydration

它不负责：

- 审批意味着什么
- issue 什么时候可以流转
- chat 什么时候可以转 issue

这类语义必须留在 Service 层，否则很快会出现契约漂移。

## 8.4 Shared Contract 层

Shared Contract 层负责：

- enum 映射
- request schema
- response schema
- shared validation
- API 常量

它的核心目标不是“类型优雅”，而是“契约稳定”。

如果需要引入代理上下文字段，这些内容应清晰与 上游参考实现 兼容业务契约分开，不应混入原本业务 payload 语义。

同样地，任何由外层系统注入的 actor/context 信息，也应被视为调用元数据，而不是 上游参考实现 原始业务 payload 的一部分。

## 9. 数据设计策略

## 9.1 业务表保持不变

现有 上游参考实现 的业务表必须视为固定边界。

包括但不限于：

- organizations
- agents
- goals
- projects
- issues
- issue_comments
- approvals
- heartbeat_runs
- chat_conversations
- chat_messages
- chat_context_links
- chat_attachments
- activity 相关表
- cost / budget 相关表

Octopus 不应借重写机会擅自拆表、改名、重建状态含义。

## 9.2 可以新增的表必须是基础设施表

如果 Python 重写确实需要新增持久化结构，它们必须满足：

- 不改变 上游参考实现 业务表语义
- 只用于基础设施治理
- 数量尽可能少
- 文档中明确说明用途

可接受的候选包括：

- organization ownership / lease 表
- idempotency 支持表
- 可选 event outbox 表

## 9.3 事务边界不能因为“单组织独占”而放松

虽然一个 organization 只归一个 pod，但同一个 pod 内仍然可能有并发请求。

因此仍然需要：

- 正确的事务边界
- 正确的唯一约束利用
- 正确的状态流转校验
- 正确的错误码处理

organization ownership 只能减少跨 pod 协调复杂度，不能替代事务正确性。

## 10. API 兼容设计

API 兼容是这次重写的第一优先级之一。

这里必须明确：Octopus 的 API 面应统一遵循 上游参考实现 兼容接口约束，而不是拆成“兼容业务接口”和“自定义内部接口”两套命名体系。

## 10.1 必须保持一致的内容

至少必须保持：

- 路由路径
- HTTP method
- query 参数名称与含义
- body 结构
- response 结构
- nullability 行为
- enum 字符串
- 关键错误码语义

## 10.2 尽量保持一致的内容

在可能的情况下，也应保持：

- 默认排序行为
- 默认过滤行为
- 默认字段值
- 错误消息风格
- activity 副作用时机
- 创建/更新后的返回体细节

## 10.3 为什么“差不多兼容”不够

前端对 API 的依赖往往不是抽象层面的，而是非常具体的：

- 字段是否存在
- 字段是否可空
- 枚举字符串是否完全一致
- 某个错误是不是返回 409 而不是 422

所以“结构很像”并不等于兼容。

Octopus 需要追求的是：

`前端把它当成 上游控制面服务端 使用时，不需要感知后端语言已经换了。`

## 10.4 不新增自定义内部接口名

Octopus 不应为了适配外层系统而新增一套自定义内部 HTTP 接口名。

这里的约束是：

- 接口名保持与 上游参考实现 一致
- 若 上游参考实现 没有某个接口名，则当前阶段不在 Octopus 中自行补出新的 HTTP 接口名
- 外层系统需要的探测、迁移、编排能力，应优先通过 上游参考实现 既有接口、进程级机制或外层系统自身能力解决

因此，Octopus 的 API 兼容目标不是“业务接口兼容，内部接口另起一套名字”，而是“整个 HTTP 接口命名面尽量不偏离 上游参考实现”。

## 11. 后台任务设计

## 11.1 后台任务仍然可以每个 pod 自己运行

因为 organization 是独占的，所以每个 pod 都可以运行自己的 background loops，只处理自己拥有的 organization。

这类任务包括：

- heartbeat scheduling
- stuck run 检测
- budget threshold 检查
- interrupted run/chat recovery
- 少量清理任务

## 11.2 后台任务的首要原则是先过滤 owned organizations

后台任务的正确顺序应该是：

1. 先拿到当前 pod 拥有哪些 organizations
2. 再只查询这些 organizations 的工作对象
3. 再在这些组织范围内执行调度或修复

不应该使用：

- 先扫全库
- 再在业务逻辑末尾判断是否属于自己

因为那样最容易造成越权处理。

## 11.3 Background 设计不是“越多越好”

Octopus 不是为了展示 Python 异步能力而设计的。

后台任务应该尽量：

- 简洁
- 明确
- organization-scoped
- 易恢复
- 易验证

避免在初期引入复杂的全局调度编排。

## 12. Run 与 Runtime 设计

Octopus 继承 上游参考实现 的运行模型：

- control plane 发起执行
- runtime 真正执行 agent
- server 记录 run 状态与结果

因此 Python 重写必须保留这些职责：

- 通过 `packages/runtimes/` 调用 runtime
- observe status
- cancel run
- persist run state
- persist transcript/progress
- ingest cost
- 与 issue/chat 生命周期对接

这里最容易犯的错误是把 Octopus 直接做成“执行器中心”，而忘了它本质上是控制平面。

## 13. Chat 设计位置

Chat 是最复杂、最容易在兼容上出问题的部分之一。

因为它同时涉及：

- message 顺序
- streaming
- attachment
- context link
- ask-user 交互
- proposal
- convert-to-issue
- unread / pinned / attention state

所以在实施顺序上，Chat 不应排在最前。

更合理的顺序是：

- 先把 issue / approval / run / activity 这些核心控制面骨架做好
- 再做 chat 的兼容实现

## 14. 并发模型设计

## 14.1 同一 organization 内

同一 organization 内可以采用“单写控制平面”的设计心智。

这意味着很多原本需要跨 pod 竞争的问题，可以收缩为：

- pod 内事务正确性问题
- pod 内请求并发问题

例如：

- issue checkout
- chat turn 处理
- run 触发
- budget stop 触发

它们不必上来就做全局分布式锁体系。

## 14.2 organization 之间

organization 之间天然并行，最合理的横向扩展方式就是：

- 通过 organization 分区扩容 pod

而不是：

- 在单个 organization 内做复杂的多写协调

这和你给出的部署约束完全一致。

## 15. 测试与验证设计

这次重写的验证重点必须是“兼容性”，不是“Python 单测覆盖率数字”。

## 15.1 契约测试

需要重点验证：

- Python server 对比现有 上游控制面服务端 的 read API 响应
- Python server 对比现有 上游控制面服务端 的 mutation API 行为
- payload shape 是否一致
- enum/nullability 是否一致

并且要验证：

- 代理入口与直连入口在业务语义上等价

## 15.2 工作流测试

必须验证至少这些流程：

- issue 创建 -> 指派 -> 开始 -> 评论 -> review -> 完成
- approval 创建 -> 决策 -> 副作用落地
- chat 创建 -> 发消息 -> 回复 -> convert to issue
- run 启动 -> 状态更新 -> cost 上报 -> budget hard-stop

## 15.3 ownership 测试

必须验证：

- 正确 pod 能处理目标 organization
- 错误 pod 会拒绝处理目标 organization
- 过期 ownership 不被视为有效 ownership

还必须验证：

- 外层系统代理到正确 pod 时请求成功
- 外层系统若错误代理到错误 pod，请求被拒绝
- 直连 owning pod 与经代理访问的业务结果一致

## 15.4 为什么兼容性测试优先于零散单测

这类项目最大的风险不是一个小函数写错，而是：

- 某个 API 只差一个字段
- 某个流程只差一次 activity log
- 某个状态流转只差一个 409/422

因此兼容性回归测试的价值远高于大量脱离场景的琐碎单测。

## 16. 分阶段实施方案

Octopus 的实施必须分阶段进行。

推荐采用“约束先收口、实现后推进”的单向依赖方式：

- 先收口契约、schema、共享模型和兼容测试基线
- 再推进 server 骨架、service 实现、workflow 和 runtime 编排

这样拆分的原因是：

- 契约边界先稳定，服务实现才能减少返工
- 兼容判断集中，有利于控制契约漂移
- 依赖方向更清晰，冲突点更少

不建议在约束未稳定前一边改实现、一边随意漂移 shared/database 边界，因为那会让契约和实现相互反复拉扯。

在文档流转上，也应保持同样的单向依赖：

- 先在对应步骤目录内冻结约束文档
- 再按步骤约束落实现
- 执行记录和验收材料只能建立在步骤约束已经存在的前提下
- 如果发现缺口，先回收并更新步骤约束，再继续实现

## 阶段 1：契约盘点

目标：

- 盘点 上游参考实现 现有 schema
- 盘点 上游参考实现 现有 API surface
- 盘点关键状态机和副作用语义

输出：

- 数据表清单
- 路由清单
- 核心兼容检查清单

## 阶段 2：Shared Contract 层

目标：

- 镜像 enum
- 镜像 validator
- 镜像 request/response schema

输出：

- Python 版 shared contract 基础层

## 阶段 3：DB 映射层

目标：

- 映射现有 上游参考实现 业务表
- 确立 transaction/session 规范
- 只补必要的基础设施表

输出：

- Python 版 `packages/database`

## 阶段 4：Read API

目标：

- 先实现只读接口
- 尽早发现 payload shape 差异

原因：

- 只读接口更容易对比现有行为
- 更容易快速暴露契约问题

## 阶段 5：Mutation Workflow

目标：

- issue
- comment
- approval
- activity side effects

这一阶段开始真正接近 上游参考实现 的控制面语义核心。

在这一阶段就应同时确定：

- 代理入口与直连入口共用同一 service 实现
- 不引入第二套 mutation 处理逻辑

## 阶段 6：Run Orchestration

目标：

- heartbeat run
- runtime adapter
- cost ingestion
- budget enforcement

## 阶段 7：Chat Compatibility

目标：

- conversation
- message
- attachment
- streaming
- convert-to-issue

## 阶段 8：Hardening

目标：

- ownership failover
- background safety
- compatibility diff tooling
- 生产形态回归验证
- 外层代理链路与直连链路一致性验证

## 17. 主要风险

## 17.1 Schema 漂移

风险：

- Python 层对 上游参考实现 现有表结构的理解偏了

后果：

- 数据读写异常
- 前端表现不一致
- 历史数据兼容失败

## 17.2 Payload 漂移

风险：

- 返回 JSON 结构只“看起来差不多”

后果：

- 前端细节行为损坏
- 页面出现隐蔽错误

## 17.3 行为语义漂移

风险：

- issue、approval、chat、budget 等语义被不知不觉改了

后果：

- 系统不再是真正的 上游参考实现 兼容实现

## 17.4 Ownership 失效

风险：

- 错 pod 处理错 organization

后果：

- 数据污染
- 运行冲突
- 难以审计

## 17.5 后台任务越界

风险：

- background loop 扫描或处理了非本 pod organization

后果：

- 最容易出现隐性错误和跨组织副作用

## 17.6 重写过程中被“优化冲动”带偏

风险：

- 开始顺手重构 schema
- 顺手修改接口
- 顺手重新设计产品对象

后果：

- 项目不再是兼容式重写
- 迁移复杂度迅速失控

## 18. 结论

Octopus 的正确整体方案应当是：

- 用 Python 重写 上游控制面服务端
- 保持数据库业务表结构不变
- 保持 API 接口与 JSON 契约不变
- 保持控制面语义不变
- 在 Octopus 之外由其他项目负责 pod 编排、organization ownership 和业务代理注入
- 采用多 pod + 共享数据库部署
- 采用 organization 级别独占 ownership
- 默认通过外层系统代理访问业务 API，同时保留 pod 独立直连访问能力
- 代理访问与直连访问共享同一套业务实现
- 在 organization 内按单写控制平面实现
- 仓库结构尽量贴近 上游参考实现
- 按契约优先、分阶段实施、以兼容验证为中心推进

这套方案的关键价值在于：

- 不把项目做成“全新系统”
- 不把项目做成“简单翻译”
- 用最小必要的结构变化，获得语言重写与部署灵活性的收益

Octopus 应当是 上游参考实现 的 Python 兼容替代实现，而不是一个名字相近但行为不同的新产品。

