# Step 20: Basic Observability / Debug Visibility

状态：已完成

## 目标

在 Step 19 Storage/Attachment 提供稳定对象引用后，补齐开发和联调需要的基础可见性，使 chat、run、runtime、workspace 的问题能被定位。

本步骤只做调试可见性，不做完整恢复、生产级指标或全链路兼容收口。

## 上游证据

本步骤按上游已有 route/service 实施，不新增自定义 `/debug` 聚合 API。

- `D:\coding\upstream-reference\server\src\routes\agents.management-routes.ts`
- `D:\coding\upstream-reference\server\src\routes\run-intelligence.ts`
- `D:\coding\upstream-reference\server\src\services\run-intelligence.ts`
- `D:\coding\upstream-reference\server\src\services\run-log-store.ts`
- `D:\coding\upstream-reference\server\src\services\workspace-operations.ts`
- `D:\coding\upstream-reference\server\src\services\workspace-operation-log-store.ts`
- `D:\coding\upstream-reference\packages\run-intelligence-core\src\types.ts`
- `D:\coding\upstream-reference\packages\shared\src\types\workspace-operation.ts`

## 任务

### 20A: Heartbeat run log

作用：补齐上游 `GET /api/heartbeat-runs/{runId}/log`，支持 `offset`、`limitBytes` 读取 run log 内容。

范围：

- 新增 shared path：`HEARTBEAT_RUN_LOG_PATH`。
- 新增本地 `local_file` run log reader，按 `logStore/logRef` 读取内容，返回 `content/endOffset/eof/nextOffset`。
- route 必须先读取 run 并校验 organization access。

### 20B: Workspace operation visibility

作用：补齐上游 `GET /api/heartbeat-runs/{runId}/workspace-operations` 与 `GET /api/workspace-operations/{operationId}/log`。

范围：

- 新增 shared path：`HEARTBEAT_RUN_WORKSPACE_OPERATIONS_PATH`、`WORKSPACE_OPERATION_LOG_PATH`。
- workspace operation 列表按 run scope 返回，log 按 operation org scope 校验。
- operation log 与 run log 使用相同 offset/limit response shape。

### 20C: Run intelligence read APIs

作用：补齐上游 `run-intelligence` 只读查询入口，便于开发与联调从 run 维度定位执行问题。

范围：

- 新增 route：
  - `GET /api/run-intelligence/orgs/{orgId}/runs`
  - `GET /api/run-intelligence/runs/{runId}`
  - `GET /api/run-intelligence/runs/{runId}/events`
  - `GET /api/run-intelligence/runs/{runId}/log`
- 列表支持上游筛选参数：`updatedAfter`、`runIdPrefix`、`agentId`、`status`、`runtime`、`issueId`、`createdBefore`、`limit`。
- detail 返回上游式 observed run shape：`run`、`agentName`、`orgName`、`issue`、`bundle`、`langfuse`。

### 20D: Debug path documentation

作用：说明 chat、run、workspace、activity 的定位关系，避免后续重复发明观测入口。

范围：

- 在本文件记录实际调试路径。
- 明确 production hardening、diagnosis、Langfuse scores、cost/activity query 不属于本步骤。

## 边界

- 不实现真实 Auth / Actor / Access，归 Step 23。
- 不实现完整 Recovery / Compatibility 矩阵，归 Step 24。
- 不实现 budget/cost 治理，归 Step 21/22。
- 不新增外部观测系统依赖；本阶段以数据库记录和服务端响应可见性为主。
- 不实现上游 `diagnoseObservedRun`、Langfuse scores 或完整 `run-intelligence-core` 分析，只提供上游已有只读 API 的基础 shape。

## 验收

- Tests 覆盖 run log、workspace operation list/log、run-intelligence list/detail/events/log。
- Tests 覆盖可见性接口的 organization scope。
- 文档说明 chat、run、workspace、activity 的调试路径。

## 调试路径

- Chat 对话失败：先看 chat message/stream error，再通过 message 或 issue 关联找到 run。
- Run 执行失败：查 `GET /api/heartbeat-runs/{runId}` 看 `error/errorCode/stdoutExcerpt/stderrExcerpt/contextSnapshot`。
- Run 事件流：查 `GET /api/heartbeat-runs/{runId}/events` 或 `GET /api/run-intelligence/runs/{runId}/events`。
- Run 原始日志：查 `GET /api/heartbeat-runs/{runId}/log` 或 `GET /api/run-intelligence/runs/{runId}/log`。
- Workspace 操作：查 `GET /api/heartbeat-runs/{runId}/workspace-operations`，再用 `GET /api/workspace-operations/{operationId}/log` 查看单步日志。
- Issue 维度产物：issue detail 中的 `workProducts` 仍是业务产物入口；本步骤只补执行可见性入口。
