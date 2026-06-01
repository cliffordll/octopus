---
name: mock-data-maintainer
description: |
  为 Octopus 开发、本地测试、本地截图、产品 demo 和用户场景解释创建真实、连贯的 mock/demo/seed 数据。当用户要求 mock data、demo data、seed data、fake-but-realistic records、test fixtures、screenshot data、synthetic app states、CSV/JSON/SQL/TypeScript seed outputs，或能帮助用户理解 workflow 的数据时使用。Octopus landing screenshots 和 demo orgs 应复用本技能的 landing demo org dataset，并与 landing-proof-shots-maintainer 协同截图。
---

# Mock Data Maintainer

使用本技能创建有用、连贯、易复用的 mock data。目标不是随机 fake records，而是支持测试、截图、demo 和清晰用户理解的 scenario data。

## 第一个决策

生成数据前，先把请求分类为一个主意图：

1. testing data：local dev、E2E、bug reproduction、contract checks、edge states
2. screenshot/demo data：local screenshots、landing proof shots、README、decks
3. user-scenario data：解释 workflow、persona、problem 或 product value
4. static artifact data：CSV、JSON、SQL、Markdown table 或 TypeScript fixture

如果 prompt 暗示多个意图，产出一个共享 scenario spine，再为各输出适配。例如一个 Octopus launch-week org 可同时服务本地截图、workflow 解释和 E2E fixture 设计。

## 参考选择

只读取请求所需 references：

- `references/scenario-index.md`：场景目录和选择规则
- `references/quality-bar.md`：真实感、确定性、隐私和输出规则
- `references/octopus-studio-scenario.md`：标准“Octopus 用 Octopus 构建和增长 Octopus”的月度 org，含 reusable JSON fixtures 和 seed script
- `references/octopus-landing-demo-org.md`：标准 screenshot-ready Octopus org
- `references/octopus-test-fixtures.md`：Octopus 测试和 edge-state fixtures
- `references/octopus-user-scenarios.md`：Octopus user stories 和 scenario spines
- `references/generic-saas-dashboard.md`：SaaS metrics、billing 和 ops data
- `references/generic-crm-sales.md`：CRM、pipeline、account 和 support data
- `references/edge-states.md`：empty、error、boundary、permission 和 conflict states

## 内置脚本

用户需要 live Octopus data 而不是 static records 时使用内置脚本：

- `scripts/capture-landing-proof-shots.ts`：启动隔离 Octopus instance，seed 标准 landing demo org，并可选 capture proof-shot screenshots。使用 `LANDING_SHOTS_SKIP_CAPTURE=1 LANDING_SHOTS_HOLD_OPEN=1` 准备 seed-only 本地截图。
- `scripts/seed-octopus-studio.ts`：把可复用 Octopus Studio org seed 到正在运行的 local dev instance。用户需要真实月度 Octopus org、“using Octopus to build Octopus”、自然 Calendar work history 或 durable user-scenario data 时使用。

优先这些脚本，而不是在一次性回答里重写 seed flow。

## 默认工作流

1. 识别 data intent 和 target surface。
2. 从 reference catalog 选择或组合 scenarios。
3. 定义 scenario spine：
   - 用户/persona 是谁
   - 他们想做什么
   - 数据应揭示什么冲突、风险或决策
   - workflow 前后发生了什么变化
4. Octopus 场景应扎根 production-like operator work。优先使用合成 records 加 sanitized Octopus 开发、release、support、growth 和 agent-ops 模式，而不是 generic SaaS examples。
5. 写 rows 前定义 entities 和 relationships。
6. 在能让场景更清楚时加入 time、status、priority、budget、ownership 和 failure signals。
7. 选择输出形式：
   - live seed command
   - TypeScript seed script
   - JSON fixture
   - CSV
   - SQL inserts
   - Markdown scenario brief
8. 包含 usage notes 和 reset notes。

## 输出形态

非平凡请求使用：

```markdown
## Scenario
- Intent:
- User story:
- Target surface:
- Data shape:

## Entities
- ...

## States Covered
- ...

## Output
...

## Usage
...
```

代码或 fixture 输出中，必要时使用 deterministic IDs。截图/demo 数据优先 readable names 和密集可信状态，而不是不透明 generated IDs。

## Octopus 特定规则

- 明确组织边界。属于 organization 的每个 Octopus entity 都应有清楚 org owner。
- 保持关系连贯：org -> goals -> projects -> issues -> agents、approvals、chats、heartbeat runs、costs 和 activity。
- 整体产品场景优先 causal scenario spine，而不是 component-specific fixtures。先从真实工作 records 出发，再让 Calendar、Dashboard、Messenger、approvals 和 cost views 反映这些 records。
- 用户要“Octopus Studio”“using Octopus to build Octopus”、真实月度 org 或应从 agent work 产生的 Calendar data 时，使用 `references/octopus-studio-scenario.md` 和 Octopus Studio fixtures。
- 截图数据要跨页面视觉可读，避免空壳。
- 产品截图要 seed 底层 run/output evidence：dashboard、agent detail、Calendar、Messenger 和 charts 应来自连贯 issues、heartbeat runs、run logs、comments、approvals、costs 和 calendar events，而不是孤立 component fixtures。
- product screenshot 或 installed app/local operator workflow claim 优先 Desktop-shell capture。窄 web UI 可用 browser capture，但最终 dataset 仍应在 Desktop shell 中可用。
- Dashboard、Calendar 和 agent run screenshots 必须包含非空 transcript/output evidence。若 seeded page 会显示空 transcript、空 run output 或装饰性 calendar-only blocks，视为 seed 不完整。
- Capture flows 必须先验证具体 screenshot surface，再声称成功。用 selectors 和 scenario-specific text/content assertions 检查页面，若页面空、stale 或 wrong scenario，应失败或报告 blocked。
- 测试数据要包含 deterministic setup 和 reset strategy。
- workflow explanation 要包含 persona、motivation、conflict、decision point 和 outcome。
- live `prod_local` 或 Desktop demo org seed 中，目标选择是数据任务的一部分。写入前验证 active runtime 和 database；陈旧 config defaults 不够。
- whole-org demo seeds 应优先通过 API 创建 organization，然后对 API 尚不完整的 richer downstream evidence 使用 scoped database insertion。
- 用户要求实际 landing screenshots 时，在 mock data 选定或 seed 后使用 `landing-proof-shots-maintainer`。

