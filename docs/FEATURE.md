# Octopus 开发计划

## 1. 当前阶段

当前处于 `Phase 0 / 项目基础建设`。

这一阶段的目标不是尽快堆出业务代码，而是先把 Octopus 作为 上游控制面服务端 Python 兼容式重写项目的基础边界固定下来，确保后续实现不会偏离设计文档。

## 2. 当前目标

当前目标分为两层：

- 建立与 `docs/DESIGN.md` 一致的仓库结构和开发边界
- 为后续兼容实现准备最小可演进的服务端基础设施

现阶段关注的是“先把项目做对”，不是“先把功能做出来再回头收拾结构”。

文档组织规则：

- 规划类文档保留在 `docs/` 根目录，例如 `docs/DESIGN.md`、`docs/FEATURE.md`
- 每一步实际执行产生的操作文档必须单独放入步骤文件夹
- 步骤目录统一按 `docs/step-01/` 到 `docs/step-15/` 命名，与本文件中的 `Step 1` 到 `Step 15` 直接对应
- `docs/step-01/` 只放 Step 1 的执行记录
- `docs/step-02/` 只放 Step 2 的执行记录
- 从 `docs/step-03/` 开始，每个步骤目录都必须先有该步骤的 `A-CONSTRAINTS.md`
- `docs/step-03/` 放 Shared Contract 层文档
- `docs/step-04/` 到 `docs/step-15/` 分别放对应步骤的约束文档、规格文档和计划文档
- 在对应步骤真正进入实现前，后续步骤的 `A-CONSTRAINTS.md` 可以先保留草稿版本，不提前冻结字段级和行为级细节
- 执行文档只在对应步骤已经有约束输入后才允许补充，不允许先有实现再倒推约束

当前步骤文档归档：

- `docs/step-01/BASELINE-CLEANUP.md`
- `docs/step-02/SERVER-SKELETON.md`
- `docs/step-03/A-CONSTRAINTS.md`
- `docs/step-04/A-CONSTRAINTS.md`
- `docs/step-04/SCHEMA-COMPATIBILITY.md`
- `docs/step-05/A-CONSTRAINTS.md`
- `docs/step-06/A-CONSTRAINTS.md`
- `docs/step-07/A-CONSTRAINTS.md`
- `docs/step-08/A-CONSTRAINTS.md`
- `docs/step-09/A-CONSTRAINTS.md`
- `docs/step-10/A-CONSTRAINTS.md`

## 2.1 单人执行模式

当前项目按单人闭环模式推进：

- 同一执行者负责约束、规格、计划、实现、测试与验收
- 文档与实现必须同步推进，不再区分契约作者和实现作者

执行职责：

- 对照 `上游参考仓库路径` 盘点 API、schema、枚举、状态流转和副作用
- 维护 `packages/shared/` 的 path、types、validators 和共享常量边界
- 维护 `packages/database/` 的 schema 映射边界和查询边界
- 维护兼容测试基线
- 落地 `server/` 的 app、config、lifespan、routes、services、background
- 接入已经冻结的 shared contract 和 database 边界
- 实现 read API、mutation workflow、runtime orchestration
- 准备每一阶段的功能验收 demo
- 对“是否仍然 上游参考实现 兼容”给出判断

执行原则：

- 每个阶段仍先定义约束和边界，再进入实现
- 兼容测试和契约判断优先于局部功能速度
- 阶段验收时同时展示兼容验证结果和功能 demo
- 如果发现契约缺口或契约与 上游参考实现 不一致，先更新文档，再继续实现

## 2.2 分支与合并策略

默认采用“文档先收口、实现后提交”的顺序。

分支建议：

- `main`：只保留已验收内容
- 功能阶段可使用单个步骤分支，例如 `feat/contracts-step-08`

合并顺序：

1. 先完成 shared contract、database 边界、兼容测试基线或文档更新
2. 文档收口后再继续 server / workflow / runtime 实现
3. 阶段成果经用户验收后再合入 `main`

同步原则：

- 若分支仅个人使用，优先 `rebase main`
- 若分支已多人共享，改用 merge
- 若 `main` 上有新的契约边界更新，必须先同步再继续开发

