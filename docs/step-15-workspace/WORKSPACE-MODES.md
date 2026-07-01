# 项目工作区与执行工作区模式语义

状态：草案
日期：2026-07-01
职责归属：Step 15 Workspace

## 1. 为什么需要这份文档

Octopus 里容易混淆的不是“三个模式叫什么”，而是这些对象分别承担什么职责。正确的决策顺序必须是：

```text
先确定项目主工作区 / 代码来源
  -> 再选择任务执行策略
  -> 再为运行时提供组织级、智能体级和产物目录
```

如果没有项目主工作区或代码来源，`shared_workspace`、`isolated_workspace`、`operator_branch` 这三种“项目执行策略”都没有完整语义。系统可以给 agent 一个组织级 scratch cwd，但它不能被解释成项目代码工作区。

核心对象：

- 项目主工作区：项目代码来源和主现场，可以是本地 `cwd`，也可以是 `repoUrl` 创建出的 managed checkout。
- 执行工作区 cwd：runtime/agent 真正进入并修改代码的目录，对应 `OCTOPUS_WORKSPACE_CWD`。
- 执行策略：从项目主工作区复用或派生执行 cwd 的方式，即 `shared_workspace`、`isolated_workspace`、`operator_branch`。
- 组织级工作区：organization 范围的运行时文件根目录，用于 artifacts、plans、skills、agents、managed checkout 父目录和无项目 scratch，不是项目代码目录。
- 智能体级工作区：agent 私有 scratch、memory、工具缓存和 session 辅助文件，不是项目代码目录。
- 任务产物目录：某个 issue/run 的截图、报告、日志、handoff 文件归档目录，对应 `OCTOPUS_ISSUE_ARTIFACTS_DIR`。
- Git 分支或 worktree：代码变更如何隔离、累积、review 和合并。
- 队列或 lease：多个任务是否可以同时写同一个执行 cwd。

关键规则：

> `OCTOPUS_WORKSPACE_CWD` 是执行目录；`OCTOPUS_ISSUE_ARTIFACTS_DIR` 是任务产物目录；组织级/智能体级 workspace 是运行时基础设施目录。三者不能混为一个概念。

如果 shared 模式下每个子任务都有独立执行 cwd，那么 shared 就退化成 isolated。对齐上游 upstream reference 后，shared 模式应明确为“直接使用项目主工作区 cwd”，不应再叠加“每个任务一个执行目录 + workspace 长锁 + workspace 队列”这套语义。

## 2. 决策模型

Preflight 不应只按 mode 分支。它必须先判断项目和代码来源是否存在，再决定执行策略能否成立。

### 2.1 第一层：代码来源 / 项目主工作区

| 输入场景 | 语义 | 允许的项目执行策略 | 默认处理 |
| --- | --- | --- | --- |
| issue 无 project | 无项目代码上下文 | 不进入三种项目执行策略 | organization scratch run，可用于文档/报告/轻量自动化 |
| project 无 project workspace 记录 | 项目没有代码来源 | 不应直接启用三种项目执行策略 | UI 提示先配置主工作区；后端可兼容旧 fallback，但必须给 warning |
| project workspace 无 `cwd`，有 `repoUrl` | 有远程代码来源，但本机未 checkout | 三种策略都可成立 | 创建 managed checkout，持久化为项目主工作区 cwd |
| project workspace 无 `cwd`，无 `repoUrl` | 项目工作区记录不完整 | 不应直接启用三种项目执行策略 | UI 标记为未配置代码来源；operator 必须失败 |
| project workspace 有 `cwd` | 有本地代码/文件来源 | shared 可成立；isolated 需要 Git repo；operator 需要 Git | 校验路径存在且可访问 |
| project workspace 有 `cwd` 且是 Git repo | 有本地 Git 来源 | 三种策略都可成立 | shared 使用当前 cwd；isolated/operator 可创建 worktree |

