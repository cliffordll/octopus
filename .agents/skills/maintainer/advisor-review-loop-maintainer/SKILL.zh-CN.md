---
name: advisor-review-loop-maintainer
description: >
  为 Octopus 开发工作运行决策级 advisor-to-reviewer loop。当用户要求把 Build Advisor 与 Agent Work Reviewer Maintainer 结合起来，想要第一性原理的场景和需求分析加独立 reviewer loop 或 acceptance gate，要求两个 reviewer agents，说“迭代两轮”“没有通过 review 返工”“从场景和需求出发”“corner cases”，或需要 proposal、skill、workflow、UI、architecture、release review 或 agent outcome 在最终交接前通过独立 review 时使用。没有 reviewer agents、重复 review 轮次或验收门要求的第一性原理建议，优先用普通 build-advisor。
---

# Advisor Review Loop Maintainer

该技能串联两个 Octopus maintainer 实践：

- `build-advisor`：把模糊不满或高风险请求转为有依据的场景分析、需求地图、选项和推荐计划。
- `agent-work-reviewer-maintainer`：独立判断结果是否以足够行为、证据和验证解决了正确产品问题。

当工作不应该在单次 author pass 后就被接受时使用。本技能的目标是创建可 review 的 proposal 或实现，让它经受独立压力，修订后只在剩余风险明确时交接。

## 何时使用

用于用户要求以下任一 Octopus 开发任务：

- Build Advisor 后接 reviewer agents
- 第一性原理产品、场景或需求分析，并且必须通过独立 reviewers、重复 review 轮次或显式 acceptance gate
- 实现或交接前的深度 corner-case 覆盖
- 最终回答前两轮 review iteration
- “不通过就继续返工”
- 对 plan、skill、workflow、feature、UI、architecture、release verification 或完成的 agent task 做 review，且正确性依赖产品判断和验收门

不要用于窄 bug fix、简单命令、普通代码 review、直接 release 执行，或已有正确专门技能可以直接执行的泛第一性原理顾问任务。

如果用户为窄截图 UI 修复明确点名本技能，但没有要求 reviewer agents、重复轮次、“不通过就返工”或验收门，走轻量 route：

1. 做短 advisor check，确认 UI 问题和非目标。
2. 把实现交给 `octopus-ui-polish-maintainer` 纪律。
3. 报告这是轻量 advisor route，不是完整 reviewer loop。

除非用户明确要求，不要对小颜色、间距、label、icon、badge、menu position 或冗余 wrapper 修复花完整双 reviewer loop。

## 输入

开始前解析：

- Target artifact：proposal、plan doc、skill、code diff、PR、commit、release、UI state、transcript 或 workflow。
- Requested mode：proposal-only、implementation、review-only 或 proposal-then-implementation。
- Evidence source：repo files、docs、screenshots、logs、traces、commits、branches、PRs、eval outputs 或用户 artifact。
- Review bar：结果被接受前必须满足什么。

用户明确时推断合理默认并继续。只有 target artifact 或 requested mode 无法安全判断时才问。

严格尊重 `review-only`。review-only 模式下，只产出 advisor frame、review findings、verdicts 和最小 changes needed；不要编辑文件、重写 artifact 或继续实现，除非用户看完 findings 后明确要求返工。

当 `turn_aborted`、`/goal` 或长实现 checkpoint 后恢复时，继续前重建当前状态：

- 检查 branch 和 dirty state
- 识别 partial commits、merge/conflict state 和正在运行的 verification
- 重述剩余任务和缺失 proof

不要因为下一条用户消息说继续，就假设上一 turn 干净完成。

## 默认工作流

### 1. 构建证据包

收集能支持真实判断的最小证据：

- repo instructions 和相关 docs
- 当前 branch、dirty state、commits、PRs 或目标文件
- existing plans、specs、screenshots、traces 或 eval results
- 依赖的两个 source skills：
  `.agents/skills/build-advisor/SKILL.md`
  `.agents/skills/maintainer/agent-work-reviewer-maintainer/SKILL.md`

Octopus 产品或 workflow 工作中，按需阅读 `doc/GOAL.md`、`doc/PRODUCT.md`、`doc/SPEC-implementation.md`，涉及 UI 时读 `doc/DESIGN.md`。

保持聚焦，不要为显得忙而扫描整个 repo。

### 2. 运行 advisor pass

在起草或接受目标前遵循 `build-advisor`：

- 重述用户真正想完成什么
- 诊断问题主层级
- 映射 actors、lifecycle states、intents 和 failure modes
- 把场景压缩成 requirement classes
- 识别 non-goals 和 boundaries
- 覆盖会改变设计的 corner cases
- 定义具体 evaluation rubric
- 比较现实选项
- 把推荐选项展开成可决策 artifact

不要声称字面“100% certainty”。说明 coverage boundary：考虑了哪些场景、证据支持什么、哪些新证据会改变结论。

### 3. 生成两个独立 reviewer

当 subagents 可用且用户要求 reviewer agents 时，在同一 turn spawn 两个 reviewers，让它们独立评估。记录 review execution mode 为 `spawned reviewers`。

Reviewer A 负责场景和需求正确性：

