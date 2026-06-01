---
name: development-lifecycle-router-maintainer
description: >
  在完整生命周期中路由 Octopus 开发工作：intake、需求 framing、产品/advisor 分析、UI 设计、实现、测试、证据收集、review gates、返工、commit、push 和 handoff。当用户给出模糊或端到端开发请求，询问该用哪个 workflow/skill，想从任意生命周期阶段进入，想每阶段后有 reviewer subagents，或默认期望交接前 review 时使用。review gates 优先使用 spawned reviewers。用户明确要求 release、UI polish、run transcript debug、local preview、data diagnosis、PR preview 或 review-only task 时，优先直接使用更窄 maintainer skill。
---

# Development Lifecycle Router Maintainer

本技能是 Octopus 开发工作的路由层。它决定用户进入哪个阶段，选择正确下游技能或正常 coding workflow，定义阶段退出标准，并在需要时添加 review gates。默认情况下，每个被路由的开发阶段在 handoff 或进入下一个重要阶段前都应通过 review gate。

它应保持轻量。不要把 advisor、reviewer、UI、release、debug 或 preview 技能的完整逻辑复制进来。路由到那些技能并遵循它们的 contract。

## 何时使用

用于用户要求：

- 从需求到实现、测试、review、handoff 的端到端开发工作流
- 判断“哪个 skill/workflow 应该处理这个任务”
- 从 requirements、UI design、implementation、testing、CI、release、debug 或 review 任一阶段进入的生命周期路由
- stage-by-stage reviewer gates、reviewer subagents 或“每阶段后 review”
- 修复上一次 agent run 中弱路由、跳过 review、阶段错误或过早实现的问题
- 创建或改进可复用开发任务 workflow

不要替代明确匹配的窄技能。用户只要求 release、debug run、review Codex session、preview PR、seed mock data、polish screenshot 或 stop dev processes 时，直接用专门技能。

## 核心规则

先路由，再执行。

在编辑文件、运行长验证、spawn reviewers 或 commit 前，说明 lifecycle stage 和离开该阶段的 acceptance bar。路由失败通常表现为从用户抱怨直接跳实现，或没有真实 reviewer evidence 却声称 review 已发生。

默认 review。当前用户请求和运行策略允许 subagents 时，优先使用真实 spawned reviewers。subagents 不可用、未授权、用户明确要轻量单 agent pass，或任务是纯机械 no-code 操作时，使用 serial fallback。

## 阶段分类器

把 prompt 分类为一个主阶段：

- `intake`：用户意图、目标 artifact 和模式不清。
- `requirements`：用户要问题 framing、场景、验收标准或“你懂吗”。
- `advisor`：当前 build、UI、workflow、trace 或 proposal 感觉不对，需要第一性原理诊断。
- `ui_design`：用户要界面方向、wireframe、视觉层级或截图产品/设计判断。
- `implementation`：用户批准方向或直接要求修/建。
- `verification`：用户问 tests、CI、E2E、screenshot、Desktop smoke 或 release checks 是否证明工作。
- `review`：用户要求 review、PM 判断、第一性原理批判或 Codex/session/PR/commit verdict。
- `debug`：用户问 run、UI path、data path、CI job、Desktop app 或本地进程为什么失败。
- `release`：用户要求 canary/stable release、npm、Desktop assets、tags 或 GitHub Release state。
- `handoff`：工作已实现，需要 final summary、validation、commit、push、residual risk 或 PR。

多个阶段同时出现时，选择最早的 blocking stage。例如“fix this and review it”从 `implementation` 开始，然后必须过 `verification` 和 `review`。

## 路由矩阵

使用最小匹配 workflow：

- 模糊不满、弱结果、产品/设计批判不清：`build-advisor`
- 高风险 proposal 或 implementation，需要 reviewer rounds：`advisor-review-loop-maintainer`
- session、PR、commit、proposal、UI state、release 或 agent outcome 的 review-only：`agent-work-reviewer-maintainer`，本地 Codex session id 用 `codex-session-product-reviewer-maintainer`
- 截图驱动可见 UI polish 或小 UI interaction fix：`octopus-ui-polish-maintainer`
- Octopus surface 数据错误、缺失、陈旧或稀疏：`octopus-data-path-diagnostician-maintainer`
- Octopus agent run failure、transcript、logs、stdout/stderr 或 run id：`debug-run-transcript`
- release、canary/stable publish、npm dist-tag、Desktop release asset 或 release workflow failure：`release-maintainer`
- 本地分支 preview 供用户测试：`octopus-worktree-preview-maintainer`
- GitHub PR 本地 checkout/preview/review：`pr-local-preview-maintainer`
- mock/demo/seed data 或 landing screenshots：`mock-data-maintainer`，截图是 deliverable 时再用 `landing-proof-shots-maintainer`
- 停止、重启或清理 repo-local dev runtime：`stop-octopus-dev-maintainer`
- 新增或更新 skill artifact：结合 `skill-creator` 指导和本 router 的 lifecycle gates

路由明显时，不要因为 router active 就跑 advisor loop。简要说明 route 并执行专门 workflow。

## 默认工作流

### 1. 构建 routing packet

只收集选择 route 所需证据：

- 用户请求和本 thread 中的纠正
- 当前 `git status --short --branch`
- 命名文件、截图、session ids、run ids、PRs、commits 或 plans
- 基于 `AGENTS.md` 的相关 repo docs
- 在多个 skills 间选择时的相邻 skill contracts

