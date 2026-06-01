---
name: codex-session-product-reviewer-maintainer
description: >
  以专业产品经理和第一性原理 reviewer 的身份 review 本地 Codex session、task 或 commit。当用户提供 Codex session id，要求 review 另一个 agent 的任务，说“PM review”“professional product manager”“first principles”“第一性原理”“作为 reviewer”“review 一下 codex session”，或想判断已实现任务是否解决正确产品问题时使用。判断前先从本地 Codex logs 和 repo artifacts 提取证据。
---

# Codex Session Product Reviewer Maintainer

该技能从产品经理视角 review 已完成或进行中的 Codex task。它是 reviewer 工作流，不是实现工作流。

核心问题是：

> 这个 session 是否以正确范围、行为和验证解决了正确产品问题？

用它把“作为 PM review 这个 Codex session”之类模糊请求，转化为基于 session transcript、实际代码改动、测试、plan docs 和 repo 产品标准的产品 review。

## 使用场景

当用户要求：

- 以产品经理身份 review Codex session id、task、thread 或 run
- 评估另一个 agent 的实现是否产品正确
- 对已交付任务做第一性原理思考
- 判断 proposal 或 implementation 是否解决正确用户问题
- 输出 reviewer 风格 accept / conditional accept / reject
- 把模糊不满转为明确产品批判

常见触发：

- “review 一下 codex session id ...”
- “as a 专业的产品经理 review”
- “第一性原理思考一下”
- “作为 reviewer”
- “PM review this task”
- “这个 session 做得怎么样”
- “这个实现是不是产品上对”

## 不使用场景

不要用于：

- 用户主要想要 bug 和 line comments 的普通 code review
- 调试失败的 Octopus agent run transcript
- 从零创建新产品想法或 brainstorm
- 实现 review 中发现的修复，除非用户明确要求
- 只总结 session 而不判断
- 本地证据可用时只根据最终 assistant message 判断

用户要代码正确性 review 时，用 code-review workflow。用户问 Octopus agent run 为什么失败时，先用 run transcript debugging。

## 输入

必需：

- Codex session id、commit hash、PR、branch 或清楚标识的 task。

可选：

- review lens：PM、first principles、design、workflow、release 或 founder mode。
- 输出风格：short verdict、detailed memo 或 findings only。

## 证据收集

不要从观点开始。先构建证据包。

1. 定位 Codex session。
   - 搜索 `~/.codex/session_index.jsonl`、`~/.codex/sessions/**/*.jsonl` 和 `~/.codex/archived_sessions/*.jsonl`。
   - 确认 session title、timestamp、cwd、branch 和 final assistant message。
   - 找不到 session 时说明，并只 review 用户提供的 artifacts。

2. 提取真实用户请求和纠正。
   - 忽略注入的 `AGENTS.md`、environment context、skill bodies 和 system text。
   - 捕获每个有意义 user prompt，尤其是中途 scope change、产品约束或补充反馈。

3. 提取 agent 实际做了什么。
   - 总结 proposals、plans、implementation steps、changed files、commands、validation results、commits 和 pushes。
   - 提到 commit 或路径时，使用 `git show`、`git diff`、plan docs、tests 和相关 source files。
   - 区分 committed changes 和 unrelated dirty worktree。

4. 阅读相关产品上下文。
   - 产品行为或 UI 任务从 `doc/GOAL.md`、`doc/PRODUCT.md`、`doc/SPEC-implementation.md`、`doc/DESIGN.md` 开始。
   - 若存在 task plan doc，阅读它。
   - release、desktop、plugin、database 或 CLI 工作遵循相关 AGENTS.md doc route。

5. 检查验证证据。
   - 记录实际通过的 focused tests、full checks、E2E、builds、screenshots 或 browser checks。
   - “尝试但超时”是 unverified，不是 passed。
   - 可见 UI 改动要找非空和 edge-case 状态的真实视觉验证，而不只是 empty state。

## 第一性原理 review 框架

写 verdict 前使用：

1. User job
   - 该任务要解决哪个真实用户或 operator 问题？
   - 原始请求是否是更深 workflow 或信息架构问题的症状？

2. Object model
   - 产品对象是什么：view、navigation shortcut、workflow state、preference、project artifact、run、issue 或 setting？
   - 实现是否把它建模为正确对象？

3. Core loop impact
   - 改动是否帮助 Octopus 端到端完成真实 agent work？
   - 是否减少 operator 摩擦、改进控制或澄清 agent work？

4. Scope discipline
   - 是否删除或避免了不必要 surface area？
   - 是否创建了本应复用现有概念的新概念？
   - 是否处理用户明确 edge cases？

5. Behavioral completeness
   - 关键入口是否覆盖？
   - 空、正常、长文本、跨 org、mobile、direct-link、legacy-link 状态是否仍正确？

6. Trust and validation
   - agent 是否证明改动在用户关心状态下可用？
   - failed/skipped checks 是否与 passed checks 分开？

## Review 方法

1. 说明证据基础：session id、title、date、commit hash（如有）、检查的 files 或 plan docs。
2. 提前给 verdict：`accept`、`conditional accept`、`reject` 或 `needs more evidence`。有用时附分数。
3. 解释产品本质：一段话说明任务真正是什么，把 UI 词汇翻译为产品语言。
4. 说明做对了什么：关注产品决策，而不是实现忙碌。
5. 说明 gaps：优先产品正确性、行为缺口、遗漏 edge cases、验证缺口和 scope mistake；尽量引用文件、行、测试或 session events。
6. 推荐下一步：一个务实 follow-up，而不是 wishlist。说明 keep direction、patch behavior、rewrite spec、gather evidence 或 reject and reframe。

## 输出形态

用户用中文时默认中文。保持 compact：

```markdown
结论：...

我会给这次任务：7/10，conditional accept。

做得好的地方：
- ...

关键缺口：
1. ...
2. ...

下一步建议：...
```

高风险 review 可增加：

- Evidence inspected
- First-principles diagnosis
- Product acceptance criteria
- Residual risks

不要把 verdict 埋在长 transcript summary 后面。

## 判断规则

- session 可以方向正确但产品未完成。
- typecheck/build 通过不证明产品行为。
- E2E launch 失败本身不一定是产品失败，但相关用户流仍未验证。
- 可见 UI 任务只有检查了相关 rendered states 或明确标记 unverified，才算完整 review。
- “太多 items”应作为体验问题 review，而不仅是渲染限制。
- compatibility paths 不应保留旧的错误心智模型。
- 最好的 review 会说保留哪部分、修哪部分，以及为什么。

## 常见 findings

- 产品对象建模错误：history 当 view、settings 当 content、workflow state 当 global preference。
- 入口不完整：只记录 list clicks，漏掉 detail、board cards、sidebar links、deep links 或 mobile paths。
- 验证不匹配：tests 覆盖新 API，但不覆盖实际 operator path。
- Edge-case theater：代码处理数量限制，但没判断该限制是否是正确产品体验。
- 过度 scope：本应小恢复 affordance，却新增 management UI。
- scope 不足：移动了 UI，但底层 behavioral contract 仍不一致。

## 边界

review 期间不要编辑代码，除非用户明确要求修 findings。若要求修复，切换到正常实现模式并遵循 repo validation 和 commit 规则。

不要仅凭 logs 声称确定用户满意。此类判断应表述为基于证据的判断，而不是真理。

不要长篇引用 transcript。总结证据并引用重要本地路径或 commit hashes。