```text
Use .agents/skills/maintainer/agent-work-reviewer-maintainer/SKILL.md.

Review this artifact from first principles as the scenario and demand reviewer.
Focus on actors, user jobs, lifecycle states, requirement classes, non-goals,
corner cases, and whether the proposed solution solves the right product
problem. Give accept / conditional accept / reject, blocking gaps, and the
smallest changes needed to pass.
```

Reviewer B 负责交付和可信正确性：

```text
Use .agents/skills/maintainer/agent-work-reviewer-maintainer/SKILL.md.

Review this artifact as the implementation, workflow, and validation reviewer.
Focus on object model, scope discipline, org scoping, contracts, validation,
tests, UI evidence when relevant, rollback/recovery, and handoff quality. Give
accept / conditional accept / reject, blocking gaps, and the smallest changes
needed to pass.
```

两个 prompt 包含相同 evidence packet、target artifact、user request 和 evaluation rubric。告诉 reviewers 它们不是 implementers；只判断和指出 gaps。

如果 subagents 不可用，自己串行执行两个 review。记录 mode 为 `serial two-role fallback`，不要声称 spawn 了两个 agents，并承认独立性信心较低。保持角色分离，避免 author pass 自评。

### 4. 合并 findings 为返工清单

两个 review 返回后：

- 把 verdict 标准化为 `accept`、`conditional accept`、`reject` 或 `needs more evidence`
- 分离 blocking gaps 和 non-blocking suggestions
- 识别 reviewer 分歧，并根据哪个 requirement 拥有 tie 做决定
- 只为提升正确性或证据的 gaps 修订 artifact
- 不要过拟合某个 reviewer 措辞；需要时提炼为更通用 skill、workflow 或产品规则

`review-only` 模式下，在这里停下，输出 merged findings 和 smallest rework list。除非用户明确切换到 rework，否则不要修订 artifact 或跑下一轮。

任一 reviewer reject 或指出 blocking gap 时，不要最终交接。先返工。

### 5. 运行第二轮 review

高风险任务、skill creation、workflow changes 或用户要求两轮时，第一轮修订后运行第二轮。

第二轮 prompt 包含：

- revised artifact
- round-one findings
- 简短 changelog：改了什么
- 明确要求判断 blockers 是否真的解决

如果第二轮仍 reject 或有 unresolved blocker，继续 targeted rework 并重复 review loop，直到：

- 两个 reviewers accept 或 conditional accept 且无 blocking gaps
- 剩余 gap 需要用户判断或外部证据
- 继续迭代不再产生实质改进

### 6. 最终交接

最终答案紧凑但必须包含：

- final artifact path 或 summary
- review execution mode：spawned reviewers 或 serial two-role fallback
- advisor coverage boundary：考虑的 scenarios、requirements、non-goals 和 key corner cases
- reviewer 轮次摘要和 verdicts
- 轮次间改了什么
- 已验证内容和未验证内容
- 剩余风险或仍需人类判断的决策

如果代码、文档或 skills 改变，遵循 repo validation、commit、push 规则。排除无关 dirty worktree。skill changes 至少验证 JSON eval files，并报告是否运行 eval harness 或 benchmark viewer；未运行要说明原因。

## Review Acceptance Bar

以下任一为真时，结果不可接受：

- artifact 从实现形态出发，而不是 user job 和 scenario pressure
- requirement classes 不能回溯到 scenarios 或 failure modes
- reviewer prompts 缺 evidence packet，导致浅 opinion review
- reviewers 被要求 rubber-stamp，而不是必要时 reject
- 第二轮没有明确验证第一轮 blockers 已修复
- 用户可见 workflow 改动缺少 repo 要求的 E2E 或 rendered evidence
- final handoff 不披露使用 spawned subagents 还是 serial fallback
- handoff 隐藏 skipped checks 或把未验证行为当已证明

## 常见 corner cases

- Reviewer 分歧：优先绑定具体 user scenario、repo invariant 或 validation gap 的 finding。若都合理，保持为 human decision。
- Missing evidence：verdict 改为 `needs more evidence`，尽量先收集缺失 artifact。
- 用户只要 proposal：停在 proposal artifact 并 review，不经确认不要实现。
- 用户只要 review：停在 verdicts 和 smallest changes needed，不返工。
- 用户要 implementation：repo 规则要求时才写计划，advisor pass 后实现，再 review 实际 diff 和 validation evidence。
- 窄 UI fix 点名本技能：走轻量 route，再按 `octopus-ui-polish-maintainer` 做实现、视觉 proof、测试、commit 和 handoff。
- Skill creation：在正确 global 或 project-local 位置创建 skill，有用时添加现实 eval prompts，review trigger description、workflow、references 和 evalability。
- Visible UI：声称 loop 通过前要有 screenshot 或 browser evidence。
- Release/Desktop：验证 live release surfaces 或 packaged behavior；local build 成功不够。

## 输出模板

```markdown
结论：...

产物：
- ...

Advisor 覆盖：
- 场景/角色：...
- 需求类：...
- 非目标：...
- 关键 corner cases：...

Review 轮次：
- Round 1: Reviewer A ..., Reviewer B ...
- Round 2: Reviewer A ..., Reviewer B ...
- Execution mode: spawned reviewers / serial two-role fallback

返工摘要：
- ...

验证：
- Passed: ...
- Not run / not proven: ...

剩余风险：
- ...
```

工作小时可以更短，但不要省略失败检查或 unresolved blockers。
