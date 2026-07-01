# 三种执行工作区模式优化开发计划

状态：待实施  
日期：2026-06-29  
实施分支：`step-29-plugins`  
职责归属：Step 15 Workspace

## 1. 目标

补齐 `shared_workspace`、`isolated_workspace`、`operator_branch` 三种模式从策略解析、真实目录准备、Git 关联、并发保护、失败恢复到清理审计的完整执行闭环。

本计划以 Octopus 为主要实现项目。`D:\coding\upstream-reference` 只作为只读参考证据，不要求先修改上游，也不照搬上游尚未完成的行为。

当前实现已经具备模式枚举、execution workspace 数据结构、issue/run/workspace 关联、runtime context/env 注入和 work product 登记能力，但仍存在关键缺口：

- `isolated_workspace` 和 `operator_branch` 目前主要计算目标路径和分支名。
- `_ensure_managed_workspace_paths()` 只执行目录创建，没有执行 `git worktree add`。
- 标记为 `git_worktree` 的目录可能实际上只是普通目录。
- `operator_branch` 仍按 issue 范围复用，无法表达固定长期 operator 分支。
- 缺少共享目录和 operator 分支的写租约。
- 缺少 dirty workspace、未合并提交和冲突状态下的安全清理规则。
- 项目只有 `repoUrl`、没有本地 `cwd` 时，没有受管 checkout 的准备流程。

## 2. 冻结的模式契约

以下定义在实施期间保持稳定，不再根据实现便利改变语义。

| 模式 | 执行目录 | 分支规则 | 复用范围 | 并发规则 |
| --- | --- | --- | --- | --- |
| `shared_workspace` | 项目主工作区 `cwd` | 使用主工作区当前分支，不自动切换 | 项目工作区 | 同一工作区写任务串行 |
| `isolated_workspace` | issue 独立 worktree | issue 首次解析时创建固定分支，后续 run 永久复用 | 单个 issue | 不同 issue 可并行 |
| `operator_branch` | 固定 operator worktree | 使用项目配置的固定长期分支，不按 issue 创建新分支 | 项目 + operator 分支 | 同一 operator workspace 串行 |

### 2.1 不可违反的分支安全规则

- Octopus 不得自动对项目主工作树执行 `git checkout`、`git switch`、`git reset` 或 rebase。
- `shared_workspace` 如果配置了期望分支，而主工作树当前分支不同，preflight 必须失败并给出可解释错误，不能代替用户切换。
- isolated issue 的分支名一经写入 execution workspace，不因标题、策略、重试或后续 run 改名。
- operator 分支由项目策略明确配置；同一 operator workspace 不创建 task 子分支。
- 修改项目策略只影响尚未绑定 execution workspace 的新任务；已有任务继续使用原 workspace 和分支。
- merge、push、PR、删除分支均是独立的显式动作，run 成功不等于已合并。

### 2.2 典型目录

项目主工作区：

```text
D:\coding\test\mytest
```

默认本地 worktree：

```text
D:\coding\test\mytest\.octopus\worktrees\octopus-PROJ-123
D:\coding\test\mytest\.octopus\worktrees\feature-full-stack
```

`worktreeParentDir` 允许配置为项目目录外的绝对路径。使用项目内 `.octopus` 时，应写入仓库本地 `.git/info/exclude`，不得擅自修改用户版本化的 `.gitignore`。

## 3. 工作区策略与 Git 策略的边界

三种模式是用户可见的执行预设，但内部需要明确区分：

- workspace mode：决定使用主目录、issue 独立目录还是固定 operator 目录。
- workspace strategy：决定目录由 `project_primary`、`git_worktree`、`local_fs` 或 adapter-managed provider 提供。
- branch policy：决定 base branch、issue branch template 和固定 operator branch。
- pull request policy：决定是否允许 push/PR 以及需要何种 approval。
- cleanup policy：决定何时允许归档、是否保留失败现场和是否删除分支。

推荐策略结构：

```json
{
  "enabled": true,
  "defaultMode": "isolated_workspace",
  "allowIssueOverride": true,
  "workspaceStrategy": {
    "type": "git_worktree",
    "baseRef": "main",
    "branchTemplate": "octopus/{issueIdentifier}",
    "worktreeParentDir": null,
    "provisionCommand": null,
    "teardownCommand": null
  },
  "branchPolicy": {
    "baseBranch": "main",
    "operatorBranch": "feature/full-stack",
    "allowExistingBranchReuse": true
  },
  "pullRequestPolicy": {
    "mode": "manual",
    "targetBranch": "main",
    "approvalRequired": true
  },
  "cleanupPolicy": {
    "mode": "manual",
    "retainFailedWorkspace": true,
    "deleteMergedIssueBranch": false
  }
}
```

