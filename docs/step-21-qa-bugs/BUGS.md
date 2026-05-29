# Step 21 Bug Ledger

本文件是 Step 21 的唯一 Bug 清单。所有最小闭环审查、调试和代码复查发现的问题必须先记录到这里，再决定修复或排期。

## 状态说明

- `open`：已确认存在，尚未处理。
- `in_progress`：正在修复或验证。
- `fixed`：已修复并有验证证据。
- `deferred`：不阻塞最小闭环，已排入后续 Step。
- `invalid`：复查后确认不是 Bug，必须记录原因。

## 严重级别

- `P0`：阻断最小闭环，必须在 Step 21 修复或说明外部阻塞。
- `P1`：影响核心调试/执行路径，优先在 Step 21 修复。
- `P2`：不阻断闭环，但会影响后续功能开发或兼容性。
- `P3`：文档、提示、可维护性或低风险问题。

## Bug 清单

| ID | 状态 | 级别 | 阻塞闭环 | 标题 | 归属 | 验证证据 |
| --- | --- | --- | --- | --- | --- | --- |
| BUG-21-001 | open | P1 | 待确认 | 智能体说明文件右侧内容显示为空需确认 server 读取语义 | Step 21 | 待复现 |

## 记录模板

### BUG-21-001: 标题

- 状态：
- 严重级别：
- 是否阻塞最小闭环：
- 影响范围：
- 复现步骤：
- 预期行为：
- 实际行为：
- 初步根因：
- 处理归属：
- 修复记录：
- 验证证据：

### BUG-21-001: 智能体说明文件右侧内容显示为空需确认 server 读取语义

- 状态：open
- 严重级别：P1
- 是否阻塞最小闭环：待确认。若默认 instructions 文件无法读取真实内容，会影响 agent 调试与说明文件编辑闭环。
- 影响范围：Agent instructions bundle UI、server `instructions-bundle` 文件读取接口、默认 instructions 初始化/materialization 行为。
- 复现步骤：
  1. 打开某个 agent 的 instructions bundle 页面。
  2. 左侧文件列表可见文件 metadata，例如 `path/size/editable/isEntryFile`。
  3. 点击文件后观察右侧编辑区内容。
  4. 对 `SOUL.md`、`TOOLS.md`、`MEMORY.md`、`AGENTS.md` 或新建文件分别确认读取结果。
- 预期行为：文件列表接口只返回 metadata；右侧内容必须由 `GET /instructions-bundle/file?path=xxx` 返回的 `content` 决定。已有默认文件如果 server 已初始化正文，应返回真实内容；新建文件允许返回空字符串。
- 实际行为：右侧显示空内容时，UI 只是展示 server 文件读取接口返回结果；若接口返回 `{ "content": "" }`，UI 不会自行填默认内容，也不会再从 `agentRuntimeConfig.promptTemplate` 兜底伪造内容。
- 初步根因：
  - `GET /instructions-bundle` 只返回 metadata，本身不包含正文，这是预期行为。
  - 对应 `GET /instructions-bundle/file?path=xxx` 可能实际返回空字符串。
  - 点击 `+` 新建文件时只输入文件名并创建 `{ "path": "...", "content": "" }`，新文件为空是预期行为。
  - 某些默认文件在 mock/test 或真实初始化中可能本来就是空内容。
  - 如果 `SOUL.md`、`TOOLS.md`、`MEMORY.md` 等默认文件也为空，需要确认 server 默认 instructions 写入/materialization 是否缺失。
- 处理归属：Step 21 先复现并确认 server 响应；若是默认 instructions 初始化缺口，按阻塞程度在 Step 21 修复或排入 Step 17/14 相关 instructions/materialization 后续。
- 修复记录：待处理。
- 验证证据：待补充具体请求、响应和涉及文件路径。
