# Step 15: Workspace 与执行产物

状态：15A-15H 已完成并通过基线验收

## 上游依据

- 参考工程：本地上游参考仓库
- Workspace route：`server/src/routes/execution-workspaces.ts`
- Workspace services：`server/src/services/execution-workspaces.ts`、`server/src/services/execution-workspace-policy.ts`、`server/src/services/managed-workspace-preflight.ts`
- Workspace runtime services：`server/src/services/workspace-runtime.ts`、`server/src/services/workspace-runtime.services.ts`、`server/src/services/workspace-runtime.lifecycle.ts`、`server/src/services/workspace-runtime.helpers.ts`
- Workspace operations：`server/src/services/workspace-operations.ts`、`server/src/services/workspace-operation-log-store.ts`
- Work products：`server/src/services/work-products.ts`
- Project workspace：`server/src/services/organization-workspace.ts`、`server/src/services/organization-workspace-browser.ts`
- Shared contract：`packages/shared/src/validators/execution-workspace.ts`、`packages/shared/src/types/workspace-runtime.ts`、`packages/shared/src/types/workspace-operation.ts`、`packages/shared/src/types/work-product.ts`
- DB schema：`packages/db/src/schema/execution_workspaces.ts`、`packages/db/src/schema/project_workspaces.ts`、`packages/db/src/schema/workspace_runtime_services.ts`、`packages/db/src/schema/workspace_operations.ts`
- 相关测试：`server/src/__tests__/workspace-runtime.test.ts`、`server/src/__tests__/managed-workspace-preflight.test.ts`、`server/src/__tests__/execution-workspace-policy.test.ts`、`server/src/__tests__/work-products.test.ts`

## 依赖边界

Step 10 已实现 Project 管理，并保留 project 的 execution workspace 策略与 workspace 聚合字段边界。本步骤补齐这些字段背后的 workspace 行为，不重新定义 Project 领域模型。

Step 11 已建立 agent 执行、对话触发和最小 runtime context；Step 13 已补齐 run 调度、取消和恢复；Step 14 已补齐 runtime adapter、环境检查、模型发现、skills 与 instructions 能力。本步骤必须复用这些既有执行链路，只在运行前后加入 workspace 解析、注入、记录和清理。

Step 19 负责 cost/activity 查询；Step 20 负责 budget 治理联动；Step 21 负责 attachment/object storage；Step 22 负责真实 auth、secret/env binding。Step 15 可以保留这些能力需要的引用结构，但不得提前实现其治理或存储后端。

## Workspace 在项目中的作用

Workspace 是智能体执行任务时的受控工作现场，不是一个普通 `cwd` 字符串。它负责把 `project`、`issue`、`agent`、`run`、`runtime adapter` 和执行产物关联起来，使服务端能够确定“在哪执行、执行了什么、产物在哪里、失败后如何恢复”。

逻辑层级如下：

```text
Organization
  Project
    Project Workspace
      Issue
        Execution Workspace
          Heartbeat Run
            Workspace Operation
            Workspace Runtime Service
            Work Product reference
```

这些层级主要是业务关系和持久化关系，不代表每一层都必须有独立物理目录。物理目录只是本地实现策略，需要由 service 层统一生成和管理，不能让 route 或 adapter 自行拼接路径。

一个本地 managed workspace 可以采用类似结构：

```text
<octopus-root>/
  .octopus/
    organizations/
      <organization_id>/
        workspaces/
          agents/
            <agent_workspace_key>/
          skills/
          plans/
          executions/
            <execution_workspace_id>/
              worktree/
              logs/
              tmp/
          artifacts/
            issue_<issue_id>/
              run_<run_id>/
                <work_product_id>/
```

该结构只作为 Step 15 的最小本地目录策略参考。上游兼容的关键不是目录名字本身，而是服务端持久化关系、runtime context/env、operation/service 状态和失败清理语义保持一致。

Runtime adapter 在执行时应通过统一 context/env 获取 workspace 信息，例如主 workspace、workspace 列表、worktree path、repo/ref/branch、organization workspace root、artifacts dir 和 runtime services JSON，而不是直接理解数据库表关系。

上游 Rudder 当前约定：新项目不会自动创建独立 workspace root。若 project-linked run 没有可用 project workspace，或 legacy project workspace 只有远程 metadata 但没有本地 `cwd`，运行时 fallback 到组织共享 workspace root，并带可解释 warning。持久交付文件、报告、截图、CSV 和 handoff 文档应优先写入 `OCTOPUS_ORG_ARTIFACTS_DIR`，不要写到临时目录或自造顶层 `projects/` 目录。

