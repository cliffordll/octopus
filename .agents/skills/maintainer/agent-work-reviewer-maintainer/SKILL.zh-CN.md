---
name: agent-work-reviewer-maintainer
description: >
  Review Octopus agent work。用于 review/第一性原理/PM review Codex sessions、PRs、commits、UI、releases、regressions 或 agent outcomes。功能或 UI review 时，如果可用，优先用 Browser 或 Computer Use 运行真实 Octopus 场景，而不是只看 diff 判断。
---

# Agent Work Reviewer Maintainer

Review 已完成或进行中的 Octopus agent work。这是 reviewer workflow，不是 implementation workflow。

核心问题是：

> agent 是否解决了正确产品问题，使用正确对象模型，行为完整，验证可信，并有干净 handoff？

用户用中文时默认中文。verdict 要尽早给出，每个判断都要基于证据。

## 使用场景

用户要求 review 以下内容时使用：

- Codex session、Octopus agent run、task 或 transcript
- 本地 branch、commit、diff、pull request 或 implementation
- 产品 proposal、plan doc、feature spec 或 UI direction
- release verification、Desktop install path、npm publish 或 canary/stable handoff
- 截图、browser state、视觉交互或“感觉不对”的 workflow

常见触发：

- “review 一下 codex session id ...”
- “as a 专业产品经理 review”
- “第一性原理思考一下”
- “作为 reviewer”
- “这个实现是不是产品上对”
- “这个 PR 本地跑起来看一下有没有问题”
- “这次 release 验证做完了吗”
- “我觉得这个功能之前有，现在没了”

## 不使用场景

不要用于：

- 同一 reviewer pass 中修 findings，除非用户明确要求实现修复
- 产品判断无关的通用逐行 code review
- 只调试 Octopus agent run 失败根因；先用 run transcript debugging，再回到本技能做产品/workflow 判断
- 没有 verdict 或 acceptance criteria 的日志总结

如果用户在 review 后要求修复 findings，切换到正常实现模式，并遵循 repo validation、commit、push 规则。

### Read-Only Guard

Reviewer mode 默认只读。除非用户明确把任务从 review 改为 implementation，否则不要编辑文件、stage、restore、commit、push、启动破坏性清理或“顺手修” findings。

如果用户说“do not implement”“review only”或分配 reviewer 角色，该指令在整个 reviewer pass 中都有效。工具只用于检查证据。

Browser、Desktop 或 Computer Use 的直接 UI 检查在只观察或执行低风险 local/dev flow 时仍属于 reviewer work。若真实场景需要修改 Octopus 数据，优先隔离 dev org、一次性 test records 或 existing preview instance，并报告创建或改变了什么。未经适当确认，不要删除数据、发布、提交外部通信、安装软件、改系统设置或做其他高风险 UI 操作。

## 证据包

不要从观点开始。构建能支持真实判断的最小证据包。

### 1. 识别目标

解析被 review 的对象：

- Codex session id 或 prefix
- Octopus run id 或 transcript
- PR number 或 URL
- branch name、commit hash、staged/unstaged diff
- plan doc、proposal、screenshot 或 browser URL
- release version、tag、workflow run、npm dist-tag 或 Desktop asset set

用户模糊时，先从当前 branch、recent commits、open browser state 或 named files 推断，再询问。

### 2. 收集任务意图

Codex sessions 搜索：

```bash
rg "<session-id-or-prefix>" ~/.codex/session_index.jsonl ~/.codex/sessions ~/.codex/archived_sessions
```

提取真实用户请求和纠正。忽略注入的 `AGENTS.md`、environment context、skill bodies 和 system/developer text。

branches、PRs、commits 或 diffs 检查：

```bash
git status --short --branch
git log --oneline --decorate -12
git diff --stat
git diff
git show --stat <commit>
git show <commit>
```

PR review 时读取 PR description、changed files、review comments 和 CI status。

### 3. 阅读产品上下文

多数 Octopus 产品工作只读相关部分：

- `doc/GOAL.md`
- `doc/PRODUCT.md`
- `doc/SPEC-implementation.md`
- 可见 UI/交互工作读 `doc/DESIGN.md`
- 存在 task plan 时读 `doc/plans/` 下对应计划

release/Desktop/package 工作还使用：

- `doc/RELEASING.md`
- `doc/PUBLISHING.md`
- `doc/DESKTOP.md`
- `.github/workflows/release.yml`
- `.github/workflows/desktop-release.yml`

database/API 行为检查跨层 contract：

- `packages/db`
- `packages/shared`
- `server`
- `ui`

### 4. 验证证明了什么

区分“实现了”和“证明了”。

记录证据：

- typecheck、unit tests、build
- E2E tests 或 release smoke tests
- browser 或 Desktop visual verification
- 可见 UI 的 screenshots
- startup、migrations、profile routing 或 installer changes 的 packaged Desktop verification
- release tasks 的 npm/GitHub Release/live workflow checks
- commits、pushes、branch state、PR URL 和 merge state