忽略注入环境文本和宽泛 repo 扫描，除非影响 route。用户给 Codex session id 时，判断 workflow 前提取真实用户 prompts 和 agent actions。

### 2. 声明 route 和 stage exits

实现前说明：

- 当前 lifecycle stage
- 选择的 downstream skill 或 normal coding workflow
- 当前阶段 acceptance bar
- review gate plan，优先 `spawned reviewers`

保持简洁。小 bug 一句话足够。

### 3. 执行当前阶段

遵循下游 skill 或正常 repo workflow。每个阶段必须产生具体 artifact：

- requirements：scenario map、non-goals、acceptance criteria
- advisor：diagnosis、options、recommendation、decision boundary
- UI design：wireframe、screenshot criteria 或 approved direction
- implementation：scoped diff、tests、必要 docs/contract updates
- verification：passing checks、screenshots、logs 或 explicit blockers
- review：verdict、blocking gaps、smallest fixes、residual risk
- release：locked source ref、live publish/asset/dist-tag evidence
- handoff：files、validation、commit/push state、unverified items

当前阶段存在会改变 route 的 blocker 时，不要进入下一阶段。

### 4. 默认 review gates

凡是产出 artifact、decision、diff、validation bundle 或 handoff 的 routed stage，默认使用 review gate。窄 bug fix 也包括：先实现、收集验证证据，再 review 实际 diff 和 evidence。

提升 review 深度的情况：

- 用户明确要求 reviewer agents、两轮或“不通过不算完成”
- 工作会塑造未来 agent 行为的 workflow/skill/proposal
- 改动广、用户可见、release 相关、Desktop/package 相关或跨 contract
- 之前 run 因跳过 review 或阶段错误失败

跳过或延后 review gate 的情况：

- 用户明确说不要 review
- 当前任务是 review-only，review 本身就是 artifact
- 纯机械 no-code 操作，如 quick status check
- 当前阶段尚无 artifact；先创建 artifact，再 review

优先 spawned reviewers。当 subagents 可用且被当前用户请求和 active tool policy 授权时，在 stage artifact 存在后 spawn reviewers。记录 execution mode 为 `spawned reviewers`。

subagents 不可用或未授权时，运行有标签的 serial two-role fallback。记录 mode 为 `serial two-role fallback`，说明独立性较低，不暗示独立 review 已发生。

Reviewer A 负责 scenario correctness；Reviewer B 负责 delivery trust。若任一 reject 或指出 blocker，返工后再 handoff，或报告 blocker 需要用户判断。

### 5. 共享 worktree 中保持 git 安全

编辑前和 commit 前都检查 branch 和 dirty state。

- 只 stage 当前任务文件。
- 大 refactor 或 `/goal` runs 中，按可独立站住的阶段拆 commit：facade/boundary setup、internal extraction、consumer rewiring、compatibility fix、test hardening 或 docs update。
- 用户说“分批 commit”或“不要一个很大的 commit”时，先做 phase checklist，并在每阶段后保留可恢复 checkpoint。
- 不要因为一次长 run 中发现，就把无关 route、UI、runtime、migration 和 docs cleanup 放进同一个 commit。
- 除非 HEAD 确认是自己刚创建的 commit 且没有并行 commits，否则不要 amend。
- 共享 workspace 中优先普通 follow-up commit，而不是改历史。
- 分支落后、non-fast-forward 或包含用户未要求发布的无关 local commits 时，不要 push。
- push 被阻塞时，如 repo 规则要求 commit，仍做 scoped local commit，并解释分支状态。

### 6. 最终 handoff

最终输出包含：

- 采取的 route 和完成的 stages
- 使用或有意跳过的 downstream skills
- review execution mode（如有）
- 改动文件或 artifacts
- 通过和未运行的验证
- commit 和 push 状态
- 剩余 blockers 或 human decisions

## 验收标准

以下任一为真时，不要声称完成：

- 从未声明 route，却静默跳阶段
- 窄专门技能被 heavyweight advisor loop 替代
- 用户要求 reviewer gates，但没有真实 review artifact
- “review”只是作者自己重看 diff，没有 findings
- 用户可见 UI 缺少 required rendered 或 screenshot evidence
- feature/workflow 改动跳过 required E2E 且没有明确批准
- Desktop/release/package 工作缺少 repo 要求的 packaged 或 live checks
- git history 包含无关文件，或共享 worktree 中 unsafe amend
- final answer 隐藏 failed checks、skipped evidence 或 push blockers

## 常见路线

- 小 UI bug 且要求 review：`implementation -> verification -> review -> handoff`
- 小 UI bug 未明确要求 review：仍默认 `implementation -> verification -> review -> handoff`，但 review 轻量
- 只要 proposal：`requirements -> advisor -> review -> handoff`，不要实现
- Codex session audit：`review`，用 `codex-session-product-reviewer-maintainer`
- failed run 或 transcript problem：`debug -> review or implementation`
- release request：`release`，直接用 `release-maintainer`

## 输出模板

```markdown
Route: ...
Stage exits:
- ...

Used:
- ...

Review:
- Mode: spawned reviewers / serial two-role fallback / not required
- Verdict: ...

Validation:
- Passed: ...
- Not run / not proven: ...

Git:
- Commit: ...
- Push: ...

Residual risk:
- ...
```
