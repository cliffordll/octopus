# Octopus 项目规范

本文件定义 Octopus 仓库内需要长期保留的项目规范。所有规范都以 上游控制面服务端的 Python 兼容式重写为中心，不保留其它项目的历史约定。

## 项目定位

- Octopus 是 上游控制面服务端的 Python 兼容替代实现，不是新产品
- 外部契约来源于 上游参考实现 现有 schema、API 和控制面语义，不来源于个人编码习惯
- 设计文档以 `docs/DESIGN.md` 为准
- 对照实现以 `上游参考仓库路径` 为准

## 核心约束

- 项目内普通文档、注释、命名和说明禁止把上游项目名作为 Octopus 自身产品名使用，应统一使用功能语义名称，例如组织管理、问题流转、审批流程、运行编排、预算控制、组织树、技能管理
- 已确认属于上游兼容契约的字符串不得为命名清理而擅自改动，例如 runtime env、workspace context、provider 枚举、测试 fixture 中用于兼容验证的 `OCTOPUS_*`、`upstream-referenceWorkspace` 等；若要替换，必须先确认上游契约已变化并同步 shared contract 与测试
- 保持 上游参考实现 现有数据库业务表结构不变
- 保持 上游参考实现 现有 API 路径、请求结构、响应结构不变
- 保持 上游参考实现 枚举值、状态值、错误码语义和关键副作用时机不变
- 保留上游 `server` 已有的 run、runtime、workspace、恢复和运行记录等执行语义
- organization 是业务作用域；请求、后台任务和执行流程不得跨组织读写
- 不将上游不存在的新业务前置条件或基础设施架构引入兼容实现
- 在兼容重写过程中，架构设计必须优先考虑长期可扩展性，不能以临时拼接方式换取短期推进
- 每次功能开发完毕后，必须先由用户确认结果；只有在用户下达明确 `commit` 指令后，才能执行提交

## 目录规范

- 仓库结构尽量参考 上游参考实现，优先保留 `server/`、`packages/`、`tests/`、`docs/`、`ui/` 这些边界
- `server/` 是 Python 服务端主实现，负责路由、service、background、middleware、storage、observability
- `packages/database/` 负责 schema 映射、数据库客户端、查询和迁移
- `packages/shared/` 负责 API 路径、枚举、契约模型、validator、共享常量
- `packages/runtimes/` 负责各 runtime 的适配实现和共享 runtime contract
- `packages/runtimes/` 的 Python 目录名使用下划线，例如 `claude_local/`；但对外兼容的 runtime id、配置值和持久化语义保持横杠命名，例如 `claude-local`
- `server/skills/bundled/` 这类资源目录不是 Python 包；其中具体 skill 目录名和 skill id 继续保持上游横杠命名，例如 `conversation-to-skill`
- `tests/` 以兼容测试、工作流测试、scope 与并发测试为主
- `docs/` 只保留与架构、兼容性、迁移计划相关的文档
- `docs/` 下的规划类文档保留在根目录；步骤文档使用 `docs/step-NN-<scope>/` 目录，`<scope>` 为简短英文功能后缀，例如 `docs/step-06-orgs/`、`docs/step-13-runs/`
- Step 开发分支统一使用 `step-<number>-<scope>` 命名，`<scope>` 为当前分支交付的简短英文后缀，例如 `step-10-projects`、`step-12-ui-cli`；不再添加 `feat/`、`contracts-` 等重复前缀
- 步骤目录及职责以 `docs/FEATURE.md` 的映射表为准；每个步骤只承载一个主要交付对象
- 已完成步骤必须在 `TASK.md` 中保留可追溯的实施记录，包括范围、修改位置、关键行为、验收证据和已知边界
- 待开发步骤以 `TASK.md` 作为入口；进入开发后可按复杂度在同一目录拆分 `SPEC.md`、`PLAN.md`、`NOTES.md` 等执行文档
- 已实施步骤的任务记录随新的步骤职责归档，不保留无职责含义的纯编号目录或重复表达同一内容的旧文档

## 编码规范

- 所有实现以 上游参考实现 兼容性为第一优先级，不按个人 Python 偏好改动 API、schema、状态值和副作用语义
- 编码实现优先内聚，优先把同一领域状态、规则和行为收敛到稳定的模块或类型中，避免语义分散
- 优先考虑封装，不把核心流程拆成大量松散的临时 helper 或跨层共享的杂项函数
- 设计扩展点时优先使用清晰的抽象边界，例如领域服务、runtime 适配接口、仓储边界、基础类和实现类分层
- 当存在稳定的父子语义或多实现分支时，优先使用继承、接口约束或组合后的统一抽象，不写难以演进的分支堆叠逻辑
- 新实现默认按可扩展架构落地，要求后续新增 organization 策略、runtime、后台任务或业务对象时可以在既有边界内扩展
- 不接受“先堆功能、以后再重构”的路径；如果当前写法会形成明确技术债，应在实现时直接收敛到可维护结构
- 命名统一使用功能语义名称，不把上游项目名写进代码、文档、变量、模块说明或验收材料
- 命名优先贴近 上游参考实现 领域对象，例如 `organizations`、`issues`、`approvals`、`heartbeat_runs`、`chat_conversations`
- 不发明新的产品概念替代 上游参考实现 既有对象；如果只是语言迁移，应复用既有领域边界
- `server/routes/` 只处理路由注册、参数解析、validator 调用、context 注入和响应组装，不承载复杂业务流程
- `server/services/` 承载 上游参考实现 控制面语义，包括状态流转、事务边界、activity 副作用、runtime 调用、workspace 流程和执行一致性校验
- `server/background/` 中的任务必须显式携带 organization scope，再处理 issue、chat、run、budget 等对象
- `packages/database/schema/` 优先只做 上游参考实现 现有表的 Python 映射；确需增加的 Python 基础设施表必须单独论证且不得改变业务契约，例如 idempotency 或 outbox
- `packages/database/queries/` 或等价持久化层只负责查询与写入细节，不定义审批、issue、chat、run 的业务语义
- `packages/shared/` 统一承载 API path、枚举、请求响应模型和 validator，避免这些契约散落到 route、service 或测试里
- `packages/runtimes/` 按 runtime 分目录实现适配，保留 shared contract，不把所有 runtime 差异揉进一个大模块
- runtime 的 Python 包路径与外部兼容标识必须分离处理，不允许在业务代码、配置解析、数据库字段或接口返回里临时用字符串替换推导 `-` 和 `_`
- skill 资源目录名和 skill id 视为外部兼容语义，不做 `_` 化；如果后续代码需要 Python 合法标识，必须额外建显式映射，不能改 skill 目录名本身
- organization 是第一层隔离边界；任何请求、后台任务、恢复逻辑、扫描逻辑都不能越过 organization scope