冲突处理：

- 契约冲突以 上游参考实现 对照结果裁定
- 实现冲突不得突破已合入主干的契约边界
- 涉及兼容语义的冲突，必须先停下来核对 上游参考实现，不能直接拍脑袋合并

## 3. 工作原理与设计意图

Octopus 的本质是对 上游控制面服务端的兼容式重写，因此开发计划必须围绕以下原则推进：

- 外部契约以 上游参考实现 为准，不以 Python 习惯为准
- 先固定契约和结构，再写实现
- 先做只读和基础设施，再做复杂工作流
- 先做 ownership 边界和兼容验证，再做扩展能力

这意味着项目推进顺序必须服务于“兼容性验证”和“长期可维护架构”，而不是局部功能快速堆叠。

## 4. 本阶段交付

当前阶段应交付以下内容：

- 仓库目录结构与设计文档对齐
- 项目规范文档稳定
- 开发计划文档稳定
- Python 服务端基础配置收敛
- 最小服务端入口方案明确
- 基础测试目录和兼容测试入口位准备完成

## 5. 本阶段范围

本阶段范围包括：

- 目录骨架建设
- 基础配置文件收敛
- 服务端入口、配置、生命周期骨架设计
- 数据库层、共享契约层、runtime 适配层的目录和职责固定
- 测试分层方案固定
- 初始开发顺序和验收标准固定

## 6. 本阶段不做

本阶段明确不做以下内容：

- 完整业务 API 实现
- 大规模 schema 映射
- 完整 auth / 鉴权体系
- pod 编排系统
- organization 分配系统
- 前端重写
- 与 上游参考实现 兼容目标无关的 CLI、桌面或外围工具实现

## 7. 执行顺序

### Step 1. 仓库基础收敛

目标：

- 清理与 Octopus 目标无关的残留内容
- 让基础文件只服务于 Python 服务端兼容重写

输出：

- 收敛后的 `pyproject.toml`
- 收敛后的 `.gitignore`
- 与项目目标一致的顶层基础文件

验收：

- 顶层配置不再混入明显无关的旧项目信息
- 基础依赖和忽略规则能解释为 Octopus 所需

验收 demo：

- Demo 1：展示顶层目录清单，确认当前仓库只保留 Octopus 需要的顶层文件和目录
- Demo 2：展示 `pyproject.toml` 关键配置，说明每个核心依赖为什么存在、每个无关依赖为什么被删掉
- Demo 3：展示 `.gitignore` 关键规则，确认忽略项已经收敛到 Python 服务端项目所需
- Demo 4：展示 `CLAUDE.md` 关键章节，确认项目约束和提交流程已经固定
- 用户确认点：仓库基础文件是否已经足够干净，是否允许进入服务端骨架实现

分工：

- A：主导基础配置收敛标准、兼容边界说明、无关残留识别
- B：配合执行目录和配置收敛，确保后续 `server/` 落地不受阻

建议命令：

```powershell
Get-ChildItem -Force
Get-Content pyproject.toml
Get-Content .gitignore
Get-Content CLAUDE.md
git diff -- pyproject.toml .gitignore CLAUDE.md
```

### Step 2. 服务端骨架落地

目标：

- 在 `server/` 下建立最小可运行骨架

输出：

- `server/app.py`
- `server/config.py`
- `server/lifespan.py`
- `server/routes/`
- `server/services/`

验收：

- 可以启动最小服务入口
- 至少具备一个与 上游参考实现 接口命名约束不冲突的最小服务启动验证链路

验收 demo：

- Demo 1：展示 `server/app.py`、`config.py`、`lifespan.py`、`routes/`、`services/` 的最小文件结构
- Demo 2：启动最小服务端进程，展示应用已完成配置加载、应用创建和路由注册
- Demo 3：调用一个与 上游参考实现 接口命名约束不冲突的最小验证入口，展示返回结果
- Demo 4：说明当前服务端骨架中 route、service、config、lifespan 的职责边界
- 用户确认点：服务端骨架是否符合设计文档，是否允许进入共享契约层建设

分工：

- A：约束路由命名、共享依赖注入方式和契约边界
- B：主导 `server/` 骨架实现和最小启动链路