这一层的输出事实必须是：

- 是否有 project。
- 是否有项目主工作区。
- 主工作区来源是 `local cwd`、`managed checkout`、`repoUrl pending checkout`，还是 `none`。
- 主工作区是否是 Git repo。
- 是否允许选择三种项目执行策略。
- 如果不允许，是否允许 organization scratch run。

### 2.2 第二层：执行策略

只有当第一层确认存在项目主工作区或可创建 managed checkout 时，三种执行策略才是“项目执行策略”。

| 执行策略 | 需要的前置条件 | 执行 cwd | Git 语义 | 写并发规则 | 典型用途 |
| --- | --- | --- | --- | --- | --- |
| `shared_workspace` | 有项目主工作区 cwd，或有 repoUrl 可先创建 managed checkout | 项目主工作区 cwd | 使用当前工作树，不自动切换分支 | 不创建 workspace 级长锁；只保留 issue/agent/run 级并发控制 | 直接在用户当前项目目录或 managed checkout 上工作 |
| `isolated_workspace` | 有 Git 项目主工作区，或有 repoUrl 可先创建 managed checkout | 每个 issue 一个 Git worktree cwd | 每个 issue 一个固定分支和 worktree | 不同 issue 可并行；同一 issue 串行 | 多任务隔离、独立 review、方便丢弃 |
| `operator_branch` | 有 Git 项目主工作区 | 多个 issue 共用一个固定 operator worktree | 一组任务累积到同一个长期 feature/operator 分支 | 同一 operator cwd 写任务必须串行 | 一个大 feature 拆成多个子任务共同推进 |

### 2.3 第三层：运行时目录

运行时目录不决定项目执行策略，只给 agent 提供辅助存储。

| 目录 | 作用 | 是否是代码工作区 |
| --- | --- | --- |
| organization workspace root | 组织范围 scratch、artifacts/plans/skills/agents 根目录、managed checkout 父目录 | 否，除非明确进入 organization scratch run |
| agent workspace root | agent 私有 memory、scratch、工具缓存 | 否 |
| issue artifacts dir | issue/run 产物归档 | 否 |
| execution workspace cwd | agent 真正执行和修改代码的目录 | 是 |

### 2.4 Preflight 场景矩阵

| 输入场景 | `shared_workspace` | `isolated_workspace` | `operator_branch` |
| --- | --- | --- | --- |
| 无 project | 不进入项目 shared；可作为 organization scratch run | 不进入项目 isolated；可作为 organization scratch run | 不进入 operator；可作为 organization scratch run |
| 有 project，无 project workspace 记录 | UI 禁用三种策略并提示先配置主工作区；后端兼容时只能 warning fallback | UI 禁用 isolated，并提示先配置 Git cwd 或 repoUrl | preflight 失败 |
| 有 project workspace，无 `cwd`，有 `repoUrl` | 创建 managed checkout；cwd 指向 checkout | 创建 managed checkout；从 checkout 创建 issue worktree | 创建 managed checkout；从 checkout 创建固定 operator worktree |
| 有 project workspace，无 `cwd`，无 `repoUrl` | UI 标记“无代码来源”；不应作为正常 shared | UI 标记“无代码来源”；不应作为正常 isolated | preflight 失败 |
| 有 `cwd`，但路径不存在或不可访问 | preflight 失败 | preflight 失败 | preflight 失败 |
| 有 `cwd`，但不是 Git repo | 使用项目 cwd；`local_fs` | isolated 不成立；提示配置 Git repo 或 repoUrl | preflight 失败 |
| 有 `cwd`，且是 Git repo | 使用项目 cwd；不自动切分支；同 cwd 串行 | 创建或复用 issue Git worktree | 创建或复用固定 operator branch worktree |
| 已有 execution workspace | 优先复用，但校验 cwd/provider/mode | 优先复用，但校验 cwd/provider/branch/source | 优先复用同 operator branch workspace，并校验 cwd/provider/branch/source |

