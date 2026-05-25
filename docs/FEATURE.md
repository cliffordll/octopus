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
- 步骤目录统一按 `docs/step-01/` 到 `docs/step-10/` 命名，与本文件中的 `Step 1` 到 `Step 10` 直接对应
- `docs/step-01/` 只放 Step 1 的执行记录
- `docs/step-02/` 只放 Step 2 的执行记录
- 从 `docs/step-03/` 开始，每个步骤目录都必须先有 A 提供给 B 的 `A-CONSTRAINTS.md`
- `docs/step-03/` 放 Shared Contract 层文档
- `docs/step-04/` 到 `docs/step-10/` 分别放对应步骤的 A 约束文档与专项盘点文档
- 在 B 完成 `Step 3` 之前，`docs/step-04/` 到 `docs/step-10/` 的 `A-CONSTRAINTS.md` 默认只保留草稿版本，不提前冻结字段级和行为级细节
- B 的执行文档只在对应步骤已经有 A 约束输入后才允许补充，不允许先有 B 的实现再倒推 A 的约束

当前步骤文档归档：

- `docs/step-01/BASELINE-CLEANUP.md`
- `docs/step-02/SERVER-SKELETON.md`
- `docs/step-03/A-CONSTRAINTS.md`
- `docs/step-04/A-CONSTRAINTS.md`
- `docs/step-04/SCHEMA-COMPATIBILITY.md`
- `docs/step-05/A-CONSTRAINTS.md`
- `docs/step-06/A-CONSTRAINTS.md`
- `docs/step-07/A-CONSTRAINTS.md`
- `docs/step-07/WORKFLOW-NOTES.md`
- `docs/step-08/A-CONSTRAINTS.md`
- `docs/step-09/A-CONSTRAINTS.md`
- `docs/step-10/A-CONSTRAINTS.md`

## 2.1 双人开发分工

当前项目按两条主线并行推进：

- 开发者 A：负责契约与基础边界
- 开发者 B：负责服务端实现与运行骨架

开发者 A 的职责：

- 对照 `上游参考仓库路径` 盘点 API、schema、枚举、状态流转和副作用
- 维护 `packages/shared/` 的 path、types、validators 和共享常量边界
- 维护 `packages/database/` 的 schema 映射边界和查询边界
- 维护兼容测试基线
- 对“是否仍然 上游参考实现 兼容”给出判断

开发者 B 的职责：

- 落地 `server/` 的 app、config、lifespan、routes、services、background
- 接入 A 已经固定的 shared contract 和 database 边界
- 实现 read API、mutation workflow、runtime orchestration
- 准备每一阶段的功能验收 demo
- 默认不主改契约文档，只消费已经冻结的契约清单执行开发任务

协作原则：

- A 优先定义契约和边界，B 基于边界实现
- 每个阶段只允许一人主改契约源文件，避免双向漂移
- 兼容测试和契约判断优先于局部功能速度
- 阶段验收时同时展示兼容验证结果和功能 demo
- B 如果发现契约缺口或契约与 上游参考实现 不一致，先反馈 A 更新契约文档，再继续实现

## 2.2 双人分支与合并策略

双人开发默认采用“契约先合、实现后合”的顺序。

分支建议：

- `main`：只保留已验收内容
- A 使用契约分支，例如 `feat/contracts-phase-x`
- B 使用实现分支，例如 `feat/server-phase-x`

合并顺序：

1. A 先完成 shared contract、database 边界、兼容测试基线或文档更新
2. A 的阶段成果经用户验收后先合入 `main`
3. B 将最新 `main` 同步到实现分支
4. B 再继续 server / workflow / runtime 实现，并在阶段完成后合入 `main`

同步原则：

- 若实现分支仅个人使用，优先 `rebase main`
- 若分支已多人共享，改用 merge
- 若 A 更新了契约边界，B 必须先同步再继续开发

冲突处理：

- 契约冲突由 A 基于 上游参考实现 对照结果裁定
- 实现冲突由 B 处理，但不得突破已合入主干的契约边界
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
- Demo 4：展示 `CLAUDE.md` 关键章节，确认项目约束、双人协作规范和提交流程已经固定
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

- `server/src/app.py`
- `server/src/config.py`
- `server/src/lifespan.py`
- `server/src/routes/`
- `server/src/services/`

验收：

- 可以启动最小服务入口
- 至少具备一个与 上游参考实现 接口命名约束不冲突的最小服务启动验证链路

验收 demo：

- Demo 1：展示 `server/src/app.py`、`config.py`、`lifespan.py`、`routes/`、`services/` 的最小文件结构
- Demo 2：启动最小服务端进程，展示应用已完成配置加载、应用创建和路由注册
- Demo 3：调用一个与 上游参考实现 接口命名约束不冲突的最小验证入口，展示返回结果
- Demo 4：说明当前服务端骨架中 route、service、config、lifespan 的职责边界
- 用户确认点：服务端骨架是否符合设计文档，是否允许进入共享契约层建设

分工：

- A：约束路由命名、共享依赖注入方式和契约边界
- B：主导 `server/` 骨架实现和最小启动链路

建议命令：