建议命令：

```powershell
uv run uvicorn server.app:app --host 127.0.0.1 --port 8000
```

接口示例：

- 第一批演示接口必须使用 上游参考实现 已有接口名
- 优先选择只读接口作为最小启动验证链路，例如：
  - `GET /api/orgs`
  - `GET /api/issues`

验收调用示例：

```powershell
curl http://127.0.0.1:8000/api/orgs
curl http://127.0.0.1:8000/api/issues
```

### Step 3. Shared Contract 层

目标：

- 建立共享契约层，避免 API path、枚举、payload 散落

输出：

- `packages/shared/constants/`
- `packages/shared/types/`
- `packages/shared/validators/`
- `packages/shared/api_paths/`

验收：

- 路由路径、共享枚举、请求响应模型有统一归位

验收 demo：

- Demo 1：展示 `packages/shared/` 下的目录和文件，确认 path、types、validators、constants 已按职责拆开
- Demo 2：选取一个 API path 常量，展示 route 如何直接复用它
- Demo 3：选取一个枚举、一个请求模型、一个 validator，展示它们如何作为共享契约被引用
- Demo 4：展示一个“如果不做 shared contract 会散落到哪里”的对照说明，证明该层已经收敛成功
- 用户确认点：共享契约边界是否清晰，是否允许进入数据库映射层建设

分工：

- A：主导 `packages/shared/` 设计和契约文件落地
- B：在 `server/` 中接入 shared contract，验证可用性

建议命令：

```powershell
Get-ChildItem -Recurse packages\shared
rg "api_paths|validators|types|constants" packages/shared
uv run pytest tests/contract -q
```

### Step 4. Database 映射基础层

目标：

- 建立 Python 版数据库映射边界

输出：

- `packages/database/schema/`
- `packages/database/clients/`
- `packages/database/queries/`
- `packages/database/migrations/`

验收：

- 能清楚区分 schema 映射、连接管理、查询层和迁移层职责
- 明确哪些表属于 上游参考实现 业务表，哪些新增表只允许是基础设施表

验收 demo：

- Demo 1：展示 `packages/database/` 目录结构，确认 schema、clients、queries、migrations 职责分离
- Demo 2：选取 1 到 2 个 上游参考实现 业务表，展示 Python 映射定义，并说明字段如何对应 上游参考实现
- Demo 3：展示数据库客户端初始化方式和 session / transaction 入口
- Demo 4：展示一条最小查询路径，从 query 层到 service 消费点的调用关系
- 用户确认点：数据库边界是否足够稳定，是否允许进入 ownership 与 read API 阶段

分工：

- A：主导 schema 映射、查询边界和兼容性盘点
- B：接入数据库客户端与查询层，为后续 service 使用打通路径

建议命令：

```powershell
Get-ChildItem -Recurse packages\database
uv run pytest server/tests -q
uv run pytest tests/contract -q
```

### Step 5. Ownership 与最小内部能力

目标：

- 先把 organization ownership 作为底层边界建立起来

输出：

- ownership 校验服务
- 最小内部接口
- 后台任务 ownership 过滤约束

验收：

- 请求入口和后台任务都能明确体现 organization scope / ownership 检查

验收 demo：

- Demo 1：演示一个属于当前 pod 的 organization 请求成功，展示校验路径和返回结果
- Demo 2：演示一个不属于当前 pod 的 organization 请求被拒绝，展示错误语义和拒绝位置
- Demo 3：演示后台任务执行前先筛 organization ownership，而不是先扫全库后末尾判断
- Demo 4：展示 ownership 相关测试断言，确认正确 pod、错误 pod、失效 lease 的处理语义
- 用户确认点：ownership 边界是否足够可靠，是否允许进入第一批 read API 实现

分工：

- A：定义 ownership 规则、拒绝语义和测试断言
- B：实现 ownership 校验链路和后台任务过滤逻辑

建议命令：

```powershell
uv run pytest tests/ownership -q
```

接口示例：

- 选择带 organization 语义的 上游参考实现 已有接口进行验证，例如：
  - `GET /api/issues?organizationId=<owned-org-id>`
  - `GET /api/issues?organizationId=<foreign-org-id>`

