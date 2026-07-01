# 项目工作区与执行工作区模式语义

状态：草案
日期：2026-07-01
职责归属：Step 15 Workspace

## 1. 为什么需要这份文档

Octopus 里容易混淆的不是“三个模式叫什么”，而是项目、项目工作区、执行模式和运行实例分别承担什么职责。配置归属与运行时解析必须分开：

```text
Project
  -> 0..N ProjectWorkspace（frontend、backend、mobile 等代码来源）
       -> 每个 ProjectWorkspace 各自配置执行模式

Issue/Run
  -> 选择一个 ProjectWorkspace（显式选择，或使用项目默认工作区）
  -> 读取该工作区的执行模式，并应用可选的 issue override
  -> Preflight 校验来源能力，创建或复用 ExecutionWorkspace
```

如果项目没有任何项目工作区，任务默认进入组织级 scratch cwd。此时不读取或展示 `shared_workspace`、`isolated_workspace`、`operator_branch`，因为没有代码来源可供这些模式复用或派生。组织级 scratch 不能被解释成项目代码工作区。

核心对象：

- 项目工作区：项目下一个可执行代码来源，可以是本地 `cwd`，也可以是 `repoUrl` 创建出的 managed checkout。一个项目可以有多个，例如 frontend 和 backend 仓库。
- 默认项目工作区：当 issue 未显式选择工作区时使用的项目工作区；默认只解决选择问题，不承载整个项目的执行模式。
- 执行工作区 cwd：runtime/agent 真正进入并修改代码的目录，对应 `OCTOPUS_WORKSPACE_CWD`。
- 工作区执行模式：从选中的项目工作区复用或派生执行 cwd 的方式，即 `shared_workspace`、`isolated_workspace`、`operator_branch`。模式归属于项目工作区，而不是项目。
- 组织级工作区：organization 范围的运行时文件根目录，用于 artifacts、plans、skills、agents、managed checkout 父目录和无项目 scratch，不是项目代码目录。
- 智能体级工作区：agent 私有 scratch、memory、工具缓存和 session 辅助文件，不是项目代码目录。
- 任务产物目录：某个 issue/run 的截图、报告、日志、handoff 文件归档目录，对应 `OCTOPUS_ISSUE_ARTIFACTS_DIR`。
- Git 分支或 worktree：代码变更如何隔离、累积、review 和合并。
- 队列或 lease：多个任务是否可以同时写同一个执行 cwd。

关键规则：

> `OCTOPUS_WORKSPACE_CWD` 是执行目录；`OCTOPUS_ISSUE_ARTIFACTS_DIR` 是任务产物目录；组织级/智能体级 workspace 是运行时基础设施目录。三者不能混为一个概念。

如果 shared 模式下每个子任务都有独立执行 cwd，那么 shared 就退化成 isolated。对齐上游 upstream reference 后，shared 模式应明确为“直接使用所选项目工作区 cwd”，不应再叠加“每个任务一个执行目录 + workspace 长锁 + workspace 队列”这套语义。

## 2. 配置与决策模型

### 2.1 配置归属与多仓库

目标数据归属：

| 配置 | 归属 | 说明 |
| --- | --- | --- |
| 项目名称、状态、负责人、目标 | `projects` | 与代码执行目录无关的项目属性 |
| cwd、repoUrl、repoRef、默认标记 | `project_workspaces` | 一个项目可以登记多个代码来源 |
| shared / isolated / operator 配置 | `project_workspaces.execution_workspace_policy` | 每个代码来源独立选择执行方式 |
| issue 选择的项目工作区 | issue workspace settings / `projectWorkspaceId` | 一次 issue/run 只选择一个主要执行 cwd |
| 实际 mode、cwd、branch、provider | `execution_workspaces` | 运行时解析结果和审计快照 |

多仓库是正式场景，不是异常状态。例如：

```text
Project: Commerce
  frontend -> D:\repos\commerce-web -> isolated_workspace
  backend  -> D:\repos\commerce-api -> shared_workspace
```

一个 issue/run 默认只选择其中一个项目工作区作为主要执行 cwd。需要同时修改 frontend 和 backend 时，应拆成两个明确指定工作区的 issue；单次 run 同时写多个主要 cwd 属于后续 multi-root workspace 能力，不在本文当前模型内。

项目必须最多只有一个默认项目工作区。默认工作区只在 issue 未显式选择时兜底；不能因为存在默认工作区，就把其模式提升成整个项目的统一模式。