兼容处理：

- 保留 `project_primary`、`isolated` 等历史别名的读取兼容。
- 兼容旧 UI 写入的 `workspaceStrategy.mode`，但保存时统一输出 `workspaceStrategy.type`。
- 旧 execution workspace 如果声明为 `git_worktree` 但目录不是有效 Git worktree，不能继续复用；preflight 应报告修复原因并创建新 workspace 或要求人工处理。

## 4. 无主工作区目录时的规则

### 4.1 有 `repoUrl`、没有 `cwd`

Octopus 应创建受管 project checkout，并将生成的本地路径持久化回 project workspace，再按模式解析：

- shared：使用受管主 checkout。
- isolated：从受管主 checkout 创建 issue worktree。
- operator：从受管主 checkout创建或挂载固定 operator 分支。

受管 checkout 路径必须由统一 workspace path service 生成，不能由 route、runtime adapter 或 agent 自行拼接。

### 4.2 没有 `repoUrl`、也没有 `cwd`

- shared：允许回退到组织共享 workspace，并记录明确 warning；provider 必须是 `local_fs` 或 `organization_workspace`。
- isolated：创建 issue 独立的受管 `local_fs` execution workspace。
- operator：preflight 失败，因为没有 Git 仓库或远程分支来源。

任何 fallback 都不得将普通目录标记为 `git_worktree`。

## 5. 服务端架构调整

避免继续把所有职责堆入 `server/services/workspaces.py`。计划拆分为：

### 5.1 `workspace_policy.py`

负责：

- 规范化 project/issue policy。
- 解析最终 mode、strategy、base ref、branch name 和 reuse scope。
- 固化已有 execution workspace 的分支和目录。
- 对不合法组合返回结构化 preflight 错误。

### 5.2 `workspace_git.py`

负责：

- 使用参数数组调用 Git，禁止拼接 shell 命令。
- 设置 timeout、stdout/stderr 上限和安全环境。
- 查询 repo root、当前分支、HEAD、worktree list、dirty 状态和 remote。
- 创建、挂载、验证和移除 worktree。
- 不提供自动切换项目主工作树分支的接口。

### 5.3 `workspace_lifecycle.py`

负责：

- prepare、reuse、archive、cleanup 的文件系统生命周期。
- 在文件系统成功后持久化 execution workspace。
- 数据库持久化失败时回滚本次新建 worktree。
- 执行 provision/teardown command。
- 记录 `worktree_prepare`、`workspace_provision`、`workspace_teardown`、`worktree_cleanup` operation。

### 5.4 `workspaces.py`

保留：

- issue/project/run 的业务关联。
- runtime context/env 构造。
- runtime services、operations 和 work products 编排。
- 调用 policy 与 lifecycle 服务，不直接执行 Git 细节。

## 6. 各模式执行流程

### 6.1 Shared workspace

```text
resolve project workspace
  -> verify cwd exists and is writable
  -> if Git expectations exist, verify repo and current branch
  -> acquire project-workspace write lease
  -> run adapter directly in project cwd
  -> release lease
```

规则：

- 非 Git 项目也可以使用 shared。
- 不创建 branch 或 worktree。
- 不自动 merge，因为改动已经发生在主工作区。
- 多个写任务不得同时执行；只读任务并发属于后续能力，不在第一版推断。

### 6.2 Isolated workspace

```text
resolve project Git workspace
  -> reuse issue-bound execution workspace when valid
  -> otherwise freeze branch name and base ref
  -> create or attach git worktree
  -> run provision command
  -> persist workspace and bind issue
  -> run adapter in issue worktree
```

规则：

- 一个 issue 对应一个稳定分支和 worktree。
- 同一 issue 的重试、恢复和后续 run 必须复用。
- 不同 issue 可以并行。
- run 完成后 workspace 默认保留，等待 review、显式合并或放弃。

### 6.3 Operator branch

```text
resolve configured operator branch
  -> find active workspace by project + project workspace + branch
  -> create or attach one operator worktree when absent
  -> bind issue to existing operator workspace
  -> acquire operator-workspace write lease
  -> run adapter
  -> release lease
```

规则：

- operator 分支固定，不按 issue 生成。
- 多个相关 issue 可以绑定同一个 operator workspace。
- 同一 operator workspace 的写任务必须串行。
- 不自动为 server/UI/CLI 任务创建子分支。
- operator 分支的 push、PR 和 merge 由显式策略或操作触发。

## 7. 并发与租约

需要提供数据库可恢复的 workspace write lease，不能只依赖进程内锁。

