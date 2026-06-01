---
name: octopus-worktree-preview-maintainer
description: >
  把当前 Octopus checkout 作为临时托管预览启动，验证就绪，并交给用户稳定 URL、日志和停止命令。当用户要求运行当前分支、“把当前分支跑起来”“运行起来我自己测试下”“本地看一下效果”或想要后台 preview handoff 时使用。不要把它作为 Codex worktree 隔离的默认机制；`pnpm dev` 已经会自动隔离 Codex-managed worktrees。
---

# Octopus Worktree Preview Maintainer

把当前 Octopus checkout 作为临时 preview 运行，让用户在浏览器中检查 feature，而不需要留下前台命令。

该技能用于实现后的常见交接：分支已经包含改动，用户想要本地 URL 测试。它不是 PR checkout 流程，不是宽泛进程清理流程，也不是 Codex-managed worktrees 的标准开发环境。

Octopus 正常 `pnpm dev` 入口是 canonical development path。在 `~/.codex/worktrees/<id>/<repo>` 下的 Codex-managed worktree 中，如果没有 repo-local `.octopus/` config，`pnpm dev` 会自动派生隔离的 `OCTOPUS_HOME`、instance id、server port、embedded PostgreSQL port 和 worktree branding。只有当用户需要托管后台 preview handoff、health 验证、日志和停止命令时才用本技能。

## 使用场景

- 用户要求运行当前分支或当前 worktree。
- 用户想手动测试最近实现的 UI 或 workflow 改动。
- 实现后需要交付稳定 preview URL，且不留下前台 `pnpm dev`。
- 用户要日志、停止命令或可独立清理的临时 preview。
- 任务是提供 preview URL，而不是打包 Desktop 或发布 release。

## 不使用场景

- 用户要求 checkout 或 preview GitHub PR；用 `pr-local-preview-maintainer`。
- 用户只要求停止或清理本地 dev 进程；用 `stop-octopus-dev-maintainer`。
- 用户问 Codex worktree 为什么干扰、正常开发如何隔离，或 `pnpm dev` 是否使用当前 worktree。应检查 `scripts/dev-local-env.mjs`、`doc/DEVELOPING.md` 和 `/api/health`。
- 用户只是想在当前 Codex worktree 中开发。用会自动隔离的 `pnpm dev`，不要另起 `/tmp/octopus-worktree-preview`。
- 改动需要打包 Desktop 验证；遵循 repo docs 的 Desktop validation workflow。
- 用户要 production-like `pnpm prod` 行为，而不是 dev preview。

## 默认工作流

### 1. 检查当前 worktree

从 repo root 开始并记录当前分支：

```bash
git status --short --branch
git branch --show-current
```

不要切分支、reset 文件或停止无关 runtime。实现工作后的 dirty worktree 很正常。

### 2. 选择隔离运行时设置

preview 有意是临时的，并可能使用与同一 worktree 的 canonical `pnpm dev` 不同的 instance。用户比较数据时要说明。

优先使用分支派生 instance id、非默认 app port 和 `/tmp` 下隔离的 `OCTOPUS_HOME`：

```text
OCTOPUS_INSTANCE_ID=<branch-slug>
PORT=<free-port>
OCTOPUS_HOME=/tmp/octopus-worktree-preview/<branch-slug>/home
```

只有用户明确要默认 dev runtime 且端口空闲时才用 `3100`。否则从 `3310` 附近选择空闲端口。

如果用户要与普通 Codex worktree 开发 surface 相同的数据和 instance，默认不要用该 launcher。启动或检查 `pnpm dev`，并验证 `/api/health` 的 instance id。

如果 embedded PostgreSQL 可用，使用空闲 `OCTOPUS_EMBEDDED_POSTGRES_PORT`。如果本地环境中 embedded PostgreSQL 失败，使用该 preview 专用 external database，不要复用其他 Octopus instance 数据库。

### 3. 优先使用内置 launcher

从 repo root：

```bash
bash .agents/skills/maintainer/octopus-worktree-preview-maintainer/scripts/start_current_branch_preview.sh
```

launcher 会：

- 从当前分支派生 instance id
- 找空闲 app 和 embedded PostgreSQL 端口
- 以 Vite dev middleware 启动 `@octopus/server`
- 可用时使用 `tmux`，macOS 下再用 `launchctl`
- 等待 `/api/health`
- 打印 URL、日志和停止命令

有用选项：

```bash
bash .agents/skills/maintainer/octopus-worktree-preview-maintainer/scripts/start_current_branch_preview.sh --replace
bash .agents/skills/maintainer/octopus-worktree-preview-maintainer/scripts/start_current_branch_preview.sh --port 3312
bash .agents/skills/maintainer/octopus-worktree-preview-maintainer/scripts/start_current_branch_preview.sh --database-url postgres://user:pass@127.0.0.1:5432/dbname
bash .agents/skills/maintainer/octopus-worktree-preview-maintainer/scripts/start_current_branch_preview.sh --stop
```

`--replace` 仅用于同一分支派生 preview session。不要 kill 属于其他 Octopus worktree 的端口或进程组。

### 4. 务实处理启动失败

readiness 失败时，先检查托管日志：

```bash
tmux capture-pane -pt octopus-preview-<instance-id> -S -180
tail -180 /tmp/octopus-worktree-preview/<instance-id>/*.log
```

修复明显本地环境问题，如端口占用或依赖缺失。如果 embedded PostgreSQL 失败，创建或使用隔离 external database 并用 `--database-url` 重跑；不要把 preview 指向用户主 dev 数据，除非用户明确要求。

### 5. 验证就绪

交接前检查：

```bash
curl -fsS http://127.0.0.1:<port>/api/health
```

响应中的 `instanceId` 应匹配 preview instance id。不匹配说明 URL 可能属于另一个 runtime。

可见 UI 工作也应在可行时打开浏览器。如果浏览器自动化不可用或卡住，明确说明，但仍提供 health-checked URL。

### 6. 交接 preview

保持简短具体：

```text
当前分支已经跑起来了：
http://127.0.0.1:<port>

实例：<instance-id>
日志：<tmux attach or log path>
停止：<stop command>
Health check passed.
```

如果因为 `3100` 被占用而使用非默认端口，要说明。如果数据库是隔离或临时的，也要说明，避免用户误解数据。

## 清理请求

清理时，只停止当前分支的托管 preview：

```bash
bash .agents/skills/maintainer/octopus-worktree-preview-maintainer/scripts/start_current_branch_preview.sh --stop
```

之后验证 preview 端口已释放。除非用户明确要求，不要删除 worktree、数据库或停止其他 Octopus session。

## 判断规则

- 隔离比保留默认端口更重要。
- 不要把该技能当作 Codex worktree 隔离的修复方案；那属于默认 `pnpm dev` 环境解析。
- 当 preview 使用临时 `/tmp` instance，且不同于同一 checkout 的普通 `pnpm dev` instance 时，要明确说明。
- health-checked URL 是最低交接标准；日志和停止命令让它可用。
- 绝不要因为无关 Octopus session 占用 `3100` 就停止它。
- 用户需要 turn 结束后还能使用 preview 时，不要留下前台命令；用 `tmux` 或用户级托管进程。
- 如果任务从 preview 转为修启动 bug，要说明并保持源码改动范围。
