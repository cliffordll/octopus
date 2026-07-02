# 工作区模式开发计划

状态：草案
日期：2026-07-01
职责归属：Step 15 Workspace

## 1. 目标

这份文档只描述开发计划，不重复定义工作区语义。设计语义见 [WORKSPACE-MODES.md](./WORKSPACE-MODES.md)。

当前优先级是先清理错误模型，再做新功能：

```text
先清理 shared 错误模型
  -> 再统一 preflight/API 事实输出
  -> 再调整 UI 展示和文案
  -> 再补齐 isolated worktree 行为
  -> 最后讨论和实现 operator_branch
```

不能先在现有错误模型上继续包装 UI 或添加新模式能力。
当前执行状态：

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 第一阶段：清理 Shared 错误模型 | 已执行 | 已删除 workspace operation lease、shared workspace lease 队列、相关 migration 与测试断言 |
| 第二阶段：统一 Preflight/API 事实输出 | 已执行 | 已输出 `workspaceKind`、`codeSourceKind`、warnings、lease/canRun 等结构化事实 |
| 第三阶段：UI 调整 | 已执行 | 项目页按 project workspace 展示代码来源与各自执行模式；无 workspace 时展示组织草稿状态 |
| 第四阶段：Shared Workspace 实现目标 | 已执行 | 项目 cwd 直用；repoUrl-only 创建并复用 managed checkout；无项目或未配置 project workspace 时显式解析为 organization scratch；已配置 workspace 但缺少 cwd/repoUrl 时拒绝执行 |
| 第五阶段：Isolated Workspace 实现目标 | 部分完成 | 已禁止 local_fs fallback；仍需补齐 repoUrl-only/managed checkout/worktree 测试 |
| 第六阶段：Operator Branch 后续计划 | 未开始 | 等 Shared/Isolated 稳定后再讨论 |

## 2. 第一阶段：清理 Shared 错误模型

### 2.1 必须删除或迁移

- 删除 shared 模式下“每个任务一个执行目录”的创建逻辑。
- 删除 shared 模式下以 workspace cwd 为 scope 的长时间 write lease。
- 删除 shared 模式下基于 workspace lease 的排队和阻塞文案。
- 删除把 issue artifacts 目录、organization scratch 目录展示或持久化成 shared execution cwd 的逻辑。
- 删除把无 project / 无代码来源 fallback 命名为 shared workspace 的 UI/API 文案。

### 2.2 必须保留

- issue checkout / execution lock：只解决同一个 issue 重复执行的问题。
- agent/run 队列：只解决同一个 agent 或 runtime 并发能力的问题。
- runtime service lease：只解决 dev server 等服务的复用和释放。
- workspace operation logs：继续记录 worktree prepare、provision、cleanup、命令执行结果。
- isolated workspace 的 issue 级 Git worktree 执行目录。

### 2.3 验收标准

- shared 模式下，同一项目的不同 issue 不再产生不同 execution cwd。
- shared 模式下，数据库不再出现以任务为粒度的 shared execution workspace 目录。
- shared 模式下，任务运行不会因为另一个任务持有 workspace write lease 而等待。
- shared 模式下，`OCTOPUS_WORKSPACE_CWD` 直接等于项目主 cwd 或 managed checkout cwd。
- 同一个 issue 的重复执行仍然受 issue checkout / execution lock 保护。

## 3. 第二阶段：统一 Preflight/API 事实输出

### 3.1 新增或收敛字段

每次 workspace preflight / runtime context 至少输出：

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

### 3.2 验收标准

- UI 不再需要从 `cwd` 或 mode 猜 workspace 语义。
- organization scratch 不会被 API 标记为项目 shared workspace。
- issue artifacts 不会被 API 标记为 execution workspace cwd。
- `providerType=git_worktree` 时，目录必须能被 Git 原生命令验证为 worktree。

## 4. 第三阶段：UI 调整

### 4.1 项目页信息架构

项目页按以下顺序展示：

```text
基础信息
  - 项目名称 / 标识 / 描述
  - 保存项目只保存项目自身字段

项目工作区
  - 每个工作区展示 cwd / repoUrl / ref / 是否默认
  - 每个工作区独立保存 shared / isolated / operator 模式
  - 添加工作区时一次保存代码来源和该来源的执行模式

任务运行记录
  - 展示 projectWorkspaceId / resolved mode / execution cwd
```

### 4.2 无代码来源文案

当 project 没有主工作区、没有 cwd、也没有 repoUrl 时，UI 应展示：

```text
未配置项目主工作区
请设置本地 cwd 或仓库 URL，才能启用共享工作区、独立工作区或操作分支。
当前仍可运行无代码任务，但它们只会使用组织草稿目录，不会基于项目代码执行。
```

