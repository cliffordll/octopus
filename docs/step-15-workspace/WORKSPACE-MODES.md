# 三种执行工作区模式语义

状态：草案
日期：2026-06-30
职责归属：Step 15 Workspace

## 1. 为什么需要这份文档

Octopus 里容易混淆的不是“三个模式叫什么”，而是这些对象分别承担什么职责：

- 执行工作区 cwd：runtime/agent 真正进入并修改代码的目录。
- 任务产物目录：某个 issue/run 的截图、报告、日志、handoff 文件归档目录。
- Git 分支或 worktree：代码变更如何隔离、累积、review 和合并。
- 队列或 lease：多个任务是否可以同时写同一个 cwd。

三种模式只决定执行 cwd 和 Git 复用语义，不改变任务产物必须按 issue/run 可追溯的要求。

一个关键规则：

> `OCTOPUS_WORKSPACE_CWD` 是执行目录；`OCTOPUS_ISSUE_ARTIFACTS_DIR` 是任务产物目录。二者不能混为一个概念。

如果 shared 模式下每个子任务都有独立执行 cwd，那么 shared 就退化成 isolated，队列也失去意义。因此 shared 模式必须明确为“多个任务共享同一个执行 cwd，并由队列串行写入”。

## 2. Preflight 场景矩阵

Preflight 不应只按 mode 分支。它必须先判断项目和代码来源是否存在，再决定 mode 能否成立。

核心输入事实：

- issue 是否有关联 project。
- project 是否有 project workspace 记录。
- project workspace 是否有 `cwd`。
- 如果没有 `cwd`，是否有 `repoUrl` 可创建 managed checkout。
- `cwd` 是否存在且可访问。
- `cwd` 是否是 Git repo。
- issue 是否已经绑定 existing execution workspace。
- mode 是 `shared_workspace`、`isolated_workspace` 还是 `operator_branch`。

总览矩阵：

| 输入场景 | `shared_workspace` | `isolated_workspace` | `operator_branch` |
| --- | --- | --- | --- |
| 无 project | organization workspace fallback；`local_fs`；按 org cwd 串行 | 不进入 isolated；按 projectless organization fallback 处理 | 不进入 operator；按 projectless organization fallback 处理 |
| 有 project，无 project workspace 记录 | organization workspace fallback；`local_fs`；给 warning | 创建 issue 级 managed `local_fs` execution workspace | preflight 失败 |
| 有 project workspace，无 `cwd`，有 `repoUrl` | 创建 managed checkout；cwd 指向 checkout | 创建 managed checkout；从 checkout 创建 issue worktree | 创建 managed checkout；从 checkout 创建固定 operator worktree |
| 有 project workspace，无 `cwd`，无 `repoUrl` | organization workspace fallback；`local_fs`；给 warning | 创建 issue 级 managed `local_fs` execution workspace | preflight 失败 |
| 有 `cwd`，但路径不存在或不可访问 | preflight 失败 | preflight 失败 | preflight 失败 |
| 有 `cwd`，但不是 Git repo | 使用项目 cwd；`local_fs` | 创建 issue 级 managed `local_fs` execution workspace | preflight 失败 |
| 有 `cwd`，且是 Git repo | 使用项目 cwd；不自动切分支；同 cwd 串行 | 创建或复用 issue Git worktree | 创建或复用固定 operator branch worktree |
| 已有 execution workspace | 优先复用，但校验 cwd/provider/mode | 优先复用，但校验 cwd/provider/branch/source | 优先复用同 operator branch workspace，并校验 cwd/provider/branch/source |
### 2.1 无 project

| 情况 | 处理 |
| --- | --- |
| issue 没有关联 project | 使用 organization workspace fallback |
| mode | 不进入三种 project workspace 模式；运行时视为 organization shared fallback |
| provider | `local_fs` |
| `OCTOPUS_WORKSPACE_CWD` | `<OCTOPUS_HOME>\instances\<instanceId>\organizations\<orgId>\workspaces` |
| Git/worktree | 不创建 |
| 队列 | 按 organization workspace cwd 串行 |
| artifacts | 仍然按 issue 独立：`artifacts\issues\<issueId>` |

