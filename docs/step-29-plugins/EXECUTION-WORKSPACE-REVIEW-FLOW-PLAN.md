# Execution Workspace Review Flow Plan（1-5）

## 背景

当前已经完成第一层基础能力：执行工作区可查询、可查看 Git 状态、可查看 diff、可 push 分支、可安全 archive。下一步需要把这些基础动作升级成完整的“任务结果审核与 Git 归并流程”。

这个阶段要解决的核心问题不是再新增零散按钮，而是回答：

- 三种 workspace 模式下，任务产物如何进入 Git 主流程？
- 如何避免系统私自切换主工作区分支？
- 如何在 merge / push / PR / abandon 之间建立明确、可审计的选择？
- 如何保证 cleanup 不误删主工作区、不丢任务成果？

## 目标

完成执行工作区从“任务运行目录”到“可审核、可合并、可推送、可清理”的闭环。

必须支持三种模式：

1. `shared_workspace`
2. `isolated_workspace`
3. `operator_branch`

并且三种模式都必须显式支持 Git 安全检查，而不是隐式 checkout 或默认 merge。

## 非目标

本阶段不做以下事情：

- 不实现完整 GitHub App / GitLab App 集成。
- 不默认自动创建远端 PR；仅在用户显式点击“创建 PR”时调用本机 `gh pr create`。
- 不默认把每个 issue 自动 merge 到 main。
- 不改变项目主工作区分支。
- 不把 heartbeat 纳入会改 Git 状态的流程。

## 1. Merge / PR 审核流

### 目标

用户在任务完成后，可以从执行工作区面板完成明确选择：

- 查看 diff
- 生成 merge preview
- merge 到目标分支
- push 任务分支
- 创建 PR 或输出 PR 创建指令
- abandon / archive

### 模式行为

#### shared_workspace

- 不创建隔离 worktree。
- 任务直接在项目主工作区执行。
- UI 必须显示“共享工作区风险”：多个任务可能污染同一目录。
- 不提供“从任务 worktree merge 回主目录”的动作，因为本来就在主目录。
- 可以提供 status / diff / push，但必须基于当前主工作区 Git 状态。

#### isolated_workspace

- 每个任务有独立 git worktree。
- 默认不 merge。
- 用户审核 diff 后可以选择：
  - merge 到目标分支
  - push 当前任务分支
  - 创建 PR
  - abandon / archive
- merge 前必须校验目标分支、dirty 状态、运行 lease、冲突风险。

#### operator_branch

- 使用任务或 operator 对应的稳定分支。
- 默认推荐 push / PR。
- 不默认 merge 到 main。
- 允许用户显式选择 merge，但必须走同样的 merge preview 和分支保护。

### 后端能力

新增 service 方法：

- `merge_preview(workspace_id, target_ref)`
  - 使用 `git merge-tree` 或等价方式预检查冲突。
  - 返回是否可 clean merge、冲突文件、摘要。

- `merge_workspace(workspace_id, target_ref, strategy)`
  - 只允许在明确目标分支下执行。
  - 必须检查 execution workspace 当前分支和 expected branch 一致。
  - 必须检查目标工作区不是 dirty。
  - 必须检查该 workspace 没有 running lease。
  - 失败时不得改变目标分支状态。

- `prepare_pull_request(workspace_id, remote)`
  - 至少返回 PR 创建所需信息：source branch、target branch、remote、URL 或命令。
  - 如果当前环境支持 `gh`，后续可扩展为自动创建 PR。

新增 API：

- `POST /api/execution-workspaces/{id}/merge-preview`
- `POST /api/execution-workspaces/{id}/merge`
- `POST /api/execution-workspaces/{id}/prepare-pr`
- `POST /api/execution-workspaces/{id}/create-pr`

## 2. 分支安全保护

### 目标

彻底避免“系统私自切换项目主工作区分支”的问题。

### 必须实现

每个执行工作区记录：

- `expectedBranch`
- `baseRef`
- `targetRef`
- `sourceWorkspaceCwd`
- `createdFromHead`
- `createdFromBranch`