### 2.5 无 project

| 情况 | 处理 |
| --- | --- |
| issue 没有关联 project | 使用 organization scratch run，而不是项目 shared workspace |
| mode | 不进入三种 project execution strategy |
| provider | `local_fs` |
| `OCTOPUS_WORKSPACE_CWD` | `<OCTOPUS_HOME>\instances\<instanceId>\organizations\<orgId>\workspaces` |
| Git/worktree | 不创建 |
| 队列 | 按 organization scratch cwd 串行 |
| artifacts | 仍然按 issue 独立：`artifacts\issues\<issueId>` |

这个场景适合写报告、整理资料、生成文档、轻量自动化；不适合作为代码修改任务。需要修改代码时，应先关联 project 并配置项目主工作区或 repo。

### 2.6 有 project，但没有可用代码来源

包括：

- 没有 project workspace 记录。
- project workspace 有记录，但 `cwd` 和 `repoUrl` 都为空。

产品语义：

- UI 不应把这种状态展示成“将使用组织共享工作区”这种正常项目路径。
- UI 应展示为“未配置项目主工作区 / 无代码来源”。
- 三种项目执行策略应禁用或弱化展示，并提示先配置本地 cwd 或 repoUrl。
- 后端为了兼容旧数据可以 fallback 到 organization scratch run，但 response/context 必须携带 warning，并且不能把它命名为项目 shared workspace。

### 2.7 有 project workspace，无 `cwd`，但有 `repoUrl`

这是“repoUrl-only project workspace”：系统知道代码仓库在哪里，但本机还没有登记可执行本地目录。

示例：

```json
{
  "name": "Shop App",
  "cwd": null,
  "repoUrl": "https://github.com/acme/shop-app.git",
  "defaultRef": "main"
}
```

处理流程：

```text
repoUrl-only project workspace
  -> Octopus 创建 managed checkout
  -> 持久化 project_workspace.cwd
  -> 再按 shared / isolated / operator 继续解析
```

| mode | 处理 |
| --- | --- |
| `shared_workspace` | `OCTOPUS_WORKSPACE_CWD` 指向 managed checkout |
| `isolated_workspace` | 从 managed checkout 创建 issue worktree |
| `operator_branch` | 从 managed checkout 创建固定 operator branch worktree |

managed checkout 是 project workspace 的本地来源，不是 issue artifacts 目录。

当前 Octopus 默认把 managed checkout 放在组织级工作区下面：

```text
<OCTOPUS_HOME>\instances\<instanceId>\organizations\<orgId>\workspaces\projects\<projectId前8位>\checkout
```

例如 server 在 `D:\coding\octopus` 启动，并显式设置：

```powershell
$env:OCTOPUS_HOME = ".octopus"
```

默认 instance 为 `default` 时，路径形态是：

```text
D:\coding\octopus\.octopus\instances\default\organizations\<orgId>\workspaces\projects\<projectId前8位>\checkout
```

需要明确区分物理位置和逻辑角色：

| 对象 | 路径位置 | 逻辑角色 |
| --- | --- | --- |
| organization workspace root | `<OCTOPUS_HOME>\instances\<instanceId>\organizations\<orgId>\workspaces` | 组织级文件根目录 |
| managed checkout | `...\workspaces\projects\<projectId前8位>\checkout` | 项目主代码工作区，即 `project_workspaces.cwd` |
| organization scratch | organization workspace root 或其 scratch 子目录 | 无项目/无代码任务的临时执行位置 |
| issue artifacts | `...\workspaces\artifacts\issues\<issueId>` | 任务产物目录 |

因此，managed checkout 虽然物理上位于组织级工作区之下，但语义上是项目主工作区。UI/API 不能把它展示成 organization scratch，也不能把 organization workspace root 本身展示成项目 shared workspace。