这个场景适合写报告、整理资料、生成文档、轻量自动化；不适合作为代码修改任务。需要修改代码时，应先关联 project 并配置 project workspace 或 repo。

### 2.2 有 project，但没有 project workspace 记录

| mode | 处理 |
| --- | --- |
| `shared_workspace` | 回退 organization workspace，`providerType=local_fs`，并给 warning |
| `isolated_workspace` | 创建 issue 级 managed `local_fs` execution workspace |
| `operator_branch` | preflight 失败，因为没有 Git 来源和固定分支来源 |

注意：isolated 不能回退到共享 organization workspace，否则就不再是 isolated。

### 2.3 有 project workspace，无 `cwd`，但有 `repoUrl`

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

### 2.4 有 project workspace，无 `cwd`，也无 `repoUrl`

| mode | 处理 |
| --- | --- |
| `shared_workspace` | 回退 organization workspace，`providerType=local_fs`，并给 warning |
| `isolated_workspace` | 创建 issue 级 managed `local_fs` execution workspace |
| `operator_branch` | preflight 失败 |

### 2.5 有 `cwd`，但路径不存在或不可访问

默认应 preflight 失败，而不是静默 fallback。

原因：用户已经显式配置了本地路径，路径不存在通常表示配置错误、磁盘未挂载、权限错误或迁移遗漏。静默 fallback 可能让任务在错误目录中执行。

### 2.6 有 `cwd`，但不是 Git repo

| mode | 处理 |
| --- | --- |
| `shared_workspace` | 可以执行；`providerType=local_fs` 或 project primary local path |
| `isolated_workspace` | 创建 issue 级 managed `local_fs` execution workspace，不能标记为 `git_worktree` |
| `operator_branch` | preflight 失败 |

operator branch 必须有 Git 来源；否则 branch 语义不存在。

### 2.7 有 `cwd`，且是 Git repo

| mode | 处理 |
| --- | --- |
| `shared_workspace` | 使用项目主工作区 cwd，不自动切换分支 |
| `isolated_workspace` | 为 issue 创建或复用真实 Git worktree |
| `operator_branch` | 创建或复用固定 operator branch worktree |

### 2.8 已有 execution workspace

如果 issue 已绑定 execution workspace，preflight 应优先复用，但必须校验它仍然有效：

- `cwd` 存在且可访问。
- `providerType=git_worktree` 时，目录是真实 Git worktree。
- `branchName` 与实际分支一致。
- `sourceWorkspaceCwd` 存在且指向可用 Git 来源。
- mode/provider 与当前执行语义不冲突。

旧数据如果声明 `providerType=git_worktree` 但缺少 `cwd`、`branchName` 或 `metadata.sourceWorkspaceCwd`，不能继续执行，也不能补一个普通目录假装 worktree。应返回结构化修复错误，或创建新的有效 workspace。

### 2.9 输出事实

每个 preflight 分支最后都应明确产出：

- `workspaceCwd`
- `providerType`
- `strategyType`
- `branchName`
- `sourceWorkspaceCwd`
- `requiresLease`
- `canRun`
- `failureReason`

## 3. 模式总览

| 模式 | 执行 cwd | Git 语义 | 任务复用范围 | 写并发规则 | 典型用途 |
| --- | --- | --- | --- | --- | --- |
| `shared_workspace` | 项目主工作区 cwd | 使用当前工作树，不自动切换分支 | 同一项目工作区 | 同一 cwd 写任务必须串行 | 直接在用户当前项目目录工作 |
| `isolated_workspace` | 每个 issue 一个独立 cwd/worktree | 每个 issue 一个固定分支或 local_fs execution cwd | 单个 issue | 不同 issue 可并行；同一 issue 串行 | 多任务隔离、独立 review、方便丢弃 |
| `operator_branch` | 多个 issue 共用一个固定 operator worktree | 一组任务累积到同一个长期 feature/operator 分支 | 项目 + operator 分支 | 同一 operator cwd 写任务必须串行 | 一个大 feature 拆成多个子任务共同推进 |

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

shared 模式下，同一个执行 cwd 的写任务必须串行。

原因：两个任务同时写同一个 working tree 会让 diff、测试结果、失败恢复、work product 归属和 review 边界全部混在一起。