每次执行 Git 写操作前检查：

- 当前 cwd 是否是预期 workspace。
- 当前 branch 是否等于 expected branch。
- 操作目标是否是允许的 target ref。
- 主工作区当前分支是否被本流程改变。

如果发现不一致：

- 阻断操作。
- 写入 workspace operation log。
- UI 显示红色风险状态。

### 禁止事项

- heartbeat 不得执行 `git checkout`。
- 无任务上下文不得切换项目主工作区分支。
- cleanup 不得为了删除 worktree 去 checkout main。
- merge 不得隐式切换用户当前主工作区分支。

## 3. Cleanup / Abandon 生命周期

### 目标

让任务目录可控地清理，不误删、不丢成果。

### 状态流

建议状态：

- `active`
- `review_ready`
- `pushed`
- `merged`
- `archived`
- `abandoned`
- `cleanup_failed`

### archive / abandon 规则

允许 archive：

- workspace 没有 running lease。
- workspace 不 dirty，或用户明确选择 discard。
- workspace 不是项目主工作区。
- workspace 是 Git worktree 时，从源仓库执行 `git worktree remove`。

不允许 archive：

- shared workspace 的主目录。
- dirty 但用户未确认 discard。
- 有运行中 lease。
- cwd 不在 managed workspace root 且未显式标记安全。

新增 API：

- `POST /api/execution-workspaces/{id}/abandon`
- `POST /api/execution-workspaces/{id}/cleanup`

其中：

- `abandon` 表示业务上放弃任务结果。
- `cleanup` 表示物理清理目录。
- 二者可以组合，但不能混为一个不透明动作。

## 4. UI 审核动作增强

### 目标

把当前“执行工作区”面板升级为可操作的审核面板。

### 页面入口

项目配置页保留基础入口，但更推荐在 issue 详情页也展示当前 issue 对应的 execution workspace。

项目配置页显示：

- 全项目执行工作区列表。
- 每个 workspace 的模式、分支、状态、dirty、lease、最后更新时间。

Issue 详情页显示：

- 当前 issue 对应 workspace。
- 当前任务 diff。
- merge preview。
- push / PR / merge / abandon 操作。

### UI 动作

每个 workspace 的动作按状态显示：

- `查看 diff`
- `检查 merge`
- `merge 到目标分支`
- `push 分支`
- `准备 PR`
- `创建 PR`
- `放弃任务结果`
- `清理目录`

危险动作必须明确文案：

- abandon：放弃任务结果，但可选择是否保留目录。
- cleanup：删除执行目录。
- merge：会把任务分支合入目标分支。

## 5. 测试矩阵

### 后端 contract 测试

必须覆盖：

- shared workspace 不创建隔离 worktree。
- isolated workspace 创建独立 worktree。
- operator branch 使用稳定分支。
- heartbeat 不执行 checkout。
- archive 不删除主工作区。
- dirty workspace 默认不能 archive。
- running lease workspace 不能 archive。
- merge preview 可以识别 clean merge。
- merge preview 可以识别 conflict。
- merge 操作不会私自切 main。
- push branch 使用当前 workspace branch。

### 前端测试

必须覆盖：

- 项目页能显示 execution workspace 面板。
- 接口异常或返回非数组时页面不崩。
- dirty 状态显示正确。
- running lease 禁用 archive / merge。
- merge preview 结果能显示。
- 危险操作按钮有明确文案。

### 手工验证场景

使用示例项目：

- 主工作区：`D:\coding\test\mytest`
- 仓库：`https://github.com/cliffordll/mytest.git`

验证：

1. shared 模式下任务在主工作区运行，不创建 worktree。
2. isolated 模式下任务在 `.octopus/worktrees/...` 下运行。
3. operator 模式下任务使用稳定 operator 分支。
4. 当前主工作区分支保持用户原本分支，不被切到 main。
5. 用户审核后可以 push 或 merge。
6. cleanup 不删除 `D:\coding\test\mytest`。

