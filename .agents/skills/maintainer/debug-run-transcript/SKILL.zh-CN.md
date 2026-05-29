---
name: debug-run-transcript
description: |
  调试和分析 Octopus agent run transcript、run log 和执行 trace。用户提到以下情况时使用：
  - "debug run", "分析 run", "查看 run"
  - "为什么这个 agent 执行失败", "run 出错了"
  - "transcript 怎么看", "run 的日志"
  - run ID 或 run ID prefix
  - agent execution、tool calls、stdout/stderr 调试

  当用户想理解一次 run 中发生了什么时优先使用，即使只有部分 run ID 或只知道 agent/runtime。不要默认先查 raw SQL；先使用 Octopus 的 run-intelligence 路径，只在需要时 fallback。
---

# Debug Run Transcript

通过最佳可用来源重构执行故事，分析 Octopus agent runs。

## 目的

Runs 失败可能有多种原因：

- model/runtime 发出错误
- transcript parser 漏掉了有用结构
- event stream 不完整
- 已存 excerpts 太浅
- operator 只有 partial run ID 或有限上下文

本技能帮助诊断这些情况，避免卡在错误的数据来源上。

## 来源优先级

始终按以下顺序使用来源：

1. **Run-intelligence loader/API**
   - 最佳默认路径。
   - 读取 run metadata、run events 和底层 run log。
   - 用 runtime-specific parsers 重构 transcript entries。
2. **Filesystem run log fallback**
   - 本地 API 不可用但磁盘上有 run logs 时使用。
   - 适合重构 transcript/tool-call。
3. **Direct database queries**
   - 只用于定向补充检查，或前两种路径不可用时。
   - DB rows 单独不是完整 transcript story。

## 重要经验 / 已知陷阱

- 不要假设 `~/.octopus/instances/dev/postgres-uri` 一定存在；在本 repo 中它不是可靠通用入口。
- 不要从 `heartbeat_run_events` 开始并假设它是完整 transcript。它们只是 supplemental run events，不是完整 parsed execution trace。
- 不要对 `uuid` columns 写 `WHERE id LIKE 'prefix%'`。先 cast：`id::text ILIKE 'prefix%'`。
- 不要假设从 repo root 执行 `pnpm exec tsx` 可用。优先使用 repo-local launcher：

```bash
node cli/node_modules/tsx/dist/cli.mjs ...
```

- 不要把 `stdout_excerpt` / `stderr_excerpt` 当作完整 log。它们只是快速诊断。
- 如果 `/api/run-intelligence/runs/<id>/log` 返回 `404`，不要假设 run 没有 raw log。先检查是否查询了错误 Octopus instance，例如 dev server/API，但 run log 位于 `~/.octopus/instances/e2e/data/run-logs/...`。

## 工作流

### 1. 识别 run

如果用户给：

- 完整 run ID：直接使用
- 短 prefix，如 `7d28669d`：按 prefix 处理
- 只有 agent 或时间范围：先帮助定位可能 runs，再深度分析

如果完全没有识别信息，至少询问：

- run ID 或 prefix
- agent name
- 近似时间窗口

### 2. 首选路径：run-intelligence CLI helpers

在本 repo 本地工作时先使用这些命令。

**高层诊断**

```bash
node cli/node_modules/tsx/dist/cli.mjs packages/run-intelligence-core/src/cli/analyze.ts <run-id-or-prefix> [auto|quick|error|perf|full]
```

**列出 model turns / steps**

```bash
node cli/node_modules/tsx/dist/cli.mjs packages/run-intelligence-core/src/cli/trace-outline.ts <run-id-or-prefix>
```

**检查特定 step**

```bash
node cli/node_modules/tsx/dist/cli.mjs packages/run-intelligence-core/src/cli/trace-entry.ts <run-id-or-prefix> <stepIndex|turn:N>
```

这些命令已知道如何：

- 按 run prefix 跨 org 搜索
- 通过 API 获取 run metadata、events 和 logs
- API 不可用时 fallback 到 filesystem run logs
- 把 runtime-specific stdout 解析为 transcript entries

### 3. 需要 raw data 时的 API 路径

如果本地 Octopus server 已启动，直接使用 run-intelligence API。

有用 endpoints：

```bash
curl http://127.0.0.1:3100/api/orgs
curl "http://127.0.0.1:3100/api/run-intelligence/orgs/<org-id>/runs?limit=50&runIdPrefix=<prefix>"
curl "http://127.0.0.1:3100/api/run-intelligence/runs/<run-id>"
curl "http://127.0.0.1:3100/api/run-intelligence/runs/<run-id>/events"
curl "http://127.0.0.1:3100/api/run-intelligence/runs/<run-id>/log"
```