### 2.8 有 `cwd`，但路径不存在或不可访问

默认应 preflight 失败，而不是静默 fallback。

原因：用户已经显式配置了本地路径，路径不存在通常表示配置错误、磁盘未挂载、权限错误或迁移遗漏。静默 fallback 可能让任务在错误目录中执行。

### 2.9 有 `cwd`，但不是 Git repo

| mode | 处理 |
| --- | --- |
| `shared_workspace` | 可以执行；`providerType=local_fs` 或 project primary local path |
| `isolated_workspace` | isolated 不成立；不能创建 fake `git_worktree`，也不能把普通 local_fs 目录包装成正常 isolated |
| `operator_branch` | preflight 失败 |

operator branch 必须有 Git 来源；否则 branch 语义不存在。

### 2.10 有 `cwd`，且是 Git repo

| mode | 处理 |
| --- | --- |
| `shared_workspace` | 使用项目主工作区 cwd，不自动切换分支 |
| `isolated_workspace` | 为 issue 创建或复用真实 Git worktree |
| `operator_branch` | 创建或复用固定 operator branch worktree |

### 2.11 已有 execution workspace

如果 issue 已绑定 execution workspace，preflight 应优先复用，但必须校验它仍然有效：

- `cwd` 存在且可访问。
- `providerType=git_worktree` 时，目录是真实 Git worktree。
- `branchName` 与实际分支一致。
- `sourceWorkspaceCwd` 存在且指向可用 Git 来源。
- mode/provider 与当前执行语义不冲突。

旧数据如果声明 `providerType=git_worktree` 但缺少 `cwd`、`branchName` 或 `metadata.sourceWorkspaceCwd`，不能继续执行，也不能补一个普通目录假装 worktree。应返回结构化修复错误，或创建新的有效 workspace。

### 2.12 输出事实

每个 preflight 分支最后都应明确产出：

- `workspaceCwd`
- `workspaceKind`：`project_execution`、`organization_scratch` 或 `agent_scratch`
- `codeSourceKind`：`local_cwd`、`managed_checkout`、`repo_url_pending_checkout` 或 `none`
- `providerType`
- `strategyType`
- `branchName`
- `sourceWorkspaceCwd`
- `requiresLease`
- `canRun`
- `failureReason`
- `warnings`

## 3. 模式总览

| 模式 | 执行 cwd | Git 语义 | 任务复用范围 | 写并发规则 | 典型用途 |
| --- | --- | --- | --- | --- | --- |
| `shared_workspace` | 项目主工作区 cwd 或 managed checkout cwd | 使用当前工作树，不自动切换分支 | 同一项目主工作区 | 不创建 workspace 级长锁；同目录并发风险由 issue/agent/run 层约束和用户策略承担 | 直接在用户当前项目目录或受管 checkout 上工作 |
| `isolated_workspace` | 每个 issue 一个 Git worktree cwd | 每个 issue 一个固定分支和 worktree | 单个 issue | 不同 issue 可并行；同一 issue 串行 | 多任务隔离、独立 review、方便丢弃 |
| `operator_branch` | 多个 issue 共用一个固定 operator worktree | 一组任务累积到同一个长期 feature/operator 分支 | 项目 + operator 分支 | 同一 operator cwd 写任务必须串行 | 一个大 feature 拆成多个子任务共同推进 |

三种模式都是“项目执行策略”。当 issue 没有 project，或 project 没有任何代码来源时，运行可以进入 organization scratch，但不应在 UI/API 语义上伪装成项目 shared workspace。
## 4. Shared Workspace

### 4.1 用户理解

`shared_workspace` 表示：让 Octopus 直接在项目主工作区里工作。

例如项目主目录是：

```text
D:\projects\shop-app
```

那么所有绑定到这个 shared workspace 的 issue/subtask 都使用同一个执行目录：

```text
OCTOPUS_WORKSPACE_CWD=D:\projects\shop-app
```

