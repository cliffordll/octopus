---
name: octopus-ui-polish-maintainer
description: >
  执行截图驱动的 Octopus UI polish 和窄范围可见交互修复。当用户指向 Octopus 页面或截图，并要求调整密度、对齐、badge、label、card、menu、hover affordance、空状态、冗余页面、onboarding 步骤或其他小到中等 UI 行为时使用，尤其是中文提示如“这里有点丑”“对齐一下”“去掉这个页面”“改成这个 UI”“先说说/优化一下”“弄个截图给我看”。即使用户提到 advisor/reviewer 技能，只要不是明确要求 reviewer agents、重复 review 轮次或验收门，窄 UI 修复也使用本技能。纯建议用 build-advisor；高风险 proposal 加 reviewer gate 用 advisor-review-loop-maintainer。
---

# Octopus UI Polish Maintainer

使用本技能把具体 Octopus UI 反馈转化为有范围的、已实现的、已验证的、已提交的改动。

目标不是完整重设计。目标是在保留 Octopus 密集、面向 operator 的界面的同时，修复用户注意到的具体视觉或交互问题。

## 使用场景

用于 Octopus UI 任务，例如：

- 截图驱动的视觉 polish
- 对齐、行高、间距、密度、溢出或 hover 修复
- 增加小状态 badge、label、icon、menu 或 affordance
- 简化设置区块或冗余解释文案
- 删除不再属于产品的页面或路由
- 修改空状态、onboarding 步骤、教程跳转或小工作流界面
- 本地改动后快速产出当前 UI 截图

如果用户明确问“你懂我要怎么改吗”“先说说”，或想先确定产品/设计方向，先用 `build-advisor`。方向接受后，再按本技能实现。

用户要求 reviewer agents、两轮、proposal review 或验收门时，用 `advisor-review-loop-maintainer`。

如果用户为小可见修复调用 `advisor-review-loop-maintainer`，但只说“修一下”“优化一下”“去掉这个 button”“颜色不对”等，把本技能作为轻量实现契约。交接时明确说明这是轻量 advisor route，不是完整双 reviewer loop。

## 不使用场景

不要用于：

- 大型架构重构或大 feature 构建
- 没有 UI 改动的纯代码 review
- 核心问题是“为什么页面没数据”的数据诊断；用 `octopus-data-path-diagnostician-maintainer`
- 截图/demo 数据创建；用 `mock-data-maintainer`，必要时再用 `landing-proof-shots-maintainer`
- release、CI、Desktop 打包或浏览器自动化基础设施问题

## 默认工作流

### 1. 解析意图和模式

编辑前分类 prompt：

- `advice-only`：用户要讨论、判断或选项。
- `implement`：用户要修、优化、删除、添加或“改一下”。
- `screenshot`：用户要当前渲染 UI 截图。
- `review-gated`：用户调用 reviewer 或要求通过 review。

`advice-only` 输出最小有用 UI 方向并停止。`implement` 直接改代码。如果用户给截图但语言模糊，从图片和周边产品状态推断具体痛点。

### 2. 构建小证据包

只收集该 UI surface 所需上下文：

- 当前 route、component 和 API client
- 相关近邻测试
- 布局敏感时的 `doc/DESIGN.md`
- invent 新 UI 前检查现有组件、token、icon 和 status label
- 用户提供或要求视觉证明时的截图/浏览器状态

编辑前运行 `git status --short --branch`。保留无关 dirty worktree。

### 3. 做最小一致 UI 改动

优先本地产品一致性，而不是通用设计模式：

- 复用现有 Octopus 组件和状态词汇
- 保持操作界面紧凑、可扫读、冷静
- 删除冗余文案，而不是在 UI 里解释 UI
- 避免 card 套 card
- 避免装饰抢工作内容注意力
- 控件可发现但不要过大
- 编辑 input/composer 时保留键盘、选择、复制和无障碍行为

添加 issue status 等可见状态时，使用上下文 snapshot 或 API response 的真实现有数据。不要为了好看硬编码状态文案。

### 4. 保持 contract 对齐

如果 UI 改动需要新数据，追踪 contract：

- shared type 或 validator
- server route 或 service response
- UI API client 和 component props
- tests 和 E2E 期望

不要在视觉 polish 任务中悄悄引入 org scoping、permission 或 persistence 改动。如果确实需要，明确指出并作为 feature work 定义范围。

### 5. 验证行为和视觉结果

先运行最窄有意义自动检查：

- 触碰 surface 的 component/page test
- 用户可见流程变化时的 E2E
- shared contract 变化时的 typecheck/build

可见 UI 改动必须用浏览器、Desktop shell、截图或等价视觉检查验证渲染结果。优先使用可用浏览器自动化。本地 route 浏览器验证被阻塞时，说明准确 blocker，不要声称视觉已证明。

对用户后续纠正如“颜色不对”“没修好”，先再次检查渲染状态再改。把用户截图当作前次 proof 不完整的证据，不要盲修。

临时截图放 repo 外，例如 `/tmp`。

### 6. 只提交本任务

验证后只 stage 本任务改动。不要包含无关 dirty worktree。使用 Conventional Commit，例如：

- `fix: align automation settings rows`
- `feat: show issue status in messenger cards`
- `chore: remove redundant organizations settings page`

当仓库规则和分支状态允许时推送当前分支。

## 输出期望

实现任务交接包含：

- 产品层面改了什么
- 关键文件
- 运行的验证和被阻塞的检查
- 可见改动的截图路径或渲染证明
- 提交 hash 和 push 状态（如果提交）

纯建议任务交接包含：

- 产品诊断
- 推荐 UI 方向
- 明确非目标
- 用户批准后的实现形态

## 常见失败模式

- 用大重设计过度解决小截图抱怨。
- 每个小截图问题都走完整 advisor/reviewer loop，而轻量 polish 足够。
- 把视觉问题当纯 CSS，实际是错误数据、错误路由或冗余对象模型。
- 浏览器自动化超时后仍声称视觉已验证。
- 发布看起来漂亮但读的是 stale/mock 数据的状态 badge。
- 把无关 dirty 文件混进 commit。
- 对每个小 UI tweak 使用 `advisor-review-loop-maintainer`，拖慢只需聚焦 polish 的工作。
