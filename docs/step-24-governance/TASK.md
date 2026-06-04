# Step 24: Budget / Governance

状态：待开发

## 依赖边界

Step 23 已实现 cost event、cost summary 和 activity query。本步骤只补齐预算治理、quota window 与 skills analytics 等后置治理能力。

## 任务

- 实现上游已有的 budget 检查与受限行为。
- 将 Step 14 的 skills analytics 兼容空响应升级为真实归集：基于 run/event/activity 中的 loaded/requested/used evidence 统计 agent skill 使用情况。
- 归集 Step 14 adapter quota window probe 输出，并与 budget/cost 查询和限制行为建立可解释联动。
- 将 Step 14 的 quota window 兼容入口升级为真实 provider quota 读取：失败继续可解释，不阻断普通 run。
- 明确 quota window、budget、cost 三者关系：quota 是 provider 使用窗口证据，budget 是组织/项目治理限制，cost 是 run/activity 归集结果。

## 边界

- 仅增加存在上游证据的预算、quota 和 analytics 治理语义。
- 不修改 runtime adapter 的执行协议；adapter 只提供 probe/usage 原始证据，本步骤负责治理归集和限制解释。
- 不负责 runtime skills 的 materialization、mount 或 organization skill 管理；这些分别归 Step 14 和独立 skills 管理步骤。

## 验收

- Tests 覆盖预算限制和必须产生的 activity entries。
- Tests 覆盖 provider quota 原始读取失败、成功归集、窗口过期和 budget 联动行为。
- Tests 覆盖 skills analytics 从空兼容响应升级为真实统计后，loaded/requested/used evidence 的计数、时间窗口和 agent/org scope 行为。

## 上游证据

开发前必须对照以下上游文件，不能凭本地偏好重定义治理模型：

- `D:\coding\rudder\packages\db\src\schema\budget_policies.ts`
- `D:\coding\rudder\packages\db\src\schema\budget_incidents.ts`
- `D:\coding\rudder\server\src\routes\costs.ts`
- `D:\coding\rudder\server\src\services\budgets.ts`
- `D:\coding\rudder\server\src\services\quota-windows.ts`
- `D:\coding\rudder\packages\shared\src\types\budget.ts`
- `D:\coding\rudder\packages\shared\src\validators\budget.ts`

## 开发计划

### 24A: Budget contract 与迁移基线

作用：把预算治理的上游数据模型落到 Python 版本，给 budget enforcement 提供稳定边界。

修改范围：

- `packages/shared/constants/`：补齐 `BudgetScopeType`、`BudgetMetric`、`BudgetWindowKind`、`BudgetThresholdType`、`BudgetIncidentStatus`、`BudgetIncidentResolutionAction`。
- `packages/shared/types/`：新增或扩展 budget response 类型。
- `packages/shared/validators/`：新增 budget update、budget policy upsert、incident resolve validator。
- `packages/database/schema/`：新增 `BudgetPolicy`、`BudgetIncident`。
- `packages/database/migrations/versions/20260528_000009_budget_governance.py`：新增上游对齐表、索引和外键。
- `tests/contract/test_step24_budget_contract.py`：覆盖 migration、validator、enum 和 schema 默认值。

验收：

- 空库 migration 可执行。
- `budget_policies`、`budget_incidents` 字段、索引和默认值与上游已纳入范围一致。
- validator 拒绝负数金额、非法 budget scope/window/incident action。

### 24B: Budget policy、incident 与 hard-stop enforcement

作用：实现上游预算策略、软阈值、硬停止、incident 和审批副作用，真正让 budget 影响新 work 的启动。

修改范围：

