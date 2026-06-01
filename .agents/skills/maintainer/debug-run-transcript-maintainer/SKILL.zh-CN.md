---
name: debug-run-transcript-maintainer
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

该文件是 `debug-run-transcript` 的 maintainer 命名副本，中文逻辑与其一致。

## 核心目的

通过 run-intelligence、filesystem run logs 和必要时的数据库补充检查，重构 Octopus agent run 的执行故事，找出第一次明确失败点和证据来源。

## 来源优先级

1. **Run-intelligence loader/API**：默认首选，读取 metadata、events 和底层 run log，并用 runtime-specific parser 重构 transcript。
2. **Filesystem run log fallback**：API 不可用但磁盘有 run logs 时使用。
3. **Direct database queries**：仅用于定向补充检查；DB rows 不是完整 transcript。

## 已知陷阱

- 不要假设 `~/.octopus/instances/dev/postgres-uri` 是通用入口。
- 不要把 `heartbeat_run_events` 当作完整 transcript。
- UUID prefix 查询要写 `id::text ILIKE 'prefix%'`。
- 本 repo 中优先使用：

```bash
node cli/node_modules/tsx/dist/cli.mjs ...
```

- `stdout_excerpt` / `stderr_excerpt` 只是快速诊断，不是完整 log。
- `/api/run-intelligence/runs/<id>/log` 返回 `404` 时，先检查是否查错 instance；raw log 可能在 sibling instance root 下。

## 工作流

### 1. 识别 run

- 完整 run ID：直接使用。
- 短 prefix：按 prefix 搜索。
- 只有 agent 或时间范围：先定位候选 runs。
- 没有识别信息：询问 run ID/prefix、agent name 或近似时间窗口。

### 2. 首选 CLI helpers

```bash
node cli/node_modules/tsx/dist/cli.mjs packages/run-intelligence-core/src/cli/analyze.ts <run-id-or-prefix> [auto|quick|error|perf|full]
node cli/node_modules/tsx/dist/cli.mjs packages/run-intelligence-core/src/cli/trace-outline.ts <run-id-or-prefix>
node cli/node_modules/tsx/dist/cli.mjs packages/run-intelligence-core/src/cli/trace-entry.ts <run-id-or-prefix> <stepIndex|turn:N>
```

这些 helper 支持跨 org prefix 搜索、API metadata/events/log 获取、filesystem fallback 和 runtime-specific stdout 解析。

### 3. API 路径

```bash
curl http://127.0.0.1:3100/api/orgs
curl "http://127.0.0.1:3100/api/run-intelligence/orgs/<org-id>/runs?limit=50&runIdPrefix=<prefix>"
curl "http://127.0.0.1:3100/api/run-intelligence/runs/<run-id>"
curl "http://127.0.0.1:3100/api/run-intelligence/runs/<run-id>/events"
curl "http://127.0.0.1:3100/api/run-intelligence/runs/<run-id>/log"
```

如果设置了 `OCTOPUS_API_URL`，使用该 base URL。

### 4. Filesystem fallback

默认 run-log root：

```text
~/.octopus/instances/dev/data/run-logs
```

也检查 sibling stores，例如：

```text
~/.octopus/instances/e2e/data/run-logs
```

### 5. DB fallback

只做补充检查。常用查询包括 run metadata、run events 和 likely error events，查询 UUID 时必须 cast 为 text。

## 解释顺序

1. **Run summary**：status、duration、runtime/agent、exit code/signal/error/error code、usage_json 中 token/cost。
2. **Transcript story**：model turns、tool calls/results、stderr/system events、第一次明显出错点。
3. **Supporting evidence**：adapter.invoke、heartbeat events、stdout/stderr excerpt、session IDs。

## 查找重点

- tool call 无 matching result、tool result error、payload 过大或截断。
- stderr 比 `error` 更清楚，raw log 有结果但 parser 没解析，或 parser 漏结构。
- metadata 状态与 exit/error 不一致，usage/result 太浅。
- session before/after 异常、continuation 缺失、重复 init/start 无 clean result。

## 输出格式

```text
Run: 7d28669d-...
Agent: CEO (claude_local)
Status: failed
Duration: 3m 38s
Cost: $0.7919 | 47.8k in | 8.3k out | 2.1k cached
Exit Code: 1
Error: unknown session
```

然后输出：

- What Happened
- Key Evidence
- Raw Log（仅用户要求时，保存到 `/tmp/run-<run-id>.log`）

## 备注

`heartbeat_run_events.stream` 可为 null；payload 可用 `isError` 或 `is_error`；成本字段检查 `inputTokens`、`outputTokens`、`cachedInputTokens`、`cachedTokens`、`costUsd`、`totalCostUsd`。默认路径是 `analyze.ts` -> `trace-outline.ts` -> 必要时 raw events/log。