验收调用示例：

```powershell
curl "http://127.0.0.1:8000/api/issues?organizationId=org-owned"
curl "http://127.0.0.1:8000/api/issues?organizationId=org-foreign"
```

### Step 6. Read API

目标：

- 优先实现只读接口，尽早发现契约差异

输出：

- 第一批只读 route 和 service
- 与 上游参考实现 对照的 read contract 测试

验收：

- 能对照 上游参考实现 响应结构检查字段、nullability、默认行为

验收 demo：

- Demo 1：选取 1 到 2 个只读接口做实际调用，展示请求方式和响应结果
- Demo 2：逐字段对照 上游参考实现 返回结构，展示字段名、nullability、默认值和排序/过滤行为是否一致
- Demo 3：展示 read contract 测试或响应断言结果，确认兼容判断不是人工主观描述
- Demo 4：说明 route、service、query、shared contract 在这些只读接口中的协作关系
- 用户确认点：只读接口兼容性是否达标，是否允许进入 mutation workflow

分工：

- A：主导 read API 对照、字段和 nullability 验证
- B：主导 read route 和 service 实现

建议命令：

```powershell
uv run pytest tests/contract -q
```

接口示例：

- `GET /api/orgs`
- `GET /api/issues`
- `GET /api/chats`
- 具体以 上游参考实现 对应阶段已完成的接口为准

验收调用示例：

```powershell
curl http://127.0.0.1:8000/api/orgs
curl http://127.0.0.1:8000/api/issues
```

### Step 7. 组织管理

目标：

- 把 `organizations` 从基础列表 / 详情推进到完整组织管理能力
- 显性补齐组织创建、组织更新、组织设置类字段和组织范围规则

范围：

- organization 列表、详情、创建、更新
- organization 级配置字段、品牌字段、预算字段
- organization-scoped 排序、过滤、分页和 board access 语义

验收：

- 组织管理可独立演示
- 组织字段、默认值、拒绝语义与 上游参考实现 一致

验收 demo：

- Demo 1：演示 organization 列表与详情读取
- Demo 2：演示 organization 创建与配置字段初始化
- Demo 3：演示 organization board access 边界和错误语义
- Demo 4：演示 organization 更新与 contract / workflow 测试结果

分工：

- A：主导组织字段、默认值、board access 语义和兼容断言
- B：主导 route、service、workflow 和持久化实现

建议命令：

```powershell
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
```

### Step 8. 任务管理

目标：

- 把 `issues / issue_comments` 从首批读取与基础写入推进到完整任务管理面
- 补齐评论、状态流转、关联对象读取和常见过滤能力

范围：

- issue 列表、详情、创建、更新
- issue comments
- issue 状态流转
- issue 与 project、goal、agent、origin 的关联

验收：

- 任务管理可独立演示
- 状态流转、事务边界、副作用时机与 上游参考实现 一致

验收 demo：

- Demo 1：演示 issue 创建、更新和状态流转
- Demo 2：演示 issue comment 写入与读取
- Demo 3：演示 issue 与 project / goal / agent 的关联
- Demo 4：展示 workflow 测试结果

建议命令：

```powershell
uv run pytest tests/workflows -q
uv run pytest tests/contract -q
```

### Step 9. 审批管理

目标：

- 把 `approvals` 从首批读取与基础写入推进到完整审批管理面
- 补齐批准、拒绝、payload 处理和审批副作用

范围：

- approval 列表、详情、创建
- approval 批准 / 拒绝
- payload 脱敏与 decision note
- 审批与任务、组织、智能体的关联行为

验收：

- 审批管理可独立演示
- 审批拒绝语义、payload 处理和副作用与 上游参考实现 一致

验收 demo：

- Demo 1：演示 approval 创建、批准、拒绝
- Demo 2：演示 payload 处理与 decision note
- Demo 3：演示审批相关副作用与错误分支
- Demo 4：展示 workflow 测试结果

建议命令：

```powershell
uv run pytest tests/workflows -q
uv run pytest tests/contract -q
```

### Step 10. 项目、目标与智能体管理

目标：

