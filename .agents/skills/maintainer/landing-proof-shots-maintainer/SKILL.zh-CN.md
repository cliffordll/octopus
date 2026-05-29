---
name: landing-proof-shots-maintainer
description: |
  维护 Octopus landing-shot 工作流。当用户想要 polished app screenshots，或想要一个已 seed 的 dev/demo organization 以便自行截图时使用。强制使用 full-page whole-app screenshots，而不是 browser-window 或 cropped partial captures。
---

# Landing Proof Shots Maintainer

使用本技能维护可靠、可展示的 Octopus landing page 和 demo screenshot 工作流。

本技能支持两种运行模式，除非用户已经选择，否则一开始要同时说明：

1. capture mode：seed org 并为用户截图
2. seed-only mode：seed org 后交还环境，让用户自行截图

重要：

- 两种模式都必须使用 `mock-data-maintainer` 维护的 landing-quality mock dataset
- seed-only mode 不是轻量 fallback dataset
- 用户要求 landing-shot dataset 时，不要替换成小 import、partial org copy 或简化 sample

## 使用场景

- landing page screenshot generation
- demo deck 产品静态图
- seed 一个真实感 Octopus org 供用户自行截图
- 请求如：
  - “mock some real-looking org data and screenshot it”
  - “give me demo data and I'll screenshot it myself”
  - “don't give me browser screenshots”
  - “each major feature should have a screenshot”
  - “include chat creating an issue”
  - “show issues across multiple projects”

## 不使用场景

- 不要求真实感的临时 debugging screenshots
- Octopus 之外的通用 desktop screenshots
- 用户要求整页时，只截单个 widget 的窄 cropped captures
- 用户只想要一次当前状态，不需要 seeded data

## 核心产出

产出以下之一：

- 可直接展示的完整 screenshot set
- seeded dev/demo org 及清晰 route，让用户自行截图

底层 demo data 两种模式相同，来自 `mock-data-maintainer`：

- 同样真实的 projects、issues、agents、approvals、chat、costs、org data
- 同样 screenshot-worthy 的密度和状态
- 同样支持主要 feature surfaces

基线质量：

- 没有 browser chrome
- 没有 desktop wallpaper 或 OS overlays
- 没有 stale 或 broken pages
- 没有明显假的 empty-state data
- full-page whole-app screenshots，而不是裁切子区域

## 默认位置

主要输出通常在：

- `/tmp/octopus-landing-proof-shots/shots`
- `/tmp/octopus-landing-proof-shots/manifest.json`

## 必须先决定模式

### Mode A: 为用户截图

用户要完整 screenshot bundle 时使用。

交付：

- seeded org
- screenshot files
- manifest
- final file list

### Mode B: seed 后让用户自行截图

用户希望你准备数据，但自己驱动 capture 时使用。

交付：

- seeded org name 和 id
- base URL
- 值得打开的精确 routes
- 本地所需 credentials 或 runtime notes

切换到 seed-only mode 后不要继续截图，除非用户要求。但 seeded data 质量必须与 capture mode 相同。

## 默认工作流

### 1. 定义 surface list

把请求映射为具体 screenshot set。

常见默认集合：

- dashboard
- chat proposal review
- chat created-issue state
- issue list
- issues across multiple projects
- approval review
- heartbeats
- costs
- org structure

如果用户要求更重的 issue 覆盖，capture 前 seed 更多项目和跨项目 issue 密度。

### 2. Seed 隔离 demo org

优先使用 repo 现有 mock-data seed/capture 脚本：

```bash
LANDING_SHOTS_SKIP_CAPTURE=1 LANDING_SHOTS_HOLD_OPEN=1 \
node cli/node_modules/tsx/dist/cli.mjs \
.agents/skills/maintainer/mock-data-maintainer/scripts/capture-landing-proof-shots.ts
```

原因：

- 创建隔离 Octopus instance 用于 landing shots
- seed 真实感 projects、agents、issues、approvals、chat、costs 和 org data
- 避免污染开发者正常本地环境

legacy `scripts/capture-landing-proof-shots.ts` 只是兼容 wrapper；dataset 和实现位于 `mock-data-maintainer`。

seed-only mode 仍使用同一 seeded dataset，只是 capture 责任变化。

记录：

- `baseUrl`
- seeded org id 和 issue prefix
- chat id
- approval id
- output directory

