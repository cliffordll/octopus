---
name: octopus-data-path-diagnostician-maintainer
description: >
  诊断 Octopus 页面或产品界面中缺失、陈旧、稀疏或错误的数据。当用户问为什么 dev/prod/local Octopus 屏幕没有 Calendar events、runs、issues、计数错误、dashboard 空、chat 输出坏掉，或问“这个数据从哪来”“为什么这里没数据”“prod z studio 下的数据怎么没了”“是不是 UI/API/DB 的问题”时使用。在提出修复或 seed 变化前，从 UI query 到 API route、service aggregation、database rows、derived sources、org scoping 和 runtime instance 追踪证据链。
---

# Octopus Data Path Diagnostician Maintainer

当用户真正的问题是 Octopus surface 没显示预期数据时使用。

目标是产出有证据支撑的数据 lineage 和根因，而不是从截图猜。此类失败多数由以下原因导致：

- runtime 或 organization 错误
- source records 为空
- filter 或 date-window 不匹配
- derived data 没从用户预期的 records 生成
- API/service aggregation 缺口
- UI rendering 或 state merge bug
- 陈旧 seed/demo 假设

本技能也有解释模式。当用户问“这个数据从哪来”或“现在的渲染逻辑是怎样的”，且数据不再缺失时，解释从 UI query 到 API route、service aggregation、derived records 和 rendering states 的 lineage。解释模式中只读源码追踪可能足够；当代码和 API contract 已能回答时，不强制查数据库。

## 使用场景

用于：

- “为什么 Calendar 没数据”
- “这个 Dashboard 怎么是空的”
- “prod z studio 下这里怎么没有 run / issue / calendar”
- “这个 UI 的数据从哪里来”
- “看起来应该有数据，但页面没有显示”
- “这个数字和数据库/API 对不上”
- “是不是 seed 数据没有写进去”

适用于 dev、prod-local Desktop、worktree previews 和 local production-style instances。

## 不使用场景

不要用于：

- 单个 agent run transcript 失败；用 `debug-run-transcript-maintainer`
- 从零创建 demo 或 screenshot 数据；用 `mock-data-maintainer`
- 数据已知的纯 UI polish；用 `octopus-ui-polish-maintainer`
- CI、release、npm、Desktop packaging 或 Chrome automation infrastructure
- 组织或数据库破坏性清理，除非用户明确授权该独立操作

## 默认工作流

### 1. 确认症状和目标环境

先固定：

- surface：页面、route、tab、card、chart 或截图区域
- expected data：用户认为应该出现什么
- actual data：实际可见或返回什么
- runtime：dev、prod-local Desktop、worktree preview 或 remote deployment
- organization：org id、URL key、display name 或 selected org
- 相关时的 date window、filters、selected project/agent

深查前分类模式：

- `diagnosis`：预期数据缺失、陈旧、稀疏或错误。
- `explanation`：用户想在可见症状解决后理解渲染或 derivation 逻辑。

解释模式中聚焦当前代码路径和 source hierarchy。仍需说明影响答案的 runtime、org 或 date window 假设。

先验证 live target，再相信假设：

```bash
curl -sS <base-url>/api/health
curl -sS <base-url>/api/orgs
```

对 prod-local 或 Desktop 调查，检查或写数据前必须证明 active runtime 是预期本地环境。

### 2. 识别 UI 数据请求

找到 feeding surface 的 component 和 data hook/API client。记录：

- query key 或 effect dependency
- endpoint path 和 parameters
- selected org/project/agent/date filters
- fallback、loading、error、empty-state 行为
- client-side merge 或 normalization 逻辑

不要停在“component 渲染空数组”。追踪数组从哪里来。

### 3. 检查 API 和 service 链

沿 endpoint 进入 server code：

- route path 和 auth/org access checks
- request validators 和默认 date windows
- service function 和 aggregation logic
- derived sources，如 heartbeat runs、automation runs、activity、messenger context snapshots、calendar projections、cost rows 或 external sync tables
- response shape 和 filtering rules

比较 route 行为和 UI 期望。很多 bug 不是缺 row，而是对 authoritative source 的假设不一致。

### 4. 安全读取 source data

先使用只读 API 调用或 SQL 查询。验证：

- 所选 organization 有 records
- timestamps 位于 UI date window 内
- statuses 符合 service filters
- linked ids 存在，并指向预期 issue、agent、project、run、automation 或 conversation
- soft-deleted、archived、hidden 或 permission-gated rows 未被误认为可见数据

每个查询都要 organization-scoped。诊断期间不要写入、reseed 或删除数据，除非用户明确把任务从 diagnosis 改为 repair。

### 5. 分类根因

使用一个主分类：

- `wrong-target`：浏览器或进程指向错误 instance 或 org
- `source-empty`：source table/API 没有匹配 records
- `filter-window`：数据存在，但 date/status/project/agent window 排除了它
- `derived-gap`：source records 存在，但 derived feed 未生成或未链接
- `contract-gap`：API response 缺少 UI 需要的数据
- `render-gap`：API response 正确，但 UI state/rendering 隐藏了它
- `seed-gap`：预期 demo/fixture 数据未 seed 到目标
- `sync-gap`：外部 provider 或 import 未产出本地 records

如果多个原因共同作用，识别第一个坏掉的边界和下游症状。

### 6. 推荐或实现修复

默认报告诊断和修复选项。只有用户要求修复，或下一步安全代码改动明显时才实现。

修复应匹配原因：

- wrong target：把 browser/process 指到正确 runtime 并验证
- source empty 或 seed gap：用 `mock-data-maintainer` 或 scoped seed path
- filter-window：调整 UI 默认值或让 filters 可见
- derived gap：修 service aggregation 或 generation logic
- contract gap：同步 shared/server/UI contract 和 tests
- render gap：修 component state/rendering 并视觉验证
- sync gap：修 provider sync 或报告外部前置条件

用户可见行为变化时，按 repo 规则添加或更新 E2E。

## 输出形态

最终答案保持具体：

```markdown
Root cause: <classification and one-sentence cause>

Evidence:
- UI requested ...
- API returned ...
- Source data shows ...
- Service logic does ...

Fix:
- ...

Validation:
- ...
```

有用时附短 lineage：

```text
Calendar page -> GET /api/orgs/:orgId/calendar/events
  -> calendar_events rows
  -> heartbeat_runs projections
  -> projected heartbeat schedules
```

## 安全规则

- 诊断默认只读。
- 任何写入前验证 runtime 和 organization。
- 绝不对 production-like data 使用未 scoped SQL。
- 不要发明 demo records 来掩盖 bug。
- 不要把“没有持久 rows”误认为“没有产品数据”，有些 surface 有意从 runs、schedules 或 activity 派生。
- 用户给截图时，用它定位症状，不把它当作 backend state 证明。

## 交接规则

如果代码改变，遵循正常 Octopus validation、commit、push 规则。只 stage 本任务文件，排除无关 dirty worktree。

如果没有代码改变，交接确切当前状态和下一步 repair command 或文件路径。只解释了 data lineage 时，不要声称问题已修复。