- 补齐 `projects / goals / agents` 三条核心控制面主对象
- 明确它们与 organization、issue、run 的关系

范围：

- project 列表、详情、创建、更新、状态
- goal 列表、详情、创建、更新、推进
- agent 列表、详情、创建、配置、启停和绑定

验收：

- 项目管理、目标管理、智能体管理都可独立演示
- 字段、状态、对象关系与 上游参考实现 一致

验收 demo：

- Demo 1：演示 project / goal 管理流程
- Demo 2：演示 agent 创建、配置、绑定流程
- Demo 3：展示 project / goal / agent 与 issue 的关系
- Demo 4：展示 contract / workflow 测试结果

分工：

- A：主导 project / goal / agent 契约和对象关系对照
- B：主导 route、service、workflow 和持久化实现

建议命令：

```powershell
uv run pytest tests/workflows -q
uv run pytest tests/contract -q
```

### Step 11. 运行、心跳运行与工作区

目标：

- 补齐 `heartbeat_runs`、runtime orchestration、workspace lifecycle
- 明确执行对象如何从控制面请求进入 runtime，再落回数据库和产物 / 活动体系

范围：

- heartbeat run 创建、查询、状态推进
- runtime orchestration
- workspace 分配、占用、释放、失败恢复
- run 与 issue、agent、goal、project 的关联关系

验收：

- 运行、心跳运行、工作区主链路可独立演示
- runtime 和 workspace 不再只是预留结构，而是完整执行面能力

验收 demo：

- Demo 1：演示 heartbeat run 创建和状态推进
- Demo 2：演示 runtime 调度和结果归一化
- Demo 3：演示 workspace 分配、释放和失败恢复
- Demo 4：展示 workflow 测试结果

分工：

- A：主导 runtime / workspace 边界和兼容断言
- B：主导 runtime 接入、workspace orchestration 和 workflow 实现

建议命令：

```powershell
uv run pytest tests/workflows -q
uv run pytest tests/contract -q
```

### Step 12. 聊天、附件、产物与对象存储

目标：

- 补齐 chat、attachment、artifact、generated file 与对象存储边界
- 把 `server/storage/` 从结构预留推进到真实业务能力

范围：

- chats / messages / convert-to-issue / context links
- chat attachments
- artifacts / generated files
- storage adapters

验收：

- 聊天协作链路、附件与对象存储链路可独立演示
- storage 边界清晰，不把附件或产物逻辑散落到无关层里

验收 demo：

- Demo 1：演示最小 chat 会话、消息写入与 convert-to-issue
- Demo 2：演示 attachment / artifact 的持久化与读取
- Demo 3：展示 chat、run、workspace 与 storage 的交叉关系
- Demo 4：展示 contract / workflow 测试结果

分工：

- A：主导 chat 契约、storage 边界和兼容断言
- B：主导 chat 实现、storage adapter 和相关 workflow 实现

建议命令：

```powershell
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
```

### Step 13. 技能、插件与智能体资源封装

目标：

- 补齐 `server/resources/skills/bundled/`、`server/resources/plugins/` 与智能体资源绑定
- 明确 skill / plugin 的 metadata、扫描、注册、启用和绑定规则

范围：

- bundled skills
- plugins
- agent resource bindings

验收：

- 技能资源、插件资源、智能体资源封装都可独立演示
- 不再只停留在目录预留或设计注释

验收 demo：

- Demo 1：演示 skill 扫描与 metadata 装配
- Demo 2：演示 plugin 扫描、注册与启用
- Demo 3：演示 agent resource binding 路径
- Demo 4：展示相关测试结果

分工：

- A：主导 skill / plugin / resource 语义对照
- B：主导资源扫描、装配和绑定实现

建议命令：

```powershell
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
```

### Step 14. 配置、上下文、预算 / 成本 / 活动治理

目标：

- 将配置、上下文、预算 / 成本 / 活动治理收口
- 给后续可观测性、恢复和兼容差异比对提供统一入口

范围：

- `server/config.py` 统一配置模型
- proxy context / actor context 注入与消费
- budget / cost / activity 归集与治理

验收：

