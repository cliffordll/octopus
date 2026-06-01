---
name: release-maintainer
description: >
  维护并执行 Octopus 在 npm、GitHub Releases 和 Desktop portable assets 上的发布。当用户询问发版、release、发布到 npm、canary/stable promotion、GitHub Release assets、Desktop distribution、`npx @octopus/cli@latest start`、`npx @octopus/cli start`、npm `latest` dist-tags 异常、完整 Desktop install smoke tests、GitHub Release API/rate-limit failures、version bumps、rollback、首次 package bootstrap、npm token fallback publishing 或 release workflow failures 时使用。在 Octopus 仓库中，无论是规划还是实际发布操作都优先使用本技能，即使用户只问“现在要做什么”或“帮我发版”。
---

# Release Maintainer

帮助用户发布 Octopus，并不丢失任何 release surface。

Octopus release model 有多个移动部分：npm packages、git tags、GitHub Releases、Desktop portable assets、release notes 和 smoke tests。你的任务是把当前 repo 和 remote state 转成具体 release plan，然后只执行用户授权的步骤。

当用户授权实际 release 工作时，使用本地和远程工具，而不是只停在指导。优先用 `git`、`gh`、`npm` 和 repository scripts 发现状态。只在 secret 或不能安全推断的决策上询问用户。

## 第一原则

- npm 发布 CLI 和 public runtime/workspace packages。
- Desktop binaries 是 GitHub Release assets，不是 npm packages。
- Canary git tags 保持 `canary/` namespace，例如 `canary/v0.1.0-canary.2`；但 GitHub Release 展示标题应是 clean version，如 `v0.1.0-canary.2`。
- public npm scope 是 `@octopus`。除非 repo 明确重新引入旧 scope，否则旧示例视为 stale。
- stable 用户入口是 `npx @octopus/cli@latest start`。裸 `npx @octopus/cli start` 解析 npm `latest` dist-tag。
- persistent CLI 存在后，`octopus <command>` 和 `npx @octopus/cli@latest <command>` 在解析到同一 CLI version 时是同一 CLI surface。`npx` 是首次运行或显式 dist-tag 形式。
- Canaries 从 `main` 自动发布，使用 npm dist-tag `canary`。
- Canary git tags 使用 `canary/vX.Y.Z-canary.N`。对应 GitHub Release display title 应为 clean `vX.Y.Z-canary.N`，并标记 prerelease。
- GitHub Actions `GITHUB_TOKEN` 推送的 tag 不会自动触发另一个 workflow。如果 canary npm publish 创建 tag，`release.yml` 必须显式 dispatch `desktop-release.yml`，或 maintainer 手动执行。
- Stables 从明确选择的 source ref 手动 promotion，使用 npm dist-tag `latest`。
- Stable tags 指向原始 source commit，不指向生成的 release commit。
- stable release 中，`main` 只是 selector，直到解析为不可变 commit SHA 或 stable tag。dry-run、publish、Desktop recovery 和 verification 都必须使用同一 locked ref。除非用户明确要求 retarget，不要追逐更新的 `main` commits 或 canaries。
- stable release 未完成，直到 verification、npm、GitHub Release、Desktop assets 和 public notes/announcement 都处理完。
- pre-stable public canaries 在没有 stable npm version 且用户明确要 `npx @octopus/cli@latest start` 或裸 `npx @octopus/cli start` 立即可用时，可临时作为默认 `latest` install path。必须说明这是 alpha/bootstrap exception，不是正常 canary policy。
- bootstrap exception 下，只有匹配 Desktop GitHub Release 具备所有 portable assets 和 `SHASUMS256.txt` 后，npm `latest` 才能移到 canary。否则 public CLI 可能指向无法安装的 Desktop release。
- `--dry-run` smoke 只证明 version 和 asset selection，不证明 download、checksum、extraction、symlink preservation、quarantine cleanup 或 app launchability。不要声称 public Desktop install path 已修复，除非非 dry-run 隔离 `npx ... start --no-open` 在可用平台成功，或明确说明无法测试的平台。
- GitHub REST `403` release lookup 可能是 anonymous API rate limit，不是 release 缺失。声明缺失前用 authenticated `gh release view` 和 direct asset URL 检查。
- 本地 npm auth 不保证存在。如果 `npm whoami` 失败且必须移动 dist-tag，使用 repo `npm-dist-tag.yml` workflow，不要假装本地 shell 能 publish 或修复 npm state。
- 不应触发另一个 canary 的 release-maintenance commits 必须包含 `[skip release]`，并验证 `release.yml` 确实 skip。
- 如果普通 `main` push 已在运行，同时你做 release-maintenance changes，要 watch 它完成。它可能发布下一个 canary，该 canary 仍需要 npm、tag、Desktop 和 Release-title verification。任何 emergency dist-tag repair 后，要等 in-progress `release.yml` 完成后重新检查 `latest`，或明确报告 overwrite risk。
- 一旦 stable source ref locked，之后无关 `main` pushes 不是 retarget stable 的理由。只跟踪 overwrite 或 verification risk。首个 stable 存在后，普通 canary promotion 不应移动 npm `latest`；验证该 invariant，而不是无限等待无关 canary smoke。