## 测试规范

- 优先写契约兼容测试，而不是只写脱离场景的零散单测
- 重点验证 API shape、字段 nullability、枚举字符串、错误码和默认行为是否与 上游参考实现 一致
- 工作流测试至少覆盖 issue、approval、run、budget、chat 等关键控制面流程
- scope 测试必须覆盖跨 organization 读写拒绝、actor 边界和新建 organization 的可用流程
- 执行面测试必须覆盖上游已纳入范围的 run claim、checkout、runtime、workspace、失败恢复和重复副作用防护
- 任何代码修改默认都必须把“符合仓库标准”视为实现完成条件的一部分，不接受“先改通功能，后补规范”式交付
- 默认交付标准是同时满足：功能正确、分层实现符合仓库规范、对应测试补齐、四步验证一次全绿
- 如果四步验证暴露的是仓库级配置或工具链问题，也视为当前改动的一部分，必须在同一轮内直接修掉
- 更新依赖、锁文件、工具链或本地环境版本后，也必须执行同一套四步验证，不能只验证被更新的单个工具
- 修复 lint 或格式问题时可执行 `uv run ruff check . --fix` 和 `uv run ruff format .`；这些会修改文件，不能替代交付验证结果
- 默认本地交付验证顺序固定为：
  1. `uv run ruff check .`
  2. `uv run ruff format --check .`
  3. `uv run pytest`
  4. `uv run pyright .`
- 如果某一步因当前阶段范围需要缩小执行面，必须在汇报中明确说明缩小原因和实际执行的命令范围

## 提交流程

- 每次功能开发、重构或清理完成后，先汇报改动结果、影响范围和验证情况，保持未提交状态
- 用户确认功能结果之前，不得自行执行 `git commit`
- 只有在用户明确下达 `commit`、`提交` 等提交指令后，才能创建提交
- 用户对功能结果的普通确认、讨论结论或测试通过，不等同于提交授权
- 未经用户明确授权，不得切换分支
- 所有提交、文档、注释、计划说明和后续协作文案都必须模拟真实开发者产出，禁止出现任何 AI 辅助、自动生成、模型参与、工具代写等痕迹
- commit message、文档内容、代码注释、PR 文案和说明文字都必须保持正常人工开发风格，不得加入 AI 署名或来源说明

## 协作与文档规范

- `docs/FEATURE.md` 定义实施顺序和每个步骤的主要交付对象，步骤文档不得自行扩展职责边界
- 已完成步骤的 `TASK.md` 必须足以解释该步实际实现；待开发步骤可以在执行期按任务复杂度拆分附属文档，但不得重复 `FEATURE.md` 或 `DESIGN.md` 的整体职责
- 实现过程中发现契约缺口、歧义或与 上游参考实现 不一致时，先以证据修正文档和契约边界，再继续代码实现
- `packages/shared/`、`packages/database/schema/` 和兼容测试基线属于契约源；对这些文件的修改必须同步对照依据与测试
- 步骤重排时，先更新 `docs/FEATURE.md` 的映射，再将已有文档迁移到职责匹配的带后缀目录
- 阶段验收必须同时覆盖契约验证和功能流程，不能只验证服务可运行

## 合并规范

- `main` 只接收已经完成阶段验收并得到用户确认的内容
- 未经用户明确授权，不得将任何分支代码 merge 到 `main`
- 如果冲突涉及 API shape、schema、状态值或副作用语义，先对照 上游参考实现，不允许凭推断合并
- 每次准备合并前，检查文档、shared/database 边界、server 实现和测试结果是否一致
- 合并到 `main` 之前，仍然必须先由用户确认结果，并收到明确的 `commit` 或等价指令

## 非目标

- 不实现与当前服务端兼容目标无关的客户端、打包或外围工具能力
- 不发明上游不存在的 organization 执行前置条件、业务表或状态机
- 不在未完成上游对照前重建或删改认证、授权与 actor 语义
- 不为了“更 Pythonic”而重构 上游参考实现 的产品模型或业务表
- 不保留与旧项目、旧技术栈、旧协作方式相关的历史说明

## 清理原则

- 保留与 上游参考实现 Python 化改造直接相关的文件和目录
- 删除 Node workspace、Tauri、旧项目协作文档、与兼容重写无关的历史文件
- 如果某个文件未来可能服务于 Octopus 的兼容实现，可以保留并重写；否则直接删除