### 2.2 第一层：选择项目工作区

运行时先解析 issue 要在哪个项目工作区执行，而不是先读取项目级 mode：

```text
已有且有效的 execution workspace
  -> issue 显式 projectWorkspaceId
  -> 项目默认 project workspace
  -> organization scratch
```

| 输入场景 | 语义 | 模式来源 | 默认处理 |
| --- | --- | --- | --- |
| issue 无 project | 无项目代码上下文 | 无 | organization scratch run，可用于文档、报告和轻量自动化 |
| project 无 project workspace 记录 | 项目没有代码来源 | 无 | organization scratch run；UI 提示添加项目工作区 |
| project 有多个 workspace，issue 已选择 | 明确的单仓库执行 | 所选 workspace 的 policy | 校验该来源后执行 |
| project 有多个 workspace，issue 未选择 | 需要默认来源 | 默认 workspace 的 policy | 使用唯一默认 workspace；没有默认项则要求用户选择 |
| workspace 无 `cwd`，有 `repoUrl` | 有远程来源但尚未 checkout | 当前 workspace 的 policy | 创建 managed checkout 并持久化 cwd |
| workspace 无 `cwd`，无 `repoUrl` | 工作区记录不完整 | 当前 workspace 的 policy 不可执行 | preflight 失败并提示修复来源 |
| workspace 有 `cwd` | 有本地代码来源 | 当前 workspace 的 policy | 校验路径和 Git 能力 |

这一层的输出事实必须是：

- 是否有 project。
- 最终选择的 `projectWorkspaceId`。
- 该工作区来源是 `local cwd`、`managed checkout`、`repoUrl pending checkout`，还是 `none`。
- 该工作区是否是 Git repo。
- 该工作区配置的执行模式是否可用。
- 如果不允许，是否允许 organization scratch run。

### 2.3 第二层：解析工作区执行模式

模式解析优先级是：

```text
issue mode override
  -> selected project workspace policy
  -> shared_workspace（workspace 默认）
```

项目级 `projects.execution_workspace_policy` 已删除。workspace policy 为空时只使用 workspace 默认 shared，不读取项目级兼容字段。

| 执行策略 | 需要的前置条件 | 执行 cwd | Git 语义 | 写并发规则 | 典型用途 |
| --- | --- | --- | --- | --- | --- |
| `shared_workspace` | 所选工作区有 cwd，或有 repoUrl 可先创建 managed checkout | 所选项目工作区 cwd | 使用当前工作树，不自动切换分支 | 不创建 workspace 级长锁；只保留 issue/agent/run 级并发控制 | 直接在该代码来源上工作 |
| `isolated_workspace` | 所选工作区是 Git repo，或有 repoUrl 可先创建 managed checkout | 每个 issue 一个 Git worktree cwd | 每个 issue 一个固定分支和 worktree | 不同 issue 可并行；同一 issue 串行 | 多任务隔离、独立 review、方便丢弃 |
| `operator_branch` | 所选工作区具备 Git 来源 | 多个 issue 共用一个固定 operator worktree | 一组任务累积到同一个长期 feature/operator 分支 | 同一 operator cwd 写任务必须串行 | 一个大 feature 拆成多个子任务共同推进 |

### 2.4 第三层：运行时目录

运行时目录不决定项目工作区的执行模式，只给 agent 提供辅助存储。

| 目录 | 作用 | 是否是代码工作区 |
| --- | --- | --- |
| organization workspace root | 组织范围 scratch、artifacts/plans/skills/agents 根目录、managed checkout 父目录 | 否，除非明确进入 organization scratch run |
| agent workspace root | agent 私有 memory、scratch、工具缓存 | 否 |
| issue artifacts dir | issue/run 产物归档 | 否 |
| execution workspace cwd | agent 真正执行和修改代码的目录 | 是 |

### 2.5 Preflight 场景矩阵

