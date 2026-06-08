# Step 26: Recovery / Observability / Compatibility

状态：待开发

## 已提前完成

- Step 20/21 已实现基础 run observability：run log、run stream、workspace operation log、run-intelligence list/detail/events/log、issue -> heartbeat runs 查询。
- `codex_local` 已提前完成 managed `CODEX_HOME`、credential home sync、managed Git config、unknown session retry、benign stderr 过滤、tool session error 识别、provider/biller usage 字段归一化和 loaded skills 元数据。
- `opencode_local` 已提前实现 chunk 读取 stdout，避免超长 JSONL 单行触发 asyncio readline limit；但 stdout/stderr 落库仍需 Step 22 修正为实时。
- 本地 runtime 基础环境检查、command resolvable、cwd/auth 线索和 provider model 注入已有部分 contract tests。

这些提前完成项降低了 Step 26 的范围；Step 26 仍负责生产级恢复、live probe 和完整 runtime 兼容矩阵收口。

## 任务

- 实现上游已有的失败恢复、重试或幂等保护行为。
- 补充诊断已实现服务端工作流所需的日志与指标边界。
- 对已纳入能力运行端到端 contract/workflow 兼容回归。
- 收口 Step 14 后置的 runtime hardening：Claude/OpenCode session resume、cwd mismatch 处理、unknown session 恢复策略和运行期兼容告警。
- 将 Step 14 的基础 environment test 扩展为 live probe：HTTP endpoint live probe、CLI hello probe、OpenCode configured/available model probe 的稳定化检查。
- 为 runtime adapter 增加兼容回归矩阵，覆盖 `process`、`http`、`codex_local`、`claude_local`、`opencode_local` 的成功、失败、取消、恢复和观测事件。

## 剩余待开发

- Claude/OpenCode session resume 与 cwd mismatch 处理仍未形成完整兼容策略。
- HTTP endpoint live probe、CLI hello probe、OpenCode configured/available model live probe 仍未完成。
- runtime compatibility matrix 还没有覆盖所有 runtime 的成功、失败、取消、恢复、观测事件和 provider/model 组合。
- Step 22 修复实时 stdout/stderr ingestion 后，本步骤需要把该能力纳入完整回归矩阵，而不是重复实现。

## 边界

- 本步骤用于收口和加固 runtime/server 恢复行为，不新增产品模块。
- 不新增 runtime 类型；未纳入 runtime 仍保持可解释 unavailable/unsupported 结果。
- 不负责 Step 23 的数据库方言兼容、Step 25 的 activity query、Step 27 的成本查询、Step 28 的预算治理或 Step 29 的真实鉴权，只验证这些能力接入后的端到端可恢复与可观测。
- Step 20 已实现基础调试可见性；本步骤负责生产级恢复、兼容矩阵和完整 hardening 收口。

## 验收

- 主要失败场景具有恢复证据，且完整兼容测试集通过。
- Tests 覆盖 session resume 失败回退、cwd mismatch、HTTP live probe 超时/失败、CLI hello probe 失败和日志/指标可定位性。
