---
name: pr-local-preview-maintainer
description: >
  把 GitHub pull request checkout 到本地 worktree，安全启动、验证本地 preview，并交给用户 URL。每当用户要求本地运行、预览、review 或验证 PR，包括 `gh pr checkout <number>`、“把这个 PR 跑起来”“本地 worktree 看一下效果”“让我 review 一下”“启动 PR 预览”时使用。如果 PR 影响可见 UI，用本技能在交接前截图，让用户检查实际发布结果，而不只是 URL。
---

# PR Local Preview Maintainer

在一次性本地 worktree 中运行 PR，并给用户稳定 preview 链接。目标是让用户 review PR，同时保护当前工作树，并让 UI 改动可见。

## 默认工作流

### 1. 保护当前 workspace

先检查仓库状态：

```bash
git status --short --branch
gh pr view <number> --json number,title,state,headRefName,headRepositoryOwner,url,isCrossRepository
```

如果当前 worktree 有本地改动，不要在这里运行 `gh pr checkout`。创建或复用 sibling worktree，避免覆盖无关工作，也方便之后删除 PR preview。

使用可预测路径：

```text
<repo-parent>/<repo-name>-pr-<number>
```

本仓库 PR 8 应为：

```text
/Users/zeeland/projects/octopus-pr-8
```

如果目录已存在，复用前检查：

```bash
git -C <worktree-path> status --short --branch
git -C <worktree-path> branch --show-current
```

如果 dirty，只在 dirty 改动与用户目标冲突时询问。否则选择带后缀路径，如 `<repo-name>-pr-<number>-preview`。

### 2. 在 worktree 中 checkout PR

从 remote base 创建 worktree，再在其中 checkout PR 分支：

```bash
git worktree add --detach <worktree-path> origin/main
gh pr checkout <number> --branch zeelandc/pr-<number>
```

如果 base 不是 `main`，使用 PR 实际 base ref。本地分支名优先体现 preview 目的，并遵循仓库分支前缀约定。

checkout 后验证：

```bash
git status --short --branch
```

### 3. 仅在需要时安装依赖

检查依赖是否存在：

```bash
test -d node_modules && echo node_modules-present || echo node_modules-missing
```

缺失时在 worktree 中安装：

```bash
pnpm install
```

只有 install warning 影响 preview 时才报告。常规 peer 或 bin link warning 可以简要提及。

### 4. 选择隔离运行时设置

启动前检查端口和现有本地 runtime：

```bash
lsof -nP -iTCP:<candidate-port> -sTCP:LISTEN
```

Octopus 优先：

```bash
OCTOPUS_INSTANCE_ID=pr-<number>
PORT=<free-api-port>
OCTOPUS_EMBEDDED_POSTGRES_PORT=<free-pg-port>
```

只有 `3100` 空闲且用户明确要默认 instance 时才用它。如果已有 Octopus dev runtime，保持不动，使用独立端口和 instance ID。

示例：

```bash
env OCTOPUS_INSTANCE_ID=pr-8 PORT=3118 OCTOPUS_EMBEDDED_POSTGRES_PORT=54358 pnpm dev
```

### 5. 让 preview 在交接后继续运行

优先使用 `tmux`。它能让 preview 在 assistant turn 结束后继续存活，并让用户容易查看日志。

```bash
tmux new-session -d -s octopus-pr-<number> -c <worktree-path> \
  'env OCTOPUS_INSTANCE_ID=pr-<number> PORT=<port> OCTOPUS_EMBEDDED_POSTGRES_PORT=<pg-port> pnpm dev'
```

如果没有 `tmux`，使用其他托管后台进程，并把日志写到 `/tmp/<repo-name>-pr-<number>.log`。不要留下无法解释的 opaque 进程。

### 6. 等待就绪

轮询 health endpoint 或等价 readiness check：

```bash
curl -fsS http://127.0.0.1:<port>/api/health
```

如果 app 没有 health endpoint，使用第一个有意义 route 并检查成功响应。frontend-only app 则加载 dev server URL 并确认返回 HTML。

启动失败时，先检查 session 日志再返回：

```bash
tmux capture-pane -pt octopus-pr-<number> -S -160
```

本地环境问题如依赖缺失或端口冲突可以自行修复。不要编辑 PR 源码，除非用户要求修复。

### 7. 判断是否需要 UI 截图

满足任一条件时必须截图：

- PR 标题、文件或用户请求提到 UI、layout、page、component、CSS、design、screenshot、visual review、browser behavior 或 interaction
- 改动文件位于 `ui/`、`desktop/`、frontend route、component、stylesheet 或 public assets
- 用户说想“看”效果

本地浏览器检查可用时使用 Browser Use。preview 运行后捕获重要 screen 或 flow。临时截图放仓库外，例如：

```text
/tmp/octopus-pr-<number>-<view>.png
```

非 UI 后端/API PR 通常 health check 加任务相关 API smoke check 足够。用户仍要手动 review 时提供 URL。

### 8. 交接格式

最终回复保持简短具体：

```text
PR <number> is running in <worktree-path>.

Open: http://127.0.0.1:<port>
Logs: tmux attach -t octopus-pr-<number>
Stop: tmux kill-session -t octopus-pr-<number>

Health check passed: <brief status>
Screenshots: <paths or embedded images when UI changed>
```

如果截图是必需但无法捕获，说明确切原因和已运行验证。

## 清理请求

用户要求关闭、停止或清理 preview 时，只停止 PR preview session，并验证端口释放：

```bash
tmux kill-session -t octopus-pr-<number>
lsof -nP -iTCP:<port> -sTCP:LISTEN
```

除非用户明确要求，不要删除 worktree。若用户要求删除，先验证 worktree 没有未提交改动。

## 安全说明

- 绝不在用户主 worktree 使用破坏性 Git 命令来完成 PR checkout。
- 不要因为默认端口占用就停止无关 Octopus dev session；选择隔离端口。
- 用专用 `OCTOPUS_INSTANCE_ID` 隔离 PR preview 数据。
- 如果需要源码编辑，暂停并说明任务已从 preview PR 转为修复 PR。