| 输入场景 | `shared_workspace` | `isolated_workspace` | `operator_branch` |
| --- | --- | --- | --- |
| 无 project | mode 不适用；进入 organization scratch | mode 不适用；进入 organization scratch | mode 不适用；进入 organization scratch |
| 有 project，无 project workspace 记录 | mode 不适用；进入 organization scratch | mode 不适用；进入 organization scratch | mode 不适用；进入 organization scratch |
| 有多个 workspace，但 issue 未选择且无默认项 | 要求选择工作区 | 要求选择工作区 | 要求选择工作区 |
| 有 project workspace，无 `cwd`，有 `repoUrl` | 创建 managed checkout；cwd 指向 checkout | 创建 managed checkout；从 checkout 创建 issue worktree | 创建 managed checkout；从 checkout 创建固定 operator worktree |
| 有 project workspace，无 `cwd`，无 `repoUrl` | UI 标记“无代码来源”；不应作为正常 shared | UI 标记“无代码来源”；不应作为正常 isolated | preflight 失败 |
| 有 `cwd`，但路径不存在或不可访问 | preflight 失败 | preflight 失败 | preflight 失败 |
| 有 `cwd`，但不是 Git repo | 使用项目 cwd；`local_fs` | isolated 不成立；提示配置 Git repo 或 repoUrl | preflight 失败 |
| 有 `cwd`，且是 Git repo | 使用项目 cwd；不自动切分支；同 cwd 串行 | 创建或复用 issue Git worktree | 创建或复用固定 operator branch worktree |
| 已有 execution workspace | 优先复用，但校验 cwd/provider/mode | 优先复用，但校验 cwd/provider/branch/source | 优先复用同 operator branch workspace，并校验 cwd/provider/branch/source |

### 2.6 无 project

| 情况 | 处理 |
| --- | --- |
| issue 没有关联 project | 使用 organization scratch run，而不是项目 shared workspace |
| mode | 不进入三种 project execution strategy |
| provider | `local_fs` |
| `OCTOPUS_WORKSPACE_CWD` | `<OCTOPUS_HOME>\instances\<instanceId>\organizations\<orgId>\workspaces` |
| Git/worktree | 不创建 |
| 队列 | 按 organization scratch cwd 串行 |
| artifacts | 仍然按 issue 独立：`artifacts\issues\<issueId>` |

这个场景适合写报告、整理资料、生成文档、轻量自动化；不适合作为代码修改任务。需要修改代码时，应先关联 project 并选择或创建项目工作区。

### 2.7 有 project，但没有项目工作区或选中的工作区不可用

必须区分两个状态：

- 没有 project workspace 记录：项目没有代码来源，任务进入 organization scratch，不解析三种 mode。
- 已选 project workspace，但 `cwd` 和 `repoUrl` 都为空：这是损坏或未完成的工作区配置，preflight 失败。

产品语义：

- 项目没有工作区时，UI 展示“当前使用组织草稿目录；添加项目工作区后可配置代码执行模式”。
- 三种 mode 只显示在具体的项目工作区配置中，不显示项目级全局 mode。
- 已选工作区缺少 cwd 和 repoUrl 时，UI 标记该工作区不可用并要求修复，不能静默改用另一个项目工作区。
- organization scratch response/context 必须携带明确的 `workspaceKind=organization_scratch`，不能把它命名为项目 shared workspace。

### 2.8 有 project workspace，无 `cwd`，但有 `repoUrl`

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
  -> 持久化当前 project_workspace.cwd
  -> 再按 shared / isolated / operator 继续解析