## 必需上下文

按请求只读取必要上下文：

- `doc/RELEASING.md`：主 maintainer runbook。
- `doc/PUBLISHING.md`：npm/package internals。
- `doc/RELEASE-AUTOMATION-SETUP.md`：一次性 GitHub/npm setup。
- `.github/workflows/release.yml`：诊断 canary/stable workflow。
- `.github/workflows/desktop-release.yml`：诊断 Desktop artifacts。
- `.github/workflows/npm-dist-tag.yml`：通过 GitHub Actions 修复 `latest` 或 `canary` dist-tags。
- `scripts/release.sh`、`scripts/release-package-map.mjs`、`scripts/create-github-release.sh`、`scripts/promote-npm-dist-tag.mjs`、`scripts/wait-for-desktop-release-assets.mjs`、`scripts/rollback-latest.sh`：需要 exact command behavior 时读取。

任何可能变化的信息都要 live check，例如 npm package versions、GitHub Actions status、tags 和 Release assets。不要靠记忆。

如果 docs 与 live workflow 不一致，先检查 workflow 和 scripts，再行动，并报告 mismatch。active release 期间 workflow 是 executable truth；policy 变化后再更新 docs。

## 快速状态检查

给 release 指令前，本地工具可用时收集：

```bash
git status --short --branch
git log --oneline --decorate --graph -8
git tag --list 'v*' --sort=-version:refname | head -10
node scripts/release-package-map.mjs list
./scripts/release.sh stable --print-version
```

依赖 remote truth 时还检查：

```bash
gh workflow list
gh run list --workflow release.yml --limit 10
gh run list --workflow desktop-release.yml --limit 10
gh run list --workflow npm-dist-tag.yml --limit 5
gh release list --repo octopus/octopus --limit 20
npm view @octopus/cli dist-tags --json
npm view @octopus/cli versions --json
```

worktree 有无关 dirty files 时，明确说明会忽略它们，只触碰 release 所需文件。

从 dirty local repo 实际发布时，优先 clean temporary clone 或 worktree，保持用户主 workspace 不动：

```bash
tmp="$(mktemp -d /tmp/octopus-release-XXXXXX)"
git clone <repo-url> "$tmp"
cd "$tmp"
git switch main
git pull --ff-only
```

只有用户明确要求切换或同步主 checkout 时，才 stash/restore 用户主 checkout 文件。绝不丢弃无关用户改动。

## 决策流

### One-Time Setup

首次准备 release automation 时使用。

1. 确认 `.github/workflows/release.yml`、`.github/workflows/desktop-release.yml` 和 `.github/CODEOWNERS` 已合并到 `main`。
2. 确认所有 public packages 已存在：
   `node scripts/release-package-map.mjs list`。
3. packages 已存在时，为每个 package 配置 npm trusted publishing：owner `Undertone0809`、repository `octopus`、workflow filename `release.yml`。npm 只要 workflow filename，不要 `.github/workflows/` 路径。
4. packages 不存在时，说明需要 bootstrap publish，之后才能把 trusted publishing 绑定到 package names。
5. 配置 GitHub environments：
   - `npm-canary`：无 reviewer，selected branch `main`
   - `npm-stable`：maintainer approval，selected branch `main`
6. trusted publishing 未就绪时，给两个 release environments 临时加 `NPM_TOKEN` secret，使用有 `@octopus` publish 权限的 npm automation token。
7. trusted publishing 验证后，把长期 `NPM_TOKEN` 从 steady-state workflow 中移除。

### First-Time npm Bootstrap

packages 尚不存在、trusted publishing 无法绑定，或用户明确提供一次性 npm token 时使用。

1. 确认 package names：

```bash
node scripts/release-package-map.mjs list
```