- `packages/database/queries/budgets.py`：新增 policy upsert/list、observed amount、incident create/list/resolve。
- `server/services/budgets.py`：实现 policy summary、overview、cost event 后评估、scope pause/resume、incident resolve。
- `server/services/heartbeat.py`：在创建 run/wakeup 前调用 budget invocation block；实现 `cancel_budget_scope_work` 取消受影响 queued/running runs。
- `server/routes/costs.py`：新增：
  - `GET /api/orgs/{orgId}/budgets/overview`
  - `POST /api/orgs/{orgId}/budgets/policies`
  - `POST /api/orgs/{orgId}/budget-incidents/{incidentId}/resolve`
  - `PATCH /api/orgs/{orgId}/budgets`
  - `PATCH /api/agents/{agentId}/budgets`
- `tests/contract/test_step24_budget_routes.py`：覆盖 policy upsert、overview、resolve、org/agent budget patch。
- `tests/workflows/test_step24_budget_workflow.py`：覆盖 soft incident、hard incident、approval、pause、resume、cancel queued/running runs。

验收：

- scope 支持 `organization`、`agent`、`project`。
- metric 只实现上游当前 `billed_cents`。
- window 支持 `calendar_month_utc` 和 `lifetime`。
- hard stop 会暂停 organization/agent/project 并阻止后续 run 创建或启动。
- `raise_budget_and_resume` 必须要求新 amount 大于当前 observed spend。

### 24C: Quota windows 真实归集入口

作用：把 Step 14 的 adapter quota probe 从单 adapter 兼容响应升级为 organization 级 provider quota 聚合，但 provider 失败不能阻断普通 run。

修改范围：

- `packages/runtimes/registry.py`：补齐列出可提供 quota windows 的 adapter。
- `server/services/quota_windows.py`：聚合 `get_runtime_quota_windows`，设置超时并把失败映射为 `{ok: false, error, windows: []}`。
- `server/routes/costs.py`：新增 `GET /api/orgs/{orgId}/costs/quota-windows`。
- `tests/contract/test_step24_quota_windows.py`：覆盖 org access、unknown org、provider failure、timeout、success aggregation。

验收：

- 只有已注册且声明 quota 能力的 adapter 被调用。
- 单个 provider 失败或超时返回错误项，不影响其他 provider。
- 不把 quota windows 写成 budget，不把 quota 当作 cost；三者关系仅在 response 和文档中解释清楚。

### 24D: Skills analytics 真实归集

作用：替换 Step 14 的空兼容响应，用 run/event/activity 证据计算 agent skill loaded/requested/used 统计。

修改范围：

- `packages/database/queries/agent_skills.py`：新增 skill usage evidence 查询。
- `server/services/agent_skills.py` 或独立 `server/services/skills_analytics.py`：实现 organization/agent/time window 统计。
- 现有 runtime skills analytics route：由空响应切换为真实统计。
- `tests/contract/test_step24_skills_analytics.py`：覆盖 response shape、时间窗口、org/agent scope。
- `tests/workflows/test_step24_skills_analytics_workflow.py`：覆盖 loaded/requested/used evidence 计数。

验收：

- loaded、requested、used 必须来自已持久化 evidence，不伪造统计。
- 没有 evidence 时返回零值统计，而不是 404 或空结构漂移。
- 不做 runtime skills materialization；该能力仍归 Step 14 runtime 边界。

## 执行顺序

1. 先执行 24A，提交 budget schema/contract/migration。
2. 执行 24B，提交 budget policy、incident 和 hard-stop。
3. 执行 24C，提交 quota windows 聚合。
4. 执行 24D，提交 skills analytics 真实归集。

每一段完成后先停下说明“做了什么、作用是什么、验证结果是什么”，再按用户确认进入下一段。

## 验证命令

每个子任务至少运行：

```powershell
uv run ruff format --check .
uv run ruff check .
uv run pyright .
```

对应子任务还需运行新增或受影响测试，例如：

```powershell
uv run pytest tests/contract/test_step24_budget_contract.py -q
uv run pytest tests/contract/test_step24_budget_routes.py -q
uv run pytest tests/workflows/test_step24_budget_workflow.py -q
uv run pytest tests/contract/test_step24_quota_windows.py -q
```