```

| mode | 处理 |
| --- | --- |
| `shared_workspace` | `OCTOPUS_WORKSPACE_CWD` 指向 managed checkout |
| `isolated_workspace` | 从 managed checkout 创建 issue worktree |
| `operator_branch` | 从 managed checkout 创建固定 operator branch worktree |

managed checkout 是当前 project workspace 的本地来源，不是 issue artifacts 目录。

当前 Octopus 把 managed checkout 放在组织级工作区下面；目标模型还必须加入 workspace 标识：

```text
<OCTOPUS_HOME>\instances\<instanceId>\organizations\<orgId>\workspaces\projects\<projectId前8位>\<workspaceId前8位>\checkout
```

例如 server 在 `D:\coding\octopus` 启动，并显式设置：

```powershell
$env:OCTOPUS_HOME = ".octopus"
```

默认 instance 为 `default` 时，路径形态是：

```text
D:\coding\octopus\.octopus\instances\default\organizations\<orgId>\workspaces\projects\<projectId前8位>\<workspaceId前8位>\checkout
```

需要明确区分物理位置和逻辑角色：

| 对象 | 路径位置 | 逻辑角色 |
| --- | --- | --- |
| organization workspace root | `<OCTOPUS_HOME>\instances\<instanceId>\organizations\<orgId>\workspaces` | 组织级文件根目录 |
| managed checkout | `...\workspaces\projects\<projectId前8位>\<workspaceId前8位>\checkout` | 一个项目工作区的受管代码来源，即 `project_workspaces.cwd` |
| organization scratch | organization workspace root 或其 scratch 子目录 | 无项目/无代码任务的临时执行位置 |
| issue artifacts | `...\workspaces\artifacts\issues\<issueId>` | 任务产物目录 |

因此，managed checkout 虽然物理上位于组织级工作区之下，但语义上属于一个具体的项目工作区。UI/API 不能把它展示成 organization scratch，也不能把 organization workspace root 本身展示成项目 shared workspace。多仓库项目的 checkout 路径必须包含 workspace 标识，不能让 frontend/backend 共用同一 checkout 目录。

### 2.9 有 `cwd`，但路径不存在或不可访问

默认应 preflight 失败，而不是静默 fallback。

原因：用户已经显式配置了本地路径，路径不存在通常表示配置错误、磁盘未挂载、权限错误或迁移遗漏。静默 fallback 可能让任务在错误目录中执行。

### 2.10 有 `cwd`，但不是 Git repo

| mode | 处理 |
| --- | --- |
| `shared_workspace` | 可以执行；`providerType=local_fs`，cwd 为所选项目工作区路径 |
| `isolated_workspace` | isolated 不成立；不能创建 fake `git_worktree`，也不能把普通 local_fs 目录包装成正常 isolated |
| `operator_branch` | preflight 失败 |

operator branch 必须有 Git 来源；否则 branch 语义不存在。

### 2.11 有 `cwd`，且是 Git repo

| mode | 处理 |
| --- | --- |
| `shared_workspace` | 使用所选项目工作区 cwd，不自动切换分支 |
| `isolated_workspace` | 为 issue 创建或复用真实 Git worktree |
| `operator_branch` | 创建或复用固定 operator branch worktree |

### 2.12 已有 execution workspace

如果 issue 已绑定 execution workspace，preflight 应优先复用，但必须校验它仍然有效：

- `cwd` 存在且可访问。
- `providerType=git_worktree` 时，目录是真实 Git worktree。
- `branchName` 与实际分支一致。
- `sourceWorkspaceCwd` 存在且指向可用 Git 来源。
- mode/provider 与当前执行语义不冲突。

旧数据如果声明 `providerType=git_worktree` 但缺少 `cwd`、`branchName` 或 `metadata.sourceWorkspaceCwd`，不能继续执行，也不能补一个普通目录假装 worktree。应返回结构化修复错误，或创建新的有效 workspace。

### 2.13 输出事实

每个 preflight 分支最后都应明确产出：

- `workspaceCwd`
- `projectWorkspaceId`：本次运行选择的项目工作区；organization scratch 时为 null。
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
| `shared_workspace` | 所选项目工作区 cwd 或其 managed checkout cwd | 使用当前工作树，不自动切换分支 | 同一项目工作区 | 不创建 workspace 级长锁；同目录并发风险由 issue/agent/run 层约束和用户策略承担 | 直接在所选代码来源上工作 |
| `isolated_workspace` | 每个 issue 一个 Git worktree cwd | 每个 issue 一个固定分支和 worktree | 单个 issue | 不同 issue 可并行；同一 issue 串行 | 多任务隔离、独立 review、方便丢弃 |
| `operator_branch` | 多个 issue 共用一个固定 operator worktree | 一组任务累积到同一个长期 feature/operator 分支 | 项目工作区 + operator 分支 | 同一 operator cwd 写任务必须串行 | 一个大 feature 拆成多个子任务共同推进 |

三种模式都是“项目工作区执行模式”。当 issue 没有 project，或 project 没有任何项目工作区时，运行进入 organization scratch，不解析三种模式，也不应在 UI/API 语义上伪装成项目 shared workspace。
## 4. Shared Workspace

### 4.1 用户理解

`shared_workspace` 表示：让 Octopus 直接在 issue 选中的项目工作区里工作。

例如 issue 选中的项目工作区目录是：

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

- 上游 upstream reference 的 shared workspace 对应 `project_primary`；在 Octopus 多工作区模型中，它表示“所选 project workspace”，不会为 shared 注入 managed `workspaceStrategy`。
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

`isolated_workspace` 表示：每个 issue/subtask 有自己的执行工作区。对齐上游 upstream reference 后，Octopus 的正常 isolated 工作区模式应基于所选代码来源创建 Git worktree：每个 issue 一个 worktree 和固定分支。

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
- 没有 `repoUrl` 也没有 `cwd`：当前项目工作区不可用于 isolated；要求修复该工作区来源。
- 不得把普通目录标记为 `git_worktree`，也不得把普通 local_fs 目录包装成正常 isolated。

## 6. Operator Branch

### 6.1 用户理解

`operator_branch` 表示：一组相关 issue 共用一个固定长期分支和一个固定 worktree。

它适合“大 feature 拆成多个子任务，但这些子任务应该共同累积到同一个分支”的场景。

例如 issue 选中的项目工作区是：

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

- operator branch 必须由所选项目工作区的 policy 明确配置，或由 issue 显式覆盖选择。
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
- `projectWorkspaceId`：本次运行选择的项目工作区；organization scratch 时为 null。
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
- `project_execution` 才能进入 shared / isolated / operator 的项目工作区模式语义。

## 10. 目标 API、UI 与迁移规则

### 10.1 Project workspace API

项目工作区的创建和更新 payload 应包含自己的执行策略：

```json
{
  "name": "Frontend",
  "cwd": "D:/repos/commerce-web",
  "repoUrl": null,
  "repoRef": "main",
  "isPrimary": true,
  "executionWorkspacePolicy": {
    "enabled": true,
    "defaultMode": "isolated_workspace",
    "workspaceStrategy": {
      "type": "git_worktree"
    }
  }
}
```

约束：

- `executionWorkspacePolicy` 属于 `project_workspaces`，不属于 `projects`。
- 每个项目最多一个 `isPrimary=true` 的工作区。
- 删除默认工作区前，必须先指定新的默认项，或明确让项目回到 organization scratch。
- `isolated_workspace` 和 `operator_branch` 在保存时可做静态字段校验，真实路径、权限和 Git 状态仍由 preflight 校验。

### 10.2 Issue workspace selection

多工作区项目必须让 issue 明确选择执行来源：

- issue 创建或编辑时可以设置 `projectWorkspaceId`。
- 未设置时使用项目唯一的默认工作区。
- 项目有多个工作区但没有默认项时，代码任务不能静默选择第一条记录。
- 已有 execution workspace 的重试和恢复继续绑定原 `projectWorkspaceId`，除非用户显式执行迁移/重新准备操作。
- issue mode override 只覆盖执行模式，不改变 `projectWorkspaceId`。

### 10.3 项目配置 UI

项目配置页的信息架构应为：

```text
基础信息