没有 project workspace 时不展示三模式选择器。三种模式只在新增或编辑具体工作区时出现。

### 4.3 有 repoUrl 但没有 cwd 文案

```text
首次运行会创建受管 checkout
Octopus 会从仓库 URL 创建一次项目主工作区，后续执行策略会基于这个 checkout 运行。
```

不要把 managed checkout 描述成 artifacts 或组织共享工作区。

### 4.4 禁止使用的误导文案

- “暂无项目工作区。任务运行时会使用组织共享工作区。”
- “未设置本地 cwd，运行时使用组织共享工作区。”
- “当前项目没有可用的本地项目工作区；任务运行会 fallback 到组织共享工作区。”

替代原则：

- 对项目代码任务：提示“先配置项目主工作区”。
- 对无项目/无代码任务：提示“将使用组织草稿目录”。
- 对 artifacts：只称“产物目录”，不称“工作区”。

## 5. 第四阶段：Shared Workspace 实现目标

### 5.1 目标行为

| 场景 | 目标处理 |
| --- | --- |
| shared + 有项目主 cwd | `OCTOPUS_WORKSPACE_CWD` 直接等于项目主 cwd |
| shared + repoUrl-only | 先创建 managed project checkout，再把 checkout cwd 作为 shared cwd |
| shared + 无 project | 不进入 shared；显式标记为 organization scratch |
| shared + 无代码来源 | 不进入 shared；要求配置项目主工作区或 repoUrl |

### 5.2 约束

- 不自动 `git checkout` / `git switch` / `git reset` / rebase。
- 不按 issue 创建 execution workspace cwd。
- 不创建 workspace 级长锁或基于 workspace lease 的排队。
- 每个 issue 仍可有独立 `OCTOPUS_ISSUE_ARTIFACTS_DIR`。

### 5.3 实施结果

- shared + 项目 cwd：直接输出项目 cwd，workspaceKind=project_execution、codeSourceKind=local_cwd。
- shared + repoUrl-only：创建并跨 issue 复用 managed checkout，codeSourceKind=managed_checkout。
- 无项目或项目未配置 workspace：输出 mode=organization_scratch，不再输出 mode=shared_workspace。
- 已配置 workspace 但 cwd/repoUrl 都为空：preflight 明确拒绝，要求先配置代码来源。
- chat 无主任务时同样使用 organization scratch；agent heartbeat 使用独立的 agent_scratch。
- Shared 场景不要求 workspace lease，任务产物继续写入 issue 独立产物目录。

## 6. 第五阶段：Isolated Workspace 实现目标

### 6.1 目标行为

| 场景 | 目标处理 |
| --- | --- |
| isolated + Git 项目 cwd | 每个 issue 创建或复用 Git worktree |
| isolated + repoUrl-only | 先创建 managed checkout，再从 checkout 创建 issue worktree |
| isolated + 非 Git cwd | isolated 不成立；提示配置 Git repo 或 repoUrl |
| isolated + 无代码来源 | 不进入 isolated；要求配置项目主工作区或 repoUrl |

### 6.2 约束

- 正常 isolated 基于 `git_worktree`。
- 不得把普通目录标记为 `git_worktree`。
- 不得把普通 local_fs 目录包装成正常 isolated。
- 同一个 issue 的重试、恢复和后续 run 复用同一个 execution workspace。
- 不同 issue 的 worktree 可以并行。

## 7. 第六阶段：Operator Branch 后续计划

operator_branch 暂时不在本轮清理中展开实现。讨论和开发必须建立在 Shared 和 Isolated 语义已经收敛之后。

待讨论问题：

- operator branch 是否自动创建固定 worktree。
- operator branch 的分支命名、配置入口和复用范围。
- 多个 issue 共享 operator cwd 时的串行控制 scope。
- push、PR、merge、cleanup 是否作为显式动作。
- operator branch 与 shared / isolated 的 UI 区分方式。

当前计划只保留两条原则：

- operator_branch 必须基于项目 Git 来源或 repoUrl。
- operator_branch 不能复用 shared workspace 长锁语义。

## 8. 开发顺序检查清单

1. 清理 shared 每任务目录、workspace 长锁、workspace lease 队列。
2. 修正无 project / 无代码来源 fallback 的 API 语义和 warning。
3. 增加或收敛 preflight/API 事实字段。
4. 调整 UI 信息架构和误导文案。
5. 修正 shared runtime cwd 解析。（已完成）
6. 修正 isolated Git worktree 创建、复用和校验。
7. 把 execution policy 从 projects 迁到 project_workspaces，并删除项目级字段和兼容逻辑。
8. 补测试覆盖多工作区不同模式、默认工作区选择、shared / isolated / no project / repoUrl-only / non-Git cwd。
9. 在 Shared 和 Isolated 稳定后，再讨论 operator_branch。