```powershell
uv run uvicorn server.src.app:app --host 127.0.0.1 --port 8000
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

- `packages/shared/src/constants/`
- `packages/shared/src/types/`
- `packages/shared/src/validators/`
- `packages/shared/src/api_paths/`

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

- `packages/database/src/schema/`
- `packages/database/src/clients/`
- `packages/database/src/queries/`
- `packages/database/src/migrations/`

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

### Step 7. Mutation Workflow

目标：

- 实现核心控制面 mutation 语义

优先顺序：

1. issue
2. approval
3. activity
4. run 相关基础状态流转

验收：

- 状态流转、事务边界、副作用时机与 上游参考实现 一致

验收 demo：

- Demo 1：演示一个完整 mutation 流程，例如 issue 创建、状态变化、审批或评论等关键步骤
- Demo 2：展示相关 activity、状态变更记录或其它关键副作用已经按预期落地
- Demo 3：展示关键错误分支，例如非法状态流转被拒绝，确认错误码与错误语义符合预期
- Demo 4：展示对应工作流测试结果，证明不是只在手工 happy path 下可用
- 用户确认点：核心控制面 mutation 是否达标，是否允许进入 runtime orchestration

分工：

- A：主导状态机、副作用、错误码和事务边界对照
- B：主导 issue、approval、activity、run 基础 mutation 实现

建议命令：

```powershell
uv run pytest tests/workflows -q
```

接口示例：

- `POST /api/issues`
- `POST /api/approvals`
- `POST /api/issues/{issueId}/comments`
- 具体路径、字段名、响应结构必须逐项对齐 上游参考实现

验收调用示例：

```powershell
curl -X POST http://127.0.0.1:8000/api/issues -H "Content-Type: application/json" -d '{"organizationId":"org-1","title":"Demo issue"}'
curl -X POST http://127.0.0.1:8000/api/approvals -H "Content-Type: application/json" -d '{"organizationId":"org-1","issueId":"issue-1"}'
```

### Step 8. Runtime Orchestration

目标：

- 建立 runtimes 适配和运行编排基础

输出：

- `packages/runtimes/shared/`
- 各 runtime 包最小 server 适配层
- run 状态与结果归一化边界

验收：

- server 与 runtime 的职责边界清楚
- runtime 差异不会污染业务语义层

验收 demo：

- Demo 1：演示 server 如何通过统一 contract 调用某个 runtime，而不是写死某个实现
- Demo 2：展示 runtime 返回结果如何归一化到 shared result / transcript 边界
- Demo 3：展示替换或新增 runtime 时，业务 service 不需要跟着改语义层代码的证据
- Demo 4：展示 runtime 相关测试或伪实现注入方式，确认该层具备扩展性
- 用户确认点：runtime 编排边界是否稳定，是否允许进入 chat compatibility

分工：

- A：主导 runtime contract、结果归一化和兼容断言
- B：主导 runtimes 接入和 orchestration 实现

建议命令：

```powershell
uv run pytest server/tests/test_services -q
uv run pytest tests/workflows -q
```

### Step 9. Chat Compatibility

目标：

- 最后处理 chat 兼容实现

原因：

- chat 是兼容风险最高、对象关系最多、状态最复杂的一层

验收：

- conversation、message、attachment、context link、convert-to-issue 等核心能力与 上游参考实现 对齐

验收 demo：

- Demo 1：演示一次最小 chat 会话创建、消息写入和消息流转
- Demo 2：演示一次关键动作，例如 chat 转 issue、context link 处理或 attachment 关联
- Demo 3：对照 上游参考实现 展示消息顺序、字段结构和关键状态语义的一致性
- Demo 4：展示 chat 相关契约测试或工作流测试结果
- 用户确认点：chat 兼容性是否达标，是否允许进入 hardening

分工：

- A：主导 chat 契约、字段、顺序和状态语义对照
- B：主导 chat 实现和相关工作流打通

建议命令：

```powershell
uv run pytest tests/workflows -q
uv run pytest tests/contract -q
```

接口示例：

- `GET /api/chats`
- `POST /api/chats`
- `POST /api/chats/{chatId}/messages`
- `POST /api/chats/{chatId}/convert-to-issue`

验收调用示例：

```powershell
curl -X POST http://127.0.0.1:8000/api/chats -H "Content-Type: application/json" -d '{"organizationId":"org-1","title":"Demo chat"}'
curl -X POST http://127.0.0.1:8000/api/chats/chat-1/messages -H "Content-Type: application/json" -d '{"content":"hello"}'
```

### Step 10. Hardening

目标：

- 补齐 failover、安全性、恢复性和兼容 diff 工具

验收：

- ownership 错路由防护明确
- 后台任务不会越权处理
- 关键工作流具备稳定回归验证

验收 demo：

- Demo 1：演示错误路由或错误 pod 请求被拒绝
- Demo 2：演示 failover、lease 失效或恢复逻辑相关保护行为
- Demo 3：展示后台任务不会越权处理非本 pod organization 的证据
- Demo 4：展示关键测试集合、执行结果和覆盖范围说明
- 用户确认点：系统是否达到可持续迭代和稳定扩展的基线

分工：

- A：主导兼容 diff、回归测试集和风险审计
- B：主导 hardening 实现、恢复逻辑和可观测性补强

建议命令：

```powershell
uv run pytest tests/contract -q
uv run pytest tests/workflows -q
uv run pytest tests/ownership -q
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

双人协作检查：

- A 是否已经冻结当前阶段的契约边界
- B 是否只在既定边界内推进实现
- 是否存在两人同时改同一类契约源文件的风险
- 阶段演示是否同时覆盖契约验证和功能演示
- 准备合并时是否已按“契约先合、实现后合”的顺序执行
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