项目工作区
  Frontend
    cwd / repoUrl / ref
    执行模式：isolated_workspace
    状态：可用 / checkout pending / 配置错误

  Backend
    cwd / repoUrl / ref
    执行模式：shared_workspace
    状态：可用 / checkout pending / 配置错误

任务运行记录
  显示 projectWorkspaceId + resolved mode + execution cwd
```

UI 规则：

- 不提供项目级全局三模式选择器。
- 模式选择器放在每个项目工作区的编辑区域内。
- “添加项目工作区”一次保存代码来源和该来源的执行模式。
- 项目没有工作区时，不展示三模式选择器，只展示 organization scratch 状态和添加入口。
- “当前生效配置”不是独立全局卡片；每个工作区直接展示自己的来源、模式和可用状态。

### 10.4 数据库迁移

当前没有需要兼容的旧项目，直接迁移到目标模型，不保留双写或 legacy fallback：

1. 为 `project_workspaces` 增加 nullable `execution_workspace_policy`。
2. 增加“每个项目最多一个 `is_primary=true`”的数据库唯一约束。
3. 直接删除 `projects.execution_workspace_policy`，不复制、不回填。
4. 新建 project workspace 时写入明确的默认 shared policy；已有空值只按 workspace 默认 shared 解析。
5. 运行时只按“issue override -> workspace policy -> workspace 默认 shared”解析。
6. 项目没有 workspace 时进入 organization scratch，不创建虚假 workspace，也不读取三模式策略。

### 10.5 非目标

- 本轮不支持一个 run 同时拥有多个主要执行 cwd。
- 本轮不把组织资源附件自动提升为项目工作区。
- 本轮不允许 runtime 在多个项目工作区之间自行猜测或切换。
- 本轮不因物理目录位于 organization workspace root 下，就改变其项目工作区语义。

## 11. 后续开发计划

开发顺序、清理项、UI 调整和三种模式后续实现计划见 [WORKSPACE-PLAN.md](./WORKSPACE-PLAN.md)。两份文档都以“模式跟随 project workspace、issue 选择 workspace、无 workspace 使用 organization scratch”为准。