不同任务可以有不同产物目录：

```text
OCTOPUS_ISSUE_ARTIFACTS_DIR=...\artifacts\issues\ISSUE-A
OCTOPUS_ISSUE_ARTIFACTS_DIR=...\artifacts\issues\ISSUE-B
```

但这些产物目录不是 execution workspace，不能展示或记录成任务的工作区 cwd。

### 4.2 适用场景

- 用户希望 agent 像本地开发者一样直接改当前项目目录。
- 项目很小，或者用户明确接受所有任务在同一个 working tree 中累积改动。
- 用户希望避免为每个 issue 创建分支和 worktree。
- 当前任务不是并行开发，而是按顺序推进。

### 4.3 不适用场景

- 希望多个子任务并行修改代码。
- 希望每个 issue 都能独立 review 或丢弃。
- 不希望任务改动污染项目主工作树。
- 需要长期 feature 分支承载一组任务，但又不想直接动主工作区。

### 4.4 并发规则

shared 模式下，Octopus 不应为了“保护共享工作区”而在整个任务执行周期持有 workspace 写锁。

原因：

- 上游 upstream reference 的 shared workspace 对应 `project_primary`，不会为 shared 注入 managed `workspaceStrategy`。
- 上游只有 issue checkout / execution lock 用于防止同一个 issue 被重复执行；没有 workspace 目录级长锁。
- 上游的 runtime service lease 用于服务复用和释放，不是代码目录写锁。

因此 shared 模式的并发边界应改为：

- 同一个 issue 仍由 issue checkout / execution lock 防重复执行。
- 同一个 agent 如果运行时一次只能执行一个 run，继续使用 agent/run 队列。
- 共享项目 cwd 不再通过 workspace lease 长时间锁住。
- 如果用户要并行修改不同功能，应选择 `isolated_workspace`。

### 4.5 分支安全

Octopus 不得自动对 shared 项目主工作树执行：

- `git checkout`
- `git switch`
- `git reset`
- rebase

如果策略声明期望分支，但当前工作树分支不同，preflight 应失败并提示用户，而不是自动切换。

## 5. Isolated Workspace

### 5.1 用户理解

`isolated_workspace` 表示：每个 issue/subtask 有自己的执行工作区。对齐上游 upstream reference 后，Octopus 的正常 isolated 项目策略应基于 Git worktree：每个 issue 一个 worktree 和固定分支。

```text
Issue A -> D:\projects\shop-app\.octopus\worktrees\octopus-ISSUE-A
Issue B -> D:\projects\shop-app\.octopus\worktrees\octopus-ISSUE-B
```

对应分支：

```text
Issue A -> octopus/ISSUE-A
Issue B -> octopus/ISSUE-B
```

同一个 issue 的重试、恢复和后续 run 应复用同一个 execution workspace，不因标题或策略变化而重新生成分支。

### 5.2 适用场景

- 多个 issue 可以并行执行。
- 每个 issue 需要独立 review、独立 diff、独立清理。
- 用户希望失败任务保留现场，不影响其他任务。
- 任务之间依赖较少，或者可以通过后续 merge/PR 集成。

### 5.3 不适用场景

- 多个子任务强依赖同一批未合并改动。
- 用户希望所有任务直接累积到当前本地 working tree。
- 大 feature 被拆成多个任务，但这些任务应该共享一个长期分支。

### 5.4 并发规则

不同 issue 的 isolated execution workspace 可以并行，因为它们写不同 cwd。

同一 issue 的多个 run 必须串行或复用同一个 issue execution workspace，因为它们写同一个 cwd。

### 5.5 Git 来源要求

上游 upstream reference 的 isolated 通过 `workspaceStrategy: { type: "git_worktree" }` 落地。Octopus 对齐时应按这个约束处理：