## Live Octopus Instance Seed Rules

向运行中的 Octopus instance seed 数据时，任何写入前先验证目标。

1. 用 `/api/health` 确认 live API target。
   - prod Desktop 或 local production data 要求 `localEnv=prod_local` 且 `instanceId=default`。
   - dev data 要求 `localEnv=dev` 且 `instanceId=dev`。
2. 不要只相信陈旧 config files。优先 live runtime descriptors、`/api/health` 和 active process/database connections。
3. API creation 可用时，用它创建顶层 organization，让 service-side defaults、memberships、labels、activity 和 policies 生效。
4. 只有缺少完整 public API 的 seed entities 才直接写 DB，并 scope 到已验证 org id。
5. 需要临时 probe write 时，清楚命名、记录 id、立即删除并验证删除。
6. destructively reseed 需要明确用户授权，或创建 pending approval record，使破坏性操作在 seeded organization 中可见。
7. 除非用户明确要求可复用 seed script 或 fixture，不要为了 seed live data 修改 repo source files。

whole-organization Octopus demo seeds 的必需 readback：

- organization 出现在 `/api/orgs`
- expected agents 存在
- expected goals、projects、issues 存在
- requested pending approvals 存在
- requested chat conversation 存在
- activity log 有代表性 events
- requested heartbeat runs 和 cost summary 存在
- primary UI route 返回 200
- 报告 organization id、URL key、counts 和 verification evidence

## 质量标准

好的 mock data 具有：

- 全部 records 之间有连贯故事
- 足够密度让 UI 状态有意义
- 测试需要的 edge states
- 自动化需要的 deterministic values
- 可信 names、statuses、timestamps 和 amounts
- 没有真实个人数据、真实客户 secrets 或复制的 private records

避免：

- 没有关联的 lorem ipsum rows
- 任何 SaaS/task board 都能套用的 generic use-case copy
- 只有完美 happy path
- 用户需要 whole workflow 时却过拟合单个 component
- 把 production-looking secrets 混进 examples
- 为了 mock data 方便而修改 schema 或 app behavior

## 交接

以用户可立即使用的具体 artifact 或 command 结束。若数据用于本地截图，包含 seed 后要打开的确切 route 或 local URL。若用于测试，包含 fixture entry point 和 reset expectation。

## 回归检查

### Use-case-led Octopus screenshot data

用户要真实 operator work 感的 Octopus screenshots/demo data 时，期望选择 Landing Demo Org 或 Octopus Studio，把场景扎根 sanitized Octopus-shaped work，先 seed issues/runs/logs/costs/approvals，再派生 Dashboard、Calendar、Messenger 和 agent-detail views。

不得返回 generic SaaS use cases、孤立 component rows 或 empty page fixtures。

### Desktop-shell product evidence

用户需要证明 installed local Octopus experience 的截图时，优先 Desktop-shell capture 或协调能 capture Desktop shell 的 screenshot skill。browser screenshots 只作为窄 route checks 的辅助证据。

### Prod Desktop demo org seed

用户要求在 prod 中用 source document 初始化新 organization 时，验证 `/api/health` 报告 `localEnv=prod_local` 和 `instanceId=default`；尽量通过 API 创建 organization；按 scope seed agents、goals、projects、issues、approvals、chats、activity、runs、costs 和 calendar evidence；验证 API readback 和 primary UI route；报告 org id、URL key、counts 和 evidence。

不得写 dev database、只依赖陈旧 config ports、留下 temporary probe records，或仅凭 DB counts 声称成功。

### Existing demo org collision

reseed 可能已存在的 organization 时，按 name、URL key 和 issue prefix 检测 existing orgs；分类为 additive 或 destructive；替换 seeded records 前需要明确授权或 pending approval；所有改动 scoped 到已验证 target organization。

### Static fixture only

用户只要 JSON、SQL、CSV 或 Markdown fixture，并说明不要写本地 Octopus 时，产出静态 artifact 和 usage/reset notes。不得调用 API、连接 DB、创建 probe records 或修改 prod/dev state。

### Screenshot capture validation

capture script 或手动 flow 保存 Dashboard、Calendar、chat、approval 或 agent run screenshots 时，必须 assert page selectors 加 scenario-specific text 和非空 transcript/output evidence 后才声明成功。
