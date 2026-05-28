# Step 23: Recovery / Observability / Compatibility

状态：待开发

## 任务

- 实现上游已有的失败恢复、重试或幂等保护行为。
- 补充诊断已实现服务端工作流所需的日志与指标边界。
- 对已纳入能力运行端到端 contract/workflow 兼容回归。
- 收口 Step 14 后置的 runtime hardening：Claude/OpenCode session resume、cwd mismatch 处理、unknown session 恢复策略和运行期兼容告警。
- 将 Step 14 的基础 environment test 扩展为 live probe：HTTP endpoint live probe、CLI hello probe、OpenCode configured/available model probe 的稳定化检查。
- 为 runtime adapter 增加兼容回归矩阵，覆盖 `process`、`http`、`codex_local`、`claude_local`、`opencode_local` 的成功、失败、取消、恢复和观测事件。

## 边界

- 本步骤用于收口和加固兼容 server 行为，不新增产品模块。
- 不新增 runtime 类型；未纳入 runtime 仍保持可解释 unavailable/unsupported 结果。
- 不负责 Step 20 的成本治理或 Step 22 的真实鉴权，只验证这些能力接入后的端到端可恢复与可观测。
- Step 18 已提前实现基础调试可见性；本步骤负责生产级恢复、兼容矩阵和完整 hardening 收口。

## 验收

- 主要失败场景具有恢复证据，且完整兼容测试集通过。
- Tests 覆盖 session resume 失败回退、cwd mismatch、HTTP live probe 超时/失败、CLI hello probe 失败和日志/指标可定位性。