- 有 `repoUrl` 但没有 `cwd`：先创建受管 project checkout，再从 checkout 创建 issue worktree。
- 有 `cwd` 但不是 Git repo：isolated 不成立，提示配置 Git repo 或 repoUrl。
- 没有 `repoUrl` 也没有 `cwd`：不进入正常 isolated；只能作为 organization scratch 或要求先配置项目主工作区。
- 不得把普通目录标记为 `git_worktree`，也不得把普通 local_fs 目录包装成正常 isolated。

## 6. Operator Branch

### 6.1 用户理解

`operator_branch` 表示：一组相关 issue 共用一个固定长期分支和一个固定 worktree。

它适合“大 feature 拆成多个子任务，但这些子任务应该共同累积到同一个分支”的场景。

例如项目主工作区是：

```text
D:\projects\shop-app
```

配置 operator branch：

```text
feature/checkout-redesign
```

Octopus 创建或复用一个 operator worktree：

```text
D:\projects\shop-app\.octopus\worktrees\feature-checkout-redesign
```

多个 issue 都进入这个 cwd 执行：

```text
Issue A -> feature/checkout-redesign worktree
Issue B -> feature/checkout-redesign worktree
Issue C -> feature/checkout-redesign worktree
```

最终这个 branch 作为一个整体 review、push、PR 或 merge。

### 6.2 它和 shared 的区别

`shared_workspace` 直接使用用户项目主工作树。它简单，但会直接污染当前 working tree。

`operator_branch` 不碰项目主工作树，而是在一个固定 feature/operator 分支 worktree 里累积改动。

```text
shared_workspace:
  所有任务 -> D:\projects\shop-app

operator_branch:
  所有相关任务 -> D:\projects\shop-app\.octopus\worktrees\feature-checkout-redesign
```

### 6.3 它和 isolated 的区别

`isolated_workspace` 是每个 issue 一个分支、一个 worktree。

`operator_branch` 是多个 issue 共用一个分支、一个 worktree。

```text
isolated_workspace:
  Issue A -> octopus/ISSUE-A -> worktree A
  Issue B -> octopus/ISSUE-B -> worktree B

operator_branch:
  Issue A -> feature/checkout-redesign -> same operator worktree
  Issue B -> feature/checkout-redesign -> same operator worktree
```

### 6.4 适用场景

- 一个大功能被拆成多个 issue，但这些 issue 共享上下文和代码状态。
- 子任务之间依赖强，后续任务需要基于前序任务未合并的代码继续做。
- 用户希望保护项目主工作树，但又不希望每个 issue 都独立分支。
- 一个 agent/operator 长期负责一个方向，例如 UI redesign、runtime hardening、workspace rewrite。

### 6.5 不适用场景

- 每个 issue 都应独立 review 或独立丢弃。
- 多个任务需要真正并行写代码。
- 没有明确的长期 feature/operator 分支。
- 项目没有 Git 来源。

### 6.6 并发规则

上游 upstream reference 当前只把 `operator_branch` 作为 policy mode 识别和持久化；已读到的代码里没有看到自动创建或切换 operator branch/worktree 的实现。

因此 Octopus 后续实现 operator branch 时，应单独定义它的串行控制和 lease scope，不能沿用 shared workspace 长锁：

- 如果 operator branch 复用一个固定 operator cwd，同一 operator cwd 的写入需要串行。
- 这个串行只属于 operator execution workspace，不属于项目主 shared cwd。
- operator branch 的自动创建、checkout、push、PR、cleanup 都必须单独设计和验收。

### 6.7 分支规则

- operator branch 必须由项目策略明确配置或由用户显式选择。
- 同一个 operator workspace 不按 issue 创建子分支。
- Octopus 不自动 merge operator branch。
- push、PR、merge、删除分支都应是后续显式动作。

## 7. 任务产物目录不是工作区模式

三种模式都可以为每个 issue/run 创建独立产物目录，例如：

```text
...\artifacts\issues\<issueId>
```