如果设置了 `OCTOPUS_API_URL`，使用该 base URL，而不是 `http://127.0.0.1:3100/api`。

### 4. Filesystem fallback

如果 API 路径不可用，run-intelligence CLI loader 仍可自动 fallback 到 filesystem logs。

默认本地 run-log root：

```text
~/.octopus/instances/dev/data/run-logs
```

如果 run 来自不同本地 instance，也检查 sibling stores，例如：

```text
~/.octopus/instances/e2e/data/run-logs
```

当以下情况出现时这很重要：

- run detail 和 events 通过某 server 正常解析
- 但 `/run-intelligence/runs/<id>/log` 返回 `404`
- raw log 实际存在于另一个 instance root

发明自定义 parser 前，先使用同样 CLI 命令。

### 5. Direct DB fallback

只在需要定向补充检查时使用 DB queries。

**按 prefix 查 run metadata**

```sql
SELECT
  r.id,
  r.status,
  r.exit_code,
  r.signal,
  r.error,
  r.error_code,
  r.started_at,
  r.finished_at,
  r.session_id_before,
  r.session_id_after,
  r.stdout_excerpt,
  r.stderr_excerpt,
  r.usage_json,
  r.result_json,
  a.name AS agent_name,
  a.agent_runtime_type
FROM heartbeat_runs r
JOIN agents a ON r.agent_id = a.id
WHERE r.id::text ILIKE '7d28669d%'
ORDER BY r.created_at DESC;
```

**按 prefix 查 run events**

```sql
SELECT
  seq,
  event_type,
  stream,
  level,
  message,
  payload,
  created_at
FROM heartbeat_run_events
WHERE run_id::text ILIKE '7d28669d%'
ORDER BY seq, id;
```

**可能的错误事件**

```sql
SELECT
  seq,
  event_type,
  stream,
  level,
  message,
  payload
FROM heartbeat_run_events
WHERE run_id::text ILIKE '7d28669d%'
  AND (
    stream = 'stderr'
    OR level = 'error'
    OR event_type ILIKE '%error%'
    OR COALESCE(payload->>'isError', payload->>'is_error', 'false') = 'true'
  )
ORDER BY seq, id;
```

## 解释数据

分析 run 时按顺序关注：

1. **Run summary**
   - status
   - duration
   - runtime type / agent name
   - exit code / signal / error / error code
   - `usage_json` 中 token 和 cost fields

2. **Transcript story**
   - model turns
   - tool calls 和 tool results
   - stderr / system events
   - run 第一次明显出错的位置

3. **Supporting evidence**
   - `adapter.invoke`、`heartbeat.run.status`、`heartbeat.run.log` 等 run events
   - `stdout_excerpt` / `stderr_excerpt`
   - session IDs before/after

## 查找重点

### Tool call 问题

- tool call 没有匹配 tool result
- tool result 标记 error
- tool payload 意外过大或被截断

### Output 问题

- stderr 比 `error` 更清楚解释失败
- raw log 存在但没有 parsed `result` entry
- transcript parser 漏掉 raw log 中可见的结构

### Metadata 问题

- `status` 与 `exit_code` 或 `error_code` 不一致
- `usage_json` 缺少明显 token/cost fields
- `result_json` 存在但太浅，无法解释失败

### Session / continuity 问题

- `session_id_before` / `session_id_after` 异常
- retries 或 continuation context 缺失
- 重复 init/start signals 但没有 clean result

## 输出格式

按以下顺序展示 findings：

### 1. Run Summary

```text
Run: 7d28669d-...
Agent: CEO (claude_local)
Status: failed
Duration: 3m 38s
Cost: $0.7919 | 47.8k in | 8.3k out | 2.1k cached
Exit Code: 1
Error: unknown session
```

### 2. What Happened

- 简短叙述执行流
- 第一个明确失败点
- 根因来自 transcript、raw log 还是 run event evidence

### 3. Key Evidence

- Tool calls
- Error snippets
- 相关 system / adapter.invoke events
- Session / retry clues

### 4. Raw Log

仅当用户要求时提供。保存到 repo 外，例如：

```bash
printf "%s" "$LOG_CONTENT" > /tmp/run-<run-id>.log
```

## 备注

- `heartbeat_run_events` 中非 log events 可能 `stream = null`。
- `payload` 可能根据来源使用 `isError` 或 `is_error`。
- 成本/tokens 检查 `inputTokens`、`outputTokens`、`cachedInputTokens`、`cachedTokens`、`costUsd` 和 `totalCostUsd`。
- 最佳默认通常是：先跑 `analyze.ts`，再跑 `trace-outline.ts`，诊断仍不清楚时再检查 raw events/log。