## 推荐开发顺序

### Phase 1：分支安全基础

- 给 execution workspace metadata 补 expected branch / target ref。
- 所有 Git 写操作前增加 branch guard。
- 禁止 heartbeat checkout。
- 补 contract 测试。

验收标准：

- 任何无任务流程不能改变项目主工作区分支。
- 如果当前 branch 与 expected branch 不一致，操作被阻断。

### Phase 2：merge preview

- 实现 `merge_preview` service。
- 新增 API。
- UI 展示 preview 结果。

验收标准：

- clean merge / conflict 都能被识别。
- preview 不改变任何分支。

### Phase 3：显式 merge

- 实现 `merge_workspace`。
- 只允许用户显式触发。
- merge 失败不破坏目标工作区。

验收标准：

- isolated workspace 可以在审核后 merge。
- operator branch 不会默认 merge。
- shared workspace 不展示无意义 merge。

### Phase 4：PR / push 流程

- push 已有基础能力，补状态记录。
- prepare PR 返回 source / target / command / URL。
- UI 增加 PR 指引。

验收标准：

- 用户可以明确知道应该从哪个分支向哪个目标分支开 PR。

### Phase 5：cleanup / abandon 完整化

- 拆分 abandon 和 cleanup。
- 加 discard dirty 的显式确认参数。
- 完善 operation log。

验收标准：

- 不误删主工作区。
- 不默默丢弃 dirty 改动。
- cleanup 失败有可诊断记录。

## 完成定义

本阶段完成后，应能回答并验证：

- 三种模式下任务产物在哪里。
- 三种模式下任务结果如何进入 Git。
- 哪些场景允许 merge。
- 哪些场景只能 push / PR。
- 为什么主工作区分支不会被私自切换。
- cleanup 删除的是哪个目录。
- abandon 是否会丢弃未提交改动。

## 当前实现状态

已完成首轮闭环实现：

- Phase 1 分支安全基础：execution workspace metadata 记录 `expectedBranch`、`targetRef`、`createdFromHead`、`createdFromBranch`；push / archive / merge / prepare PR 前执行 branch guard。
- Phase 2 merge preview：新增 service 和 API，支持 clean merge / conflict 预检，不 checkout、不改变分支。
- Phase 3 显式 merge：新增显式 merge API；仅当目标分支已经是项目工作区当前分支时执行，Octopus 不自动 checkout。
- Phase 4 PR / push：保留 push，新增 prepare PR 信息输出，包括 source branch、target ref、compare URL / gh 命令；新增显式创建 PR API，用户点击后调用本机 `gh pr create`，不会自动创建。
- Phase 5 cleanup / abandon：新增 abandon 与 cleanup API；shared workspace 禁止 cleanup；dirty cleanup 需要显式 discard 参数。
- UI：项目配置页执行工作区面板新增检查 merge、merge 到目标分支、准备 PR、创建 PR、push、放弃结果、清理目录动作；dirty cleanup 必须先勾选“确认丢弃未提交改动”。
- Issue 详情页：新增 issue-scoped execution workspace 审核入口，可直接查看当前任务工作区并执行 diff / merge preview / merge / PR / push / abandon / cleanup；同样提供 dirty cleanup 显式确认。
- Tests：补充 metadata / branch guard / merge preview clean-conflict / merge-PR-create-abandon-cleanup contract 测试。

仍未完成或后续增强：

- GitLab PR/MR 自动创建尚未实现。
- GitHub PR 创建当前依赖本机 `gh` 已安装、已登录且有仓库权限；完整 GitHub App 集成仍属于后续增强。

## 风险点

- Windows git worktree 删除容易受当前进程 cwd 影响，必须从 source workspace 执行 remove。
- merge 操作如果直接 checkout target branch，会复发“私自切分支”问题；必须设计成明确目标和安全 guard。
- shared workspace 天然不隔离，UI 必须明确提示，而不是伪装成 isolated。
- operator_branch 容易被误解为自动 merge；默认应偏向 push / PR。
