---
name: stop-octopus-dev-maintainer
description: >
  安全停止或清理 Octopus 本地 `pnpm dev` 进程。仅当用户当前任务明确是停止、重启、kill 或清理 repo-local 开发运行时，例如“把 pnpm dev 停了”“重启 dev”“清掉 dev 残留”“把本地开发环境关掉”时使用。如果该技能与生产数据、数据库、组织、Desktop 打包等无关任务一起出现，只把它当作可选 preflight：只有用户明确要求停止 dev 时才运行一次脚本，然后继续真实任务。优先使用该技能而不是临时 `pkill pnpm`，确保只处理 Octopus repo dev 进程。
---

# Stop Octopus Dev Maintainer

保持 Octopus 本地 dev 运行时维护紧凑且安全。

通常任务很简单：

- 识别当前 Octopus dev runtime 进程
- 优雅停止它们
- 确认实际是否有进程在运行

不要把它扩大成全机器的通用进程清理。

## 快速适用性检查

在做任何进程或端口调查前，先分类用户当前任务：

- 当任务是 repo-local 开发运行时，例如停止或重启 `pnpm dev`，使用完整工作流。
- 如果任务主要是生产/本地生产数据、打包 Desktop、组织、数据库清理、备份、迁移或 API 维护，本技能不是主流程。不要因为存在其他 Octopus 进程就花时间检查宽泛进程列表。
- 如果用户明确把该技能作为非 dev 任务的安全 preflight，只运行一次内置脚本，报告是否发现 `pnpm dev` runtime，然后继续。

打包 Desktop、`pnpm prod`、`pnpm octopus run` 和 `/Applications/Octopus.app` 拥有的 embedded Postgres 不在范围内。除非用户明确要求停止 production/local-prod runtime，否则让它们继续运行。

## 范围

该技能只针对当前 Octopus checkout。

设计目标是 repo root 开发流程：

```bash
pnpm dev
```

该流程启动 `scripts/dev-shell.mjs`，再管理本地 dev runner 和 desktop shell。

## 默认工作流

### 1. 优先使用内置脚本

从 repo root 执行：

```bash
bash .agents/skills/maintainer/stop-octopus-dev-maintainer/scripts/stop_octopus_dev.sh
```

只预览：

```bash
bash .agents/skills/maintainer/stop-octopus-dev-maintainer/scripts/stop_octopus_dev.sh --dry-run
```

如果脚本输出 `No matching Octopus dev processes found.`，除非用户任务是诊断为什么 dev 还在运行，否则停止本技能流程。不要仅因为有其他 Octopus 进程就继续做宽泛的 `ps`、`lsof` 或 app 进程搜索。

### 2. 脚本应该处理什么

脚本只允许停止 repo-local Octopus dev 进程，例如：

- 根 `pnpm dev` / `scripts/dev-shell.mjs` 进程
- `scripts/dev-runner.mjs`
- 本 repo 的 desktop dev Electron 进程
- 属于同一运行时的 repo-local Octopus dev helper 进程

不得 kill 其他 repo 的无关 `pnpm`、`node`、`vite` 或 Electron 工作。不得停止打包 Desktop 或本地 production runtime。

### 3. 验证

停止进程后，用聚焦检查验证：

```bash
ps -Ao pid=,command= | rg 'scripts/dev-shell\.mjs|scripts/dev-runner\.mjs|electron/cli\.js dist/main\.js'
lsof -nP -iTCP:3100 -sTCP:LISTEN
```

用验证结果明确区分：

- 本来就没有运行
- Octopus dev 运行过并已停止
- 部分目标进程在优雅关闭后仍存活

脚本停止了东西或报告 survivors 后，运行这些验证。简单“没运行”结果下，脚本输出通常足够，除非用户要求更深诊断。

## 升级规则

- 优先用 `SIGTERM` 优雅关闭。
- 如果内置脚本报告 survivors，先展示确切 survivors，再使用 hard kill。
- 只有用户明确要硬停止，或优雅关闭已失败且用户仍想全部停掉时，才用 `--force`。
- 绝不要用 `pkill pnpm`、`killall node` 或类似宽泛命令。

## 重启请求

如果用户要求重启 dev：

1. 用内置脚本停止当前 Octopus dev runtime
2. 验证旧 runtime 已消失
3. 启动用户要求的 dev 命令
4. 报告新进程状态

不要假设“重启”意味着 kill 所有本地开发进程。

## 报告格式

简短回复：

- 是否发现正在运行的 Octopus dev runtime
- 停止了哪些进程组
- 是否有东西在优雅关闭后仍存活

示例：

```text
已停止当前 Octopus `pnpm dev` 运行时。
关闭了 `scripts/dev-shell.mjs` 和其子进程，`3100` 端口当前没有监听。
```