Project workspace 支持后，它就是项目对应的本地源码与下载物锚点。项目相关的仓库 checkout、导入或下载的源码包、依赖快照、项目内临时文件、代码修改和 patch 应放在 project workspace / execution workspace 的 `cwd` 下。Runtime 子进程的相对路径读写默认也发生在这个 `cwd` 中。

如果希望任务直接在项目本地目录执行，例如 `D:\coding\test`，项目的执行工作区策略应选择 `shared_workspace`。`isolated_workspace` 和 `operator_branch` 会基于项目工作区创建或解析每次任务独立的 execution workspace，实际 cwd 不会直接等于项目主工作区目录。

Project workspace 不应承担正式交付物归档职责。报告、截图、CSV、mockup、运行日志摘要、handoff 文档等 durable output 应优先写入 `OCTOPUS_ORG_ARTIFACTS_DIR`，再由 server 扫描并登记为 issue work products 或 documents。这样可以避免源码目录混入交付归档，也避免只靠文件系统目录推断 issue/run 关系。

## Preflight 的含义

Preflight 是 run 正式调用 runtime adapter 之前的 workspace 预检与准备阶段。它不是独立执行模型，而是 Step 13 run 生命周期中的执行前检查点。

Preflight 需要确认：

- 当前 run 是否携带可解析的 `issueId` 或等价业务上下文。
- issue 是否能解析到同一 organization 下的 project。
- project 是否有可用的 project workspace 或 execution workspace 策略。
- 是否能创建或复用 execution workspace。
- 组织共享 workspace、agents、skills、plans、artifacts 目录以及必要的 logs/tmp 目录是否可准备。
- 注入给 adapter 的 workspace context/env 是否完整。

正常执行顺序如下：

```text
queued run
  -> claim as running
  -> workspace preflight
  -> runtime adapter execute
  -> persist result
```

如果 preflight 失败，adapter 不应继续执行；run/event/operation 需要留下可解释失败信息。这样可以避免智能体在错误目录、空目录或未明确归属的 workspace 中执行任务。

## 15A：Workspace Contract 与 Schema

- 对齐上游 `project_workspaces`、`execution_workspaces`、`workspace_runtime_services`、`workspace_operations` 和 work product 引用相关 schema。
- 补齐 shared path、types、validators、枚举和响应模型，避免 route/service 中散落自造字段。
- 将 issue、project、run 需要关联 workspace 的字段纳入数据库查询层；已有字段不得改变语义。
- Alembic migration 必须支持空库升级，并与 Step 4 migration 流程保持一致。

实施记录：

- `packages/database/schema/workspaces.py` 定义 `project_workspaces`、`execution_workspaces`、`workspace_runtime_services`、`workspace_operations`、`issue_work_products`。
- `packages/database/migrations/versions/20260528_000007_workspaces.py` 支持空库升级到 workspace schema。
- `packages/shared/constants/workspace.py`、`packages/shared/types/workspace.py`、`packages/shared/validators/workspace.py` 提供 workspace 枚举、类型和 update payload 校验。

## 15B：Project Workspace 管理与聚合

- 实现 project workspace 的读取、聚合和 primary workspace 输出。
- Project detail/list 响应需要返回上游兼容的 workspace 聚合字段，例如 `primaryWorkspace`、`workspaces` 或已在 contract 中确认的等价结构。
- 不凭空增加上游没有的管理入口；如果上游只通过既有流程创建或维护 workspace，Python 侧也应保持相同入口。
- 保证 project workspace 受 organization scope 约束，不能跨 organization 读取或关联。

实施记录：

- `server/services/projects.py` 支持 project workspace 创建、primary 切换和 project detail/list 聚合输出。
- Project 响应已补齐 `workspaces`、`primaryWorkspace`、`codebase` 的最小上游兼容结构。

## 15C：Execution Workspace 策略解析

- 实现 execution workspace policy service，按 project、issue、agent/runtime config 和请求上下文解析应该创建、复用或绑定的 execution workspace。
- 支持 issue 上的 workspace preference/settings 与 project 默认策略，不把执行目录当成普通 runtime config 字符串处理。
- 保证每次 run 获得明确 workspace 决策：使用已有 workspace、创建 managed workspace、或返回可解释的 preflight 失败。
- 策略解析必须幂等，重复触发同一 run 或恢复 run 不应创建不一致的 workspace 记录。

实施记录：

- `server/services/workspaces.py` 实现 `resolve_for_issue()`，按 issue/project policy 解析 `shared_workspace`、`isolated_workspace`、`operator_branch`、`agent_default`。
- issue 会写回 `execution_workspace_id` 与 `execution_workspace_preference`，重复解析优先复用已有 active/idle/in_review workspace。

## 15D：Managed Workspace Preflight 与 Runtime Context 注入

