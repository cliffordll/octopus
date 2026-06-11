# Step 26: Recovery / Observability / Compatibility

状态：已完成

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

## 已实现记录

- Claude/OpenCode/Codex local runtime 已接入 session resume 可用性判断；unknown/unavailable session 会写入可诊断日志并重试 fresh session。
- Codex local 已处理 cwd mismatch：当上一 session 的 workspace 与当前 cwd 不一致时跳过 resume，避免把工作接到错误 workspace。
- HTTP runtime environment test 已支持 live probe，并能区分 skip、missing URL、timeout、非 2xx 和 2xx 结果。
- Local CLI runtime environment test 已支持 live hello probe；失败退出码、启动失败和 timeout 都会落到稳定 check result。
- OpenCode environment test 已校验 configured model 是否在 available model list 中。
- Runtime hardening contract 覆盖 HTTP live probe failure、CLI hello failure、OpenCode model availability、Claude unknown session retry 和 Codex cwd mismatch skip。

## 剩余边界

- 自动化测试使用 fake subprocess、fake HTTP client 和临时 Python probe 证明控制面行为；release 前仍需要在安装了真实 Codex/Claude/OpenCode CLI 的机器上执行 smoke。
- Runtime compatibility matrix 只覆盖已纳入 runtime 的关键恢复和 probe 行为，不把未纳入 runtime 扩展为真实执行能力。
- 实时 stdout/stderr ingestion 已由 Step 22 提供，本步骤只验证 hardening 侧消费边界，不重复实现 ingestion。

## Release smoke checklist

发布或合并前，如果目标环境安装了真实 runtime CLI，应额外抽样验证：

- `POST /api/orgs/{orgId}/adapters/http/test-environment` 使用可达 HTTP endpoint，确认 live probe 成功和失败都可解释。
- `POST /api/orgs/{orgId}/adapters/codex_local/test-environment` 使用真实 `codex` command，确认 hello probe 成功或返回稳定失败 check。
- `POST /api/orgs/{orgId}/adapters/claude_local/test-environment` 使用真实 `claude` command，确认 cwd/auth/hello probe check 能解释当前机器状态。
- `POST /api/orgs/{orgId}/adapters/opencode_local/test-environment` 使用真实 `opencode` command 和配置模型，确认 available model 检查与 hello probe 结果一致。

## 边界

- 本步骤用于收口和加固 runtime/server 恢复行为，不新增产品模块。
- 不新增 runtime 类型；未纳入 runtime 仍保持可解释 unavailable/unsupported 结果。
- 不负责 Step 23 的数据库方言兼容、Step 25 的 activity query、Step 27 的成本查询、Step 28 的预算治理或 Step 29 的真实鉴权，只验证这些能力接入后的端到端可恢复与可观测。
- Step 20 已实现基础调试可见性；本步骤负责生产级恢复、兼容矩阵和完整 hardening 收口。

## 验收

- 主要失败场景具有恢复证据，且完整兼容测试集通过。
- Tests 覆盖 session resume 失败回退、cwd mismatch、HTTP live probe 超时/失败、CLI hello probe 失败和日志/指标可定位性。

## 本地验证记录

- `uv run pytest tests/contract/test_step26_runtime_hardening.py -q`：5 passed。覆盖 HTTP live probe timeout/503、CLI hello probe 失败、OpenCode model availability、Claude unknown session retry 和 Codex cwd mismatch skip。