因此 shared 模式需要 workspace write lease 或队列。队列保护的是共享执行 cwd，不是任务产物目录。

### 4.5 分支安全

Octopus 不得自动对 shared 项目主工作树执行：

- `git checkout`
- `git switch`
- `git reset`
- rebase

如果策略声明期望分支，但当前工作树分支不同，preflight 应失败并提示用户，而不是自动切换。

## 5. Isolated Workspace

### 5.1 用户理解

`isolated_workspace` 表示：每个 issue/subtask 有自己的执行工作区。

Git 项目里通常是每个 issue 一个 worktree 和固定分支：

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

同一 issue 的多个 run 必须串行或复用同一 lease，因为它们写同一个 issue workspace。

### 5.5 无 Git 来源时的 fallback

如果没有可用 Git 来源：

- 有 `repoUrl` 但没有 `cwd`：先创建受管 project checkout，再从 checkout 创建 issue worktree。
- 没有 `repoUrl` 也没有 `cwd`：可创建 issue 级 `local_fs` execution workspace。
- 不得把普通目录标记为 `git_worktree`。

这个 fallback 仍然是 isolated，因为每个 issue 有自己的 execution cwd；只是 provider 不是 Git worktree。

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

operator branch 多个任务写同一个 operator cwd，因此必须串行。

它和 shared 一样需要 write lease，但 lease scope 不同：

- shared lease scope：project workspace cwd。
- operator lease scope：operator branch execution workspace。

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

队列不是因为“任务有产物目录”而存在，而是因为“多个任务写同一个执行 cwd”而存在。

| 情况 | 是否需要写队列 |
| --- | --- |
| shared 模式多个任务写同一个项目 cwd | 需要 |
| isolated 模式不同 issue 写不同 cwd | 不需要跨 issue 队列 |
| isolated 模式同一 issue 多个 run 写同一 cwd | 需要同 issue 串行 |
| operator 模式多个 issue 写同一个 operator cwd | 需要 |
| 多个任务只写各自 artifacts 目录 | 不因此需要 workspace 写队列 |

## 9. Preflight 输出必须满足的约束

每次 run preflight 完成后，workspace context 至少要满足：

- `OCTOPUS_WORKSPACE_CWD` 指向真实执行目录。
- `OCTOPUS_ISSUE_ARTIFACTS_DIR` 如果存在，只表示产物目录。
- `providerType=git_worktree` 时，目录必须能被 Git 原生命令验证为 worktree。
- 没有 Git 来源时，不能生成 fake `git_worktree`。
- shared 模式不能为每个子任务生成新的 execution cwd。
- operator 模式不能为每个 issue 生成子分支。
- isolated 模式不能让不同 issue 共享同一个 execution cwd，除非用户显式复用已有 workspace。

## 10. 建议的 UI 文案

### Shared Workspace

直接在项目主工作区执行。所有写任务会串行运行，避免多个任务同时修改同一个工作树。每个任务仍有独立产物目录，但不会创建独立执行工作区。

### Isolated Workspace

每个任务使用独立执行工作区。Git 项目会为每个 issue 创建或复用独立 worktree 和分支，适合并行开发、独立 review 和失败保留现场。

### Operator Branch

多个相关任务共用一个固定 feature/operator 分支工作区。适合一个大功能拆成多个子任务并持续累积到同一分支，同时避免直接修改项目主工作树。

## 11. 实现检查清单

- shared 模式下，不得按 issue 创建 execution workspace cwd。
- shared 模式下，不同 issue 的 `OCTOPUS_WORKSPACE_CWD` 必须相同，`OCTOPUS_ISSUE_ARTIFACTS_DIR` 可以不同。
- isolated 模式下，不同 issue 的 `OCTOPUS_WORKSPACE_CWD` 必须不同。
- operator 模式下，绑定同一 operator branch 的 issue 的 `OCTOPUS_WORKSPACE_CWD` 必须相同。
- shared/operator/same-issue isolated 必须有可恢复 write lease。
- fallback 到 local_fs 时，`providerType` 必须是 `local_fs`。
- UI 不得把 artifacts 目录展示成 workspace cwd。
- operation/log/work product 可以按 issue/run 归档，但不能反向改变执行 cwd 语义。