- 在 run 真正调用 runtime adapter 前执行 workspace preflight。
- 构造并注入上游兼容 runtime context/env，包括主 workspace、workspace 列表、workspace source/strategy/id/repo/ref/branch/worktree path，以及 organization workspace/artifacts 目录。
- 保留 runtime service intents、agent home、instructions、skills 等 Step 14 已建立能力的 context 入口，但不在本步骤重写 adapter 行为。
- preflight 失败必须写入 run/event/operation 可追踪状态，并阻止 adapter 执行。

实施记录：

- `HeartbeatService._prepare_workspace_context()` 在 adapter 执行前调用 workspace preflight，并将结果写入 run `context_snapshot`。
- Runtime adapter 收到 `workspace` context、workspace env、managed cwd，包含 `OCTOPUS_WORKSPACE_ID`、`OCTOPUS_WORKSPACES_JSON`、`OCTOPUS_ORG_WORKSPACE_ROOT`、`OCTOPUS_ORG_SKILLS_DIR`、`OCTOPUS_ORG_PLANS_DIR`、`OCTOPUS_ORG_ARTIFACTS_DIR`。
- issue/project run 解析出 project workspace 或 execution workspace `cwd` 后，`HeartbeatService` 会用该 `cwd` 覆盖 agent runtime config 中的旧 `cwd`；agent runtime config 的 `cwd` 只作为非 issue/project run 或无 workspace 上下文时的 fallback。
- Runtime guidance 会提示本地 CLI：把项目源码、下载物、依赖快照和代码修改放在 workspace worktree，将报告、截图、CSV、mockup、日志和 handoff 文档放在 organization artifacts。
- Project 没有 workspace，或选中的 project workspace 没有本地 `cwd` 时，preflight 按上游行为使用组织共享 workspace root 作为执行 cwd，并在 execution workspace metadata 中记录 `fallback=organization_workspace` 和 warning。
- 本地 managed workspace 目录由 `WorkspaceService._ensure_managed_workspace_paths()` 统一生成，不由 route 或 adapter 拼接。

## 15E：Workspace Runtime Service 生命周期

- 实现 `workspace_runtime_services` 持久化和 service 层生命周期。
- 支持 workspace runtime service 的 establish、reuse、release、stop 或上游等价状态流转。
- 将已建立的 runtime service reports 注入 runtime adapter context，供本地 adapter 或后续 UI/CLI 使用。
- 失败、取消和恢复时必须释放或标记 service 状态，避免遗留 running/in-use 业务记录。

实施记录：

- `RuntimeExecutionResult.runtime_services` 由 heartbeat 执行完成后统一交给 `WorkspaceService.persist_adapter_runtime_services()` 持久化。
- ephemeral runtime service 在 run 结束、失败、取消或 recovery 收尾时由 `release_runtime_services_for_run()` 标记为 `stopped`。

## 15F：Workspace Operation 与 Run 关联

- 实现 workspace operation 创建、状态更新、日志记录和查询边界。
- 将 heartbeat run、execution workspace、workspace runtime service 和 operation 关联起来，方便恢复和审计。
- 取消、timeout、preflight failure、adapter failure 和 recovery run 都需要有可解释 operation 状态。
- operation 日志只记录控制面可追踪信息，不替代 Step 21 的附件或对象存储。

实施记录：

- `WorkspaceService.begin_operation()` / `finish_operation()` 记录 preflight 与 adapter execution operation。
- operation 关联 `heartbeat_run_id` 与 `execution_workspace_id`，stdout/stderr excerpt 只记录控制面摘要。
- `mark_run_workspace_interrupted()` 会把 cancel/recovery 时仍处于 `running` 的 operation 标记为 `failed`，并写入 `interrupted` 与原因 metadata。

## 15G：Work Product / Artifact 引用

- 实现上游已包含的 work product 引用结构，记录 issue/run/workspace 产生的产物引用。
- 本步骤只持久化引用、类型、来源和关联关系；真实文件上传、对象存储、下载权限和 attachment body 归 Step 19。
- Runtime adapter 输出中若包含产物引用，应通过统一 service 写入，不能由 adapter 直接操作业务表。
- 产物引用必须受 organization/issue/workspace scope 约束。

实施记录：

- `RuntimeExecutionResult.work_products` 支持 adapter 输出 work product 引用。
- `WorkspaceService.persist_run_work_products()` 统一写入 `issue_work_products`，并关联 issue、project、execution workspace、runtime service 和 run。
- `IssueService.get_by_id()` 已聚合返回 `workProducts`。

## 15H：清理、恢复与测试

- 补齐失败、取消、server 重启恢复时 workspace、runtime service、operation 和 run 的一致性处理。
- 针对重复触发、恢复 run、preflight failure、adapter failure、cancel 和 timeout 增加 workflow tests。
- 增加 contract tests 覆盖 workspace path、payload、response、枚举和错误结构。
- 补充 curl 验收 demo，展示 project workspace、agent run、workspace context、runtime service、operation 和 work product 引用的最小闭环。