租约至少包含：

- workspace scope/id
- owner run id
- acquired/heartbeat/expires timestamps
- release reason

要求：

- shared 与 operator 在 adapter 执行前获取写租约。
- isolated workspace 天然按 issue 隔离，但同一 issue 的重复 run 仍需防止并发写。
- server 重启后过期租约可恢复。
- 竞争失败应保持 run queued 或返回明确冲突，不得静默进入同一目录。

第一版可以复用 execution workspace + run 的原子状态更新实现租约；若现有字段无法保证跨数据库原子性，再增加专用 lease 表和 migration。

## 8. Git 集成和状态记录

Execution workspace 需要可追踪以下事实：

- repo root / repo URL
- base ref / base commit
- branch name / head commit
- worktree path
- current dirty state
- remote/upstream
- created by runtime / reused existing branch
- last verified timestamp

优先保留现有上游兼容列，扩展事实先写入 `metadata.git`；只有需要索引、过滤或事务约束的字段才新增数据库列。

本计划不默认自动 merge。后续显式集成动作必须满足：

- 测试和 review gate 已通过。
- merge 目标明确。
- 主工作区 clean。
- 发生冲突时停止并保留现场。
- 远程 PR 合并后，本地主工作区只允许显式 safe fast-forward，不自动 checkout/reset。

## 9. 清理和恢复

清理前必须检查：

- workspace 是否 dirty。
- 是否存在未推送提交。
- isolated 分支是否已合并或明确放弃。
- operator workspace 是否仍被其他活跃 issue 使用。
- runtime services 是否已停止。

规则：

- dirty worktree 不自动删除。
- failed、blocked、conflict workspace 默认保留。
- 不默认使用 `git worktree remove --force`。
- 分支删除与 worktree 删除是两个独立动作。
- `cleanup_failed` 必须保存原因，并允许重试。
- cancel/recovery 先释放租约和 ephemeral services，再决定是否清理文件系统。

## 10. 产出物边界

代码和项目内生成物：

- shared 写入项目主工作区。
- isolated 写入当前 issue worktree。
- operator 写入固定 operator worktree。

正式交付物：

- 报告、截图、CSV、handoff 文档继续写入 `OCTOPUS_ORG_ARTIFACTS_DIR`。
- `issue_work_products` 继续通过 `issue_id`、`created_by_run_id`、`execution_workspace_id` 关联。
- isolated 只扫描当前 issue worktree。
- shared 只扫描 `artifacts/issues/<issueId>` 范围。
- 不扫描整个组织 artifacts root 并归属给单个任务。

Workspace 模式变化不得改变 work product 的任务归属语义。

## 11. API 与 UI

### 11.1 API

补齐 execution workspace 的：

- list/detail
- prepare/verify
- Git status/diff
- archive/cleanup/retry cleanup
- lease 状态
- operation/log 查询

push、PR、merge 放在后续显式集成 API 中，不和 run success 隐式绑定。

### 11.2 UI

项目设置：

- 三种模式的稳定说明。
- base branch、branch template、operator branch 和 worktree parent。
- PR 与 cleanup 高级策略。
- 无 cwd 但有 repoUrl 时的受管 checkout 状态。

Issue / execution workspace 页面：

- mode、cwd、repo、branch、base/head commit。
- 是否为真实 Git worktree。
- dirty、lease、review、cleanup 状态。
- 查看 operation/log。
- 危险清理动作需要确认。

UI 文案不得暗示 Octopus 会自动切换项目主分支或自动合并。

## 12. 实施阶段

### 阶段 A：契约与失败测试

- 固化三种模式表和策略 validators/types。
- 增加真实临时 Git 仓库测试，先证明当前普通目录不是 worktree。
- 增加“主工作树分支不得变化”的回归测试。
- 更新 Step 15 文档中与真实行为不一致的完成声明。

### 阶段 B：真实 Git worktree lifecycle

- 新增 policy/git/lifecycle 服务。
- isolated 创建并复用真实 worktree。
- operator 按固定分支创建并复用真实 worktree。
- 文件系统与数据库失败回滚。
- operation 记录和 runtime context 对齐。

### 阶段 C：无 cwd provisioning 与并发保护

- repoUrl-only 项目创建受管 checkout。
- non-Git fallback 按模式处理。
- shared/operator/same-issue 写租约。
- recovery 释放过期租约。

### 阶段 D：清理、API 与 UI

- 安全 archive/cleanup。
- workspace Git 状态与日志 API。
- 项目策略和 workspace 状态 UI。
- 真实用户流程 E2E。

### 阶段 E：显式集成能力