这个目录用于：

- 截图
- 报告
- 日志摘要
- CSV/JSON/Markdown handoff
- issue work products

它不决定代码在哪里执行，也不参与 shared/isolated/operator 的模式判断。

因此 UI/API 应避免把 `issueArtifactsDir` 命名或展示成 workspace cwd。推荐命名：

- `workspace.cwd`：执行目录。
- `issueArtifactsDir`：任务产物目录。
- `workspace.mode`：执行工作区模式。
- `workspace.providerType`：执行目录提供者，如 `local_fs` 或 `git_worktree`。

## 8. 队列和 lease 的真正含义

队列不是因为“任务有产物目录”而存在。对齐上游后，还要区分三类不同的串行控制，不能混成 workspace 锁：

- issue checkout / execution lock：防止同一个 issue 被重复执行。
- agent/run 队列：防止同一个 agent 或 runtime 同时跑超过能力上限的 run。
- runtime service lease：复用和释放 dev server 等服务。

shared workspace 不应再新增 workspace 级长锁或 workspace lease 队列。

| 情况 | 是否需要写队列 |
| --- | --- |
| shared 模式多个任务写同一个项目 cwd | 不使用 workspace 级长锁；需要串行时应由 issue/agent/run 层表达 |
| isolated 模式不同 issue 写不同 cwd | 不需要跨 issue 队列 |
| isolated 模式同一 issue 多个 run 写同一 cwd | 需要同 issue 串行 |
| operator 模式多个 issue 写同一个 operator cwd | 需要 |
| 多个任务只写各自 artifacts 目录 | 不因此需要 workspace 写队列 |

## 9. Preflight 输出必须满足的约束

每次 run preflight 完成后，workspace context 至少要满足两类约束：运行时可以安全执行，UI/API 可以正确解释它是什么。

### 9.1 运行时约束

- `OCTOPUS_WORKSPACE_CWD` 指向真实执行目录。
- `OCTOPUS_ISSUE_ARTIFACTS_DIR` 如果存在，只表示产物目录。
- `providerType=git_worktree` 时，目录必须能被 Git 原生命令验证为 worktree。
- 没有 Git 来源时，不能生成 fake `git_worktree`。
- shared 模式不能为每个子任务生成新的 execution cwd。
- operator 模式不能为每个 issue 生成子分支。
- isolated 模式不能让不同 issue 共享同一个 execution cwd，除非用户显式复用已有 workspace。

### 9.2 解释性输出

Preflight/API 应返回足够事实，避免 UI 只能从 `cwd` 或 mode 猜语义：

- `workspaceKind`：`project_execution`、`organization_scratch` 或 `agent_scratch`。
- `codeSourceKind`：`local_cwd`、`managed_checkout`、`repo_url_pending_checkout` 或 `none`。
- `workspaceCwd`：实际执行 cwd。
- `issueArtifactsDir`：issue 产物目录。
- `providerType`：`local_fs`、`git_worktree` 等。
- `strategyType`：实际工作区策略。
- `branchName`：执行目录当前/目标分支。
- `sourceWorkspaceCwd`：worktree 来源 cwd。
- `requiresLease`：是否需要非 workspace 级的运行时 lease；shared 不应返回 workspace 写长锁。
- `canRun`：是否可执行。
- `failureReason`：不能执行时的结构化原因。
- `warnings`：例如“无代码来源，使用组织草稿目录”。

### 9.3 命名约束

- `organization_scratch` 不能展示为项目 shared workspace。
- `agent_scratch` 不能展示为项目 execution workspace。
- `issueArtifactsDir` 不能展示为 workspace cwd。
- `project_execution` 才能进入 shared / isolated / operator 的项目策略语义。

## 10. 后续开发计划

开发顺序、清理项、UI 调整和三种模式后续实现计划见 [WORKSPACE-PLAN.md](./WORKSPACE-PLAN.md)。