超时、跳过或尝试过的 checks 是 unverified，不是 passed。不要把“代码看起来合理”转成产品证明。

### 4.1 重要时运行真实场景

functional review、UI review、Desktop review 或 workflow-regression review 中，优先直接场景验证，而不是 code-only inference：

- Browser 用于 local web targets，如 `localhost`、`127.0.0.1` 或 file previews。
- Computer Use 用于 packaged Octopus Desktop app、native dialogs、update prompts、menus、resident shell behavior、drag/drop 或只能在本地 Mac UI 可见的 flow。
- API/log/database checks 是支持证据，不替代真实 operator path。
- app 未运行时，如果安全且属于 review scope，启动适当 local 或 packaged Octopus path。启动昂贵或有风险时，说明 review 限制。
- 跳过真实场景时，verdict 通常应为 `needs more evidence` 或 `conditional accept`，并命名缺失场景。

用户可见工作中，如果 Browser 或 Computer Use 可低成本验证实际交互，不要把“tests pass”当作足够证明。最低可信证据是观察到的 workflow state 加相关 logs、API responses、screenshots 或 failure messages。

### 5. 组装 review packet

写 verdict 前明确 review packet，包含相关子集：

- target：session、run、PR、branch、commit、diff、proposal、screenshot、release 或 browser state
- user intent：原始请求和重要纠正/约束
- changed object：被 review 的 product/workflow/code object
- evidence inspected：files、diffs、logs、screenshots、docs、plans、tests、CI、browser/Desktop state、release artifacts 或 sub-reviewer notes
- validation status：passed、failed、timed out、skipped、inferred
- unresolved evidence gaps：缺截图、缺 E2E、未查 downstream consumers、branch/CI 不确定、public surfaces 未验证

缺少可信判断所需 packet item 时，用 `needs more evidence` 或 `conditional accept`，不要用自信填空。

## 第一性原理 review 框架

### 1. User Job

该任务要解决哪个真实 operator 或 contributor 问题？请求是否是更深 workflow 问题的症状？

示例：

- “Move recent views” 可能意味着 navigation history 被错误建模为 content。
- “Where did my draft issue go” 是 lifecycle 和 recovery 问题，不只是 sidebar rendering bug。
- “Calendar blocks are unreadable” 是 time-density visualization 问题，不只是 card styling。

### 2. 产品对象模型

识别被改变对象：

- view 或 navigation shortcut
- workflow state
- draft、issue、goal、project、run 或 artifact
- external source
- preference 或 setting
- release/version/install surface
- agent memory、instruction、skill 或 operating contract

判断实现是否把它建模为正确对象。很多 Octopus 回归来自把 workflow state 当 static view，把 setting 当 content，或过早把 external source 当 imported local object。

### 3. Core Loop Impact

问该工作如何影响 Octopus north-star loop：真实 agent work 端到端完成。

好的改动减少 operator friction、澄清 agent state、保留控制或让 review/handoff 更容易。弱改动增加 surface area，却没有让 agent-work loop 更可控。

### 4. Scope Discipline

检查工作是否：

- 保留 organization scoping 和 permissions
- 复用现有产品概念，而不是创造新概念
- 删除半成品 surface area（当删除才是正确产品动作）
- 避免把兼容路径变成永久错误心智模型
- 处理用户明确要求的 edge cases

### 5. Behavioral Completeness

检查关键入口和状态：

- list、detail、direct link、sidebar、board card、mobile、legacy link
- empty、normal、long text、cross-org、permission denied、loading、error
- workflow 中的 start、active、blocked、done、review、reopen、retry

### 6. Trust and Validation

检查已证明什么、未证明什么。可见 UI 必须有 rendered state 或 screenshot evidence；release/Desktop 必须有 live 或 packaged evidence；API/DB contract 改动必须跨 shared/server/UI 验证。

## 输出形态

默认中文时：

```markdown
结论：conditional accept。

证据：
- ...

做对的地方：
- ...

阻塞缺口：
1. ...

非阻塞建议：
- ...

下一步：
- ...
```

verdict 可选：`accept`、`conditional accept`、`reject`、`needs more evidence`。

## 判断规则

- “方向对”不等于“产品完成”。
- 没有真实场景或 screenshot 的 UI review 只能 conditional。
- release review 不能只看 local build，要看 npm、GitHub Release、Desktop assets 和 public install path。
- failed/skipped checks 必须显式披露。
- 如果最小修复会改变产品模型，应要求重新 framing，而不是只给 patch。

## 常见 findings

- 产品对象建模错误。
- 入口覆盖不完整。
- 验证覆盖 API 但不覆盖 operator path。
- edge case 只是表演式代码分支，没有解决真实体验。
- scope 过大或过小。
- UI 状态漂亮但读的是 stale/mock/wrong-org data。
- release 声称完成，但 public install 或 asset checks 未验证。

## 边界

本技能本身不修代码。用户要求修复时切换到实现模式。不要长篇引用 transcript；总结证据并引用关键本地路径、commit 或截图。