- push 与 upstream tracking。
- PR provider integration。
- review gate 后的显式 local merge 或 PR merge 状态同步。
- conflict 保留与恢复。

阶段 E 不阻塞前三种执行模式正确落地，但属于完整代码交付闭环的一部分。

## 13. 重点修改范围

- `packages/shared/constants/workspace.py`
- `packages/shared/types/workspace.py`
- `packages/shared/validators/project.py`
- `packages/shared/validators/issue.py`
- `packages/shared/validators/workspace.py`
- `packages/database/schema/workspaces.py`
- `packages/database/queries/workspaces.py`
- `packages/database/migrations/versions/`
- `server/services/workspaces.py`
- `server/services/workspace_policy.py`（新增）
- `server/services/workspace_git.py`（新增）
- `server/services/workspace_lifecycle.py`（新增）
- `server/services/workspace_paths.py`
- `server/services/heartbeat.py`
- `server/routes/projects.py`
- execution workspace routes（新增或补齐）
- `ui/src/pages/ProjectPage.tsx`
- issue/execution workspace UI 与 API types
- `tests/contract/test_step15_workspace_contract.py`
- workspace workflow 和 UI E2E tests

现有 `server/plugins/git_worker.py` 继续承担 agent 显式 Git 工具调用，不负责 run preflight 的受管 worktree 创建；preflight lifecycle 必须由 server 自己保证，不能依赖 agent 是否调用工具。

## 14. 验收标准

### Shared

- cwd 精确等于配置的项目主工作区。
- preflight 前后项目主工作树分支不变。
- 非 Git 目录可运行。
- 两个写 run 不会同时进入同一 shared cwd。

### Isolated

- 目录通过 `git worktree list` 可验证。
- 不同 issue 获得不同固定分支和目录。
- 同一 issue 的多次 run 复用相同分支和目录。
- 策略或标题变化不会修改已绑定分支。
- isolated 改动不会在显式 merge 前出现在项目主工作区。

### Operator

- operator branch 由项目配置固定。
- 多个 issue 复用同一个 execution workspace。
- 不创建 issue 子分支。
- 并发写 run 被租约串行化。
- 项目主工作树分支始终不变。

### Missing cwd

- repoUrl-only 项目获得受管 checkout。
- 无 repo/cwd 的 shared 和 isolated 使用正确的 non-Git provider。
- 无 repo/cwd 的 operator 在 adapter 启动前失败。
- fallback 不会声明为 `git_worktree`。

### Cleanup and products

- dirty workspace 不被自动删除。
- active issue 或 lease 阻止 archive。
- cleanup failure 可见且可重试。
- 三种模式下 work products 均保持正确 issue/run/workspace 关联。

### Repository validation

交付前执行：

1. `uv run ruff check .`
2. `uv run ruff format --check .`
3. `uv run pytest`
4. `uv run pyright .`
5. `npm test`（`ui/`）
6. `npm run build`（`ui/`）
7. 真实 Git 仓库和 Windows 路径 E2E

## 15. 风险与恢复

- 当前 `server/services/workspaces.py` 已有未完全闭环的路径/分支改动，实施时必须保留有效部分并替换伪 worktree 行为，不能回退 work product 修复。
- 项目主工作树可能有用户未提交修改；所有自动化都必须以“不切分支、不 reset、不覆盖”为默认。
- Git 分支可以存在但 worktree 缺失，必须支持安全重新挂载，不能重建或重置分支。
- operator workspace 被多个 issue 引用，清理必须检查所有引用，不能只检查 `source_issue_id`。
- SQLite、PostgreSQL、MySQL 的租约实现需要一致的原子竞争语义。
- 旧数据可能包含 providerType 与实际目录不一致的记录，需要验证和渐进修复，不能假设全部有效。

## 16. 非目标

- 不自动切换用户项目主工作树分支。
- 不自动 reset/rebase 用户分支。
- 不默认自动 merge 或自动删除分支。
- 不在第一阶段实现任意非 Git 目录的增量复制隔离。
- 不把正式 artifacts 强制提交到 Git。
- 不修改 upstream reference 上游参考仓库。

## 17. 完成定义

三种模式只有同时满足以下条件才视为完成：

- UI 选择的模式与实际 cwd、provider 和分支一致。
- Git worktree 可以由 Git 原生命令验证，不是普通目录模拟。
- 主工作树分支在整个 run 生命周期中保持不变。
- 重试、并发、失败、取消和恢复不会产生重复 workspace 或破坏用户改动。
- workspace 清理不会静默丢失未提交或未合并内容。
- work products 始终保持任务级关联。
- 自动化测试覆盖真实 Git 生命周期及主要失败路径。