2. publish 前检查每个 package npm state。首次 release 缺失是预期；某 package/version 已存在则该 package/version 必须停止。
3. 使用 token 时，只写入 temporary npmrc 或 environment-scoped npm config。不要 echo、commit、写入 shell history 或遗留。发布后删除 temp npmrc，并提醒用户 revoke/rotate 聊天里粘贴的 token。
4. 按 release-package-map 顺序发布所有 public packages，使用选定 version 和 dist-tag。npm 已接受的 package/version 不要重试；继续验证和修复 tags/releases。
5. pre-stable public canary 且没有 stable npm version，并且用户要 `latest` 立即可用时，把所有 public packages 的 `canary` 和 `latest` 都移到同一 canary version。首个 stable 后，普通 canaries 只移动 `canary`。
6. 立即用脚本验证整个 package set 的 dist-tags，而不只看 `@octopus/cli`。

### Canary Release

Canary 通常自动发布。

1. 确认 change 已 merge 到 `main`。
2. 观察 `Release` workflow canary job。如果 triggering commit 是带 `[skip release]` 的 release-maintenance commit，先验证 run 被 skip。pre-stable public canary 只有在 dispatch Desktop release、验证 Desktop assets 后再 promotion npm `latest`，才算完成。
3. 确认每个 public package 的 npm `canary` 指向新 prerelease，而不只是 `@octopus/cli`。
4. 确认 canary tag、GitHub Release title、prerelease 标记、Desktop release assets 和 `SHASUMS256.txt`。
5. 必要时运行 public install smoke；不要把 dry-run 当完整安装证明。

### Stable Release

Stable 是手动 promotion。

1. 与用户确认 source ref，并锁定为不可变 commit SHA 或 stable tag。
2. 使用同一 locked ref 做 dry-run、publish、Desktop recovery 和 verification。
3. 检查 worktree clean 或使用 clean temporary clone。
4. 运行 release script，按 repo runbook 执行 stable publish。
5. 验证所有 public packages 的 `latest` 指向 stable version。
6. 验证 GitHub Release、Desktop assets、checksums 和 release notes。
7. 在可用平台做非 dry-run `npx @octopus/cli@latest start --no-open` smoke，或明确说明未覆盖平台。
8. 处理 public notes/announcement。

### Dist-tag Repair

当 npm `latest` 或 `canary` 错误时：

- 先确定 expected version 和 package set。
- 本地 npm auth 可用时可使用脚本；`npm whoami` 失败时走 `.github/workflows/npm-dist-tag.yml`。
- repair 后验证所有 packages，而不是单包。
- 如果 release workflow 仍在运行，结束后再次检查，或报告 overwrite risk。

### Rollback

rollback 前先判断 rollback 对象：

- npm dist-tag rollback
- GitHub Release asset/title repair
- Desktop asset recovery
- source commit revert
- docs/notes correction

不要把 rollback 扩大成未授权破坏性操作。每一步都要验证 public surface。

## 验证原则

Release 验证必须覆盖：

- git tag 和 source ref
- npm versions 和 dist-tags across all public packages
- GitHub Release 存在、title/prerelease 状态正确
- Desktop portable assets 和 `SHASUMS256.txt`
- public install path：`npx @octopus/cli@latest start`
- release notes 或 announcement 状态
- workflow runs 状态和失败原因

把 skipped、timed out、rate-limited、platform-unavailable 与 passed 分开报告。

## 安全规则

- 不要未经用户授权 publish、retag、move dist-tag、delete release、rollback 或 force push。
- 不要在 dirty user checkout 中做会污染用户工作的 release 操作；优先临时 clone/worktree。
- 不要泄露 npm token。临时 token 用完删除并提醒轮换。
- 不要只用 anonymous GitHub REST 判断 release 不存在；先用 authenticated `gh`。
- 不要把 canary policy 和 bootstrap exception 混淆。
- 不要追逐移动的 `main`，stable source ref 一旦 locked 就保持一致。

## 输出格式

规划或状态检查时：

```markdown
Release state:
- Source ref:
- Current npm tags:
- Latest workflows:
- GitHub Releases:
- Desktop assets:

Recommended next step:
- ...

Needs user decision:
- ...
```

实际执行后：

```markdown
完成：
- ...

验证：
- Passed: ...
- Not run / not proven: ...

Public surfaces:
- npm:
- GitHub Release:
- Desktop:
- npx install:

剩余风险：
- ...
```

如果无法继续，明确 blocker 是权限、token、workflow failure、rate limit、platform 缺失还是用户决策。