- 配置、上下文、治理形成统一系统边界
- 横切规则不再散落在各业务模块里

验收 demo：

- Demo 1：演示配置模型覆盖 database / storage / runtime / workspace
- Demo 2：演示 proxy / actor context 参与请求或后台任务
- Demo 3：演示 budget / cost / activity 的统一归集方式
- Demo 4：展示相关测试结果

分工：

- A：主导配置模型、上下文语义、治理规则和兼容断言
- B：主导配置落地和治理实现

建议命令：

```powershell
uv run pytest tests/contract -q
uv run pyright
```

### Step 15. 可观测性、恢复能力与兼容差异比对

目标：

- 补齐 observability、recovery、failover、compatibility diff
- 让多 pod、ownership、runtime、workspace、storage 的复杂链路具备稳定回归基础

范围：

- `server/observability/`
- recovery / failover 逻辑
- compatibility diff 与回归测试工具

验收：

- wrong-route、wrong-pod、lease 失效、workspace / runtime / storage 故障路径都有验证
- 兼容差异比对和回归测试可持续支撑后续迭代

验收 demo：

- Demo 1：演示日志、指标、追踪
- Demo 2：演示 failover、lease 失效和恢复行为
- Demo 3：演示 compatibility diff 与关键回归测试
- Demo 4：展示系统是否达到稳定扩展基线

分工：

- A：主导兼容 diff、风险审计和回归口径
- B：主导观测、恢复逻辑和故障路径实现

建议命令：

```powershell
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
uv run pytest tests/ownership -q
uv run pyright
```

## 8. 验收标准

每个阶段都必须同时满足以下验收标准：

- 实现边界与 `docs/DESIGN.md` 一致
- 不破坏 上游参考实现 兼容目标
- 目录和分层职责清晰
- 代码组织符合项目规范中的内聚、封装、可扩展要求
- 测试能验证本阶段最关键的契约或工作流
- 结果先由用户确认，再决定是否提交
- 必须能提供与本阶段目标直接对应的验收 demo

## 9. 验收方法

每阶段完成后至少做以下检查：

- 文档与实现是否一致
- 目录和职责是否清晰
- 是否引入了与阶段目标无关的实现
- 是否把临时写法固化成长期结构
- 是否具备对应层级的测试或验证手段
- 是否已经准备好可以直接向用户展示的验收 demo

统一本地校验顺序：

```powershell
ruff check . --fix
ruff format .
pytest
pyright
```

执行规则：

- 默认按上述顺序执行，不自行调整先后
- 如果当前阶段只适合执行局部测试或局部类型检查，必须在验收汇报里明确写出实际执行范围
- 若其中某一步因环境、依赖或阶段范围暂时无法执行，也必须在验收汇报里说明未执行原因

在技术层面，后续应逐步建立：

- 静态检查
- 类型检查
- 契约兼容测试
- 工作流测试
- ownership 安全测试

执行模式检查：

- 当前阶段的契约边界是否已经冻结
- 实现是否只在既定边界内推进
- 是否存在共享契约源文件和实现代码一起漂移的风险
- 阶段演示是否同时覆盖契约验证和功能演示
- 准备合并时是否已按“文档先收口、实现后提交”的顺序执行
- 实现分支在合并前是否已经同步最新 `main`
- 冲突处理是否经过 上游参考实现 对照，而不是直接本地拍平

## 10. 当前约束与风险

当前最主要的约束和风险包括：

- 上游参考实现 的真实行为可能比设计文档更复杂，后续必须持续对照源码
- 如果过早写业务实现，容易在目录和职责层面返工
- 如果 ownership 边界不先建立，后续后台任务和 mutation 逻辑容易越权
- 如果共享契约层不先建立，API shape 很容易在不同模块间漂移
- 如果为了赶进度引入临时结构，后续会直接形成技术债

## 11. 当前结论

当前开发计划的核心结论是：

- 先把基础做稳
- 先把边界做清楚
- 先把兼容验证路径铺好
- 再按从易验证到难验证的顺序推进功能实现

Octopus 的正确推进方式不是“先做一版能跑”，而是“先做一版不会把项目带偏的基础”，再逐步替换 上游控制面服务端能力。