实施记录：

- `HeartbeatService.cancel_run()` 在标记 run cancelled 后调用 workspace 收尾，释放 ephemeral runtime service，并将未完成 operation 置为 failed。
- `HeartbeatService.recover_orphaned_runs()` 在 server recovery 标记 orphaned run failed 后执行同样 workspace 收尾，并保留 automatic retry 语义。
- `tests/contract/test_step15_workspace_contract.py` 覆盖 schema/migration、project workspace 聚合、execution workspace 解析、runtime context/env 注入、runtime service release、operation 记录、work product 引用、cancel/recovery 清理。

curl 验收 demo：

```powershell
$base = "http://127.0.0.1:8000"
$org = curl.exe -s -X POST "$base/api/orgs" -H "Content-Type: application/json" -d '{"urlKey":"step15-demo","name":"Step 15 Demo","issuePrefix":"WKS"}' | ConvertFrom-Json
$project = curl.exe -s -X POST "$base/api/orgs/$($org.id)/projects" -H "Content-Type: application/json" -d '{"name":"Workspace Demo","executionWorkspacePolicy":{"enabled":true,"defaultMode":"isolated_workspace"}}' | ConvertFrom-Json
curl.exe -s -X POST "$base/api/projects/$($project.id)/workspaces" -H "Content-Type: application/json" -d '{"name":"Primary","cwd":"D:/work/step15-demo"}'
$agent = curl.exe -s -X POST "$base/api/orgs/$($org.id)/agents" -H "Content-Type: application/json" -d '{"name":"Workspace Agent","agentRuntimeType":"process","agentRuntimeConfig":{"command":"python","args":["-c","import os; print(os.environ.get(\"OCTOPUS_WORKSPACE_ID\"))"]}}' | ConvertFrom-Json
$issue = curl.exe -s -X POST "$base/api/orgs/$($org.id)/issues" -H "Content-Type: application/json" -d "{\"title\":\"Workspace run demo\",\"projectId\":\"$($project.id)\"}" | ConvertFrom-Json
curl.exe -s -X POST "$base/api/agents/$($agent.id)/wakeup" -H "Content-Type: application/json" -d "{\"payload\":{\"issueId\":\"$($issue.id)\"}}"
```

## 当前实施基线

- Step 10 已有 Project 管理，Step 15 已补齐 project workspace 聚合和 execution workspace 行为。
- Step 11/13 已有 run、event、cancel、retry 和 runtime adapter 执行链路，Step 15 已接入 workspace preflight、context 注入和执行收尾。
- Step 14 已有 runtime adapter、skills、model discovery、instructions 和 quota probe 能力，Step 15 已将 workspace context/env 提供给 adapter。
- Step 15 已完成 project workspace、execution workspace、workspace runtime service、workspace operation 和 work product 引用闭环。

## 不包含

- Cost/activity 查询归 Step 21；budget、quota window 聚合与治理联动归 Step 22。
- Chat/Messenger 扩展归 Step 16；消息附件 metadata 和 transcript 可见性归 Step 18，完整 storage lifecycle 归 Step 19。
- Attachment body、对象存储、文件上传下载和存储权限，归 Step 19。
- 真实认证、secret/env binding 和访问策略替换，归 Step 23。
- Desktop/Tauri workspace UI。
- 没有上游证据的 workspace provider、远程基础设施编排或新业务对象。

## 验收

- Contract tests 覆盖 workspace、runtime service、operation、work product 引用的 path、payload、response 和错误结构。
- Workflow tests 覆盖 project workspace 聚合、execution workspace 创建/复用、run preflight、runtime context 注入、runtime service 生命周期、operation 日志和 work product 引用。
- 失败、取消、timeout 和 recovery run 不会留下不一致的 workspace、service、operation 或 run 状态。
- Runtime adapter 接收到的 workspace context/env 与上游结构保持兼容，adapter 差异不泄漏到业务 API。
- Project、issue、run、workspace、work product 的关联全部受 organization scope 约束。

已执行验证：

- `uv run pytest tests/contract/test_step15_workspace_contract.py -q`：10 passed。
- `uv run pytest tests/workflows/test_step13_run_workflow.py tests/contract/test_step15_workspace_contract.py -q`：17 passed。
- `uv run ruff check packages/database/queries/workspaces.py server/services/workspaces.py server/services/heartbeat.py tests/contract/test_step15_workspace_contract.py`：All checks passed。
- `uv run ruff check .`：All checks passed。
- `uv run ruff format --check .`：193 files already formatted。