### 3. Capture 前验证环境

确认 instance alive 前不要截图。

检查：

```bash
curl http://127.0.0.1:3101/api/health
curl -I http://127.0.0.1:3101/RUD/dashboard
```

规则：

- health 失败先恢复 seeded instance
- 不要对 dead port 继续调截图
- browser tooling 中 `localhost` 不稳定时优先 `127.0.0.1`

### 4. 截完整 app 页面

这是最重要约束。

截图时：

- 截该 route 的完整 Octopus 页面
- 包含该状态下的完整 app shell
- 避免 component-only 裁切
- 除非用户明确要细节图，否则避免 locator clips

最终 PNG 中用户应看到：

- 完整页面 surface
- 正确 layout、hierarchy 和 surrounding context
- 没有 browser tabs、URL bar 或 browser chrome

错误：

- 只有 chat panel
- 只有 issues table
- 只有 modal body
- 浏览器窗口的桌面区域截图

正确：

- 整个 page route 渲染成干净 app screenshot

### 5. 优先 app-style capture，不拍浏览器窗口

默认 capture path：

- Playwright
- 必要时 system Chrome executable
- 保留 whole app page 的 page-level screenshot flow

默认避免：

- 手动 desktop screen capture
- 带 URL bar 或 tabs 的 browser-window photos
- monitor-region crops

### 6. 有意制造 stateful screens

某些截图需要先交互。

chat issue creation：

1. 打开 seeded chat
2. 提交会创建 issue proposal 的用户请求
3. 等待 proposal review block
4. 截 proposal state 的完整 chat page
5. 批准
6. 等待 “Created issue ...” 状态
7. 再截 created-issue state 的完整 chat page

issue coverage：

- 需要时 seed 多个 projects
- 创建足够 issues，让页面像工作中的 org
- 如果需求包含跨项目，确保 issue list 可见跨多个 projects
- 截完整 issues page，不只截 table region

### 7. 生成 manifest

截图后写 manifest，使 bundle 可检查、可复用。

字段：

- generation timestamp
- base URL used
- screenshot filenames
- mode：`capture` 或 `seed-only`
- 环境或方法简短 notes

### 8. 清晰交接

capture mode 返回：

- screenshot directory
- final file list
- manifest path

seed-only mode 返回：

- org name and id
- base URL
- 用户应打开的 routes
- 影响本地 capture 的 caveat

不要交付降级 org。用户应能截图与 capture mode 相同的 surfaces。

## 判断规则

### 必须保持

- screenshots presentation-ready
- data 像真实运行组织
- screenshots 覆盖用户要求的主要 product surfaces
- chat 和 issue screenshots 显示有意义状态，而非空壳
- issue-heavy 页面在请求时应明显跨多个 projects
- 默认 full-page whole-app capture 优先于 clipped partial capture

### 避免

- demo server 已死还继续
- 用户要求 app-style shots 时使用 browser chrome screenshots
- 把 browser-launch 问题误当 Octopus page failure
- 用户要求页面时裁成单个 component
- 把无关个人浏览器状态混进 demo capture
- 把 seed-only mode 当作使用更小或不同数据的许可

## 故障排查

### Health checks 失败

- 重启隔离 landing-shot seed instance
- app 可达前不要调 capture

### Browser 打开但内容错误

- 不要假设新浏览器窗口成功创建
- capture 前验证实际 page URL 和 route state
- 在 capture flow 中优先直接 Playwright navigation

### Capture 像浏览器截图

如果图片包含 browser tabs、URL bar、toolbars、desktop wallpaper、window thumbnails 或缺失页面上下文的裁切内容，方法错误。

切回干净 whole-page app capture。

### Bundled Playwright browser 启动失败

- 用 system Chrome 的 `executablePath`
- 保持同样 page-level capture flow

## 输出期望

成功 capture mode 留下：

- `/tmp/octopus-landing-proof-shots/shots` 中完整 screenshot set
- `manifest.json`
- 可直接用于 marketing 或 product presentation 的 app-style PNGs

成功 seed-only mode 留下：

- live seeded Octopus org
- 自助 capture 的清晰 routes
- 足够真实的数据，用户无需先做更多准备

## 非目标

本技能不负责：

- 截图前重设计 UI
- 编辑 landing page 本身
- 写解释截图的文案

如果用户要求，这些可在截图或 seeding 工作流之后进行。
