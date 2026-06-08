# Agent runtime 问题记录

## Bug 列表

当前记录：12 个。

| 编号 | 问题 | 状态 |
| --- | --- | --- |
| 1 | Agent skill 未启用 | 已修复 |
| 2 | 组织工作区 legacy layout 可能导致 UI 文件树为空 | 已修复 |
| 3 | Agent workspace home 未初始化 `life/`、`memory/`、`skills/` | 已修复 |
| 4 | SQLite DB 与 Octopus home 默认不同源导致 workspace 写到用户目录 | 已修复，Step 23 已改为上游式 instance db layout |
| 5 | 切换 Octopus home 后已有 managed instructions 仍指向旧绝对路径 | 已修复 |
| 6 | Agent workspace key 被二次 normalize 导致目录分裂 | 已修复 |
| 7 | Run logs 默认不在 instance `data/run-logs` 下 | 已修复 |
| 8 | 缺少 instance-scoped server/app 文件日志目录 | 已修复 |
| 9 | Issue run 的 `cwd` 可能被旧 agent runtime config 带回 repo 根目录 | 已修复 |
| 10 | 无 project 的 issue run 没有 fallback 到 organization workspace | 已修复 |
| 11 | Chat run 没有 organization artifacts context，产物落到 cwd | 已修复 |
| 12 | runtime home、workspace、DB 路径仍存在非上游式 legacy/error layout | 已修复，Step 23C |

## 1. Agent skill 未启用

### 背景

Octopus 中有两套容易混淆的 skill 概念：

- `.agents/skills`：开发 Octopus 项目时，当前 Codex/Claude/OpenCode 开发助手使用的技能目录。
- 产品内 agent skill：Octopus server 管理的组织 skill、agent private skill，以及某个产品 agent 已选择启用的 skill。

`agent_enabled_skills` 只属于产品内 agent runtime，不代表 `.agents/skills` 是否生效。

### 症状

- `organization_skills` 中已有组织 skill。
- `agent_enabled_skills` 为空。
- agent 执行 heartbeat/chat 时仍可运行。
- runtime 收到的 `desiredSkills` 为 `[]`。
- 组织 skill 或 agent private skill 不会被 materialized 到 runtime home。
- 该 agent 的任务执行中不会加载这些可选 skill。

### 数据链路

- `organization_skills`：组织 skill 库，表示组织有哪些 skill 可选。
- `agent_enabled_skills`：agent 已启用 skill 选择，核心字段是 `org_id`、`agent_id`、`skill_key`。
- heartbeat/chat 执行前，server 通过 `list_enabled_skill_keys(agent.id)` 读取启用列表，并写入 runtime config 的 `desiredSkills`。
- local runtime 根据 `desiredSkills` 将目标 skill materialize 到对应 runtime home。

因此，`organization_skills` 有数据但 `agent_enabled_skills` 为空时，只能说明 skill 可选，不能说明任何 agent 已经启用。

### 影响边界

- 这不是 `.agents/skills` 未生效；`.agents/skills` 是开发助手技能目录，不属于产品内 agent runtime。
- 这不是 agent 本身不能运行；agent 仍可执行任务，只是没有加载可选 skill。
- 组织 skill 入库不会自动启用到所有 agent。

### 修复

服务端已补齐默认启用和迁移 backfill：

- 新创建 agent 时，如果请求没有显式传 `desiredSkills`，默认写入 `skills/control-plane` 到 `agent_enabled_skills`。
- 如果请求显式传 `desiredSkills: []`，尊重显式空列表，不自动补默认值。
- 新增 migration `20260605_000017`，升级时给已有非 terminated agent backfill `skills/control-plane`。
- runtime skill materialization 支持把 `skills/control-plane` 这种 organization/bundled key 映射到磁盘目录 `control-plane`，避免 DB 有记录但 runtime home 不装载。

手动入口仍可继续使用。对已有 agent，可以追加启用：

对已有 agent，可以追加启用：

```text
POST /api/agents/{id}/skills/enable
body: { "skills": ["<skill-key-or-selection-ref>"] }
```

也可以替换完整启用列表：

```text
POST /api/agents/{id}/skills/sync
body: { "desiredSkills": ["<skill-key-or-selection-ref>"] }
```

`enable` 是追加；`sync` 是替换完整列表。

### 验收

- `agent_enabled_skills` 中出现目标 `agent_id` 与 `skill_key`。
- `GET /api/agents/{id}/skills` 返回的 `desiredSkills` 包含目标 skill。
- 下一次 runtime 执行前，启用的 skill 被 materialized 到对应 runtime home。
- heartbeat/chat run 的 runtime config 中 `desiredSkills` 不再是 `[]`。
- 新建 agent 未显式传 `desiredSkills` 时，返回 `desiredSkills=["skills/control-plane"]`。
- 旧库升级后，已有非 terminated agent 自动补 `skills/control-plane`。

## 2. 组织工作区 legacy layout 可能导致 UI 文件树为空

### 背景

上游 control-plane 和当前 Octopus 代码的 canonical organization workspace 路径是：

```text
<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/organizations/<orgId>/workspaces
```

默认本地路径通常是：

```text
.octopus/instances/default/organizations/<orgId>/workspaces
```

但本地可能仍然存在旧布局或迁移残留：

```text
.octopus/organizations/<orgId>/workspaces
```

这两个目录不是同一个 workspace root。如果 server、runtime、UI workspace browser、skill scan 或 artifact 写入混用了两套路径，就会导致同一个 org 的文件分散在不同目录。

### 症状

- UI “组织 - 工作区 - 文件”下的 `agents/`、`skills/`、`plans/` 或 `artifacts/` 为空。
- 磁盘上另一个 workspace root 里能看到对应文件。
- agent instructions、agent private skills、organization skills 或 artifacts 看起来“丢失”。
- UI 浏览路径和 runtime 写入路径不一致。

### 影响边界

- 如果 `.octopus/organizations/<orgId>/workspaces` 只是历史空目录，不一定影响当前运行。
- 如果真实内容仍写在 legacy 路径，而 UI 读取 canonical instance 路径，则 UI 会显示为空。
- 如果 canonical 路径已有内容但 UI 仍为空，则还需要排查当前 server 的 `OCTOPUS_HOME`、`OCTOPUS_INSTANCE_ID`、运行进程版本、选中 org 是否一致，以及前端是否过滤空目录。

### 预期行为

所有组织工作区读写应统一使用 canonical instance 路径：

```text
<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/organizations/<orgId>/workspaces
```

该目录下应按需出现：

```text
agents/
skills/
plans/
artifacts/
executions/
```

### 修复

- 明确 `.octopus/organizations/<orgId>/workspaces` 为 legacy layout。
- 新增 `ensure_organization_workspace_root(orgId)` 作为带迁移能力的 organization workspace root 入口。
- 如果 legacy root 有内容且 canonical root 为空，会将 legacy `workspaces/` 移动到 canonical instance path。
- 如果 canonical root 已存在，会把 legacy 下未冲突的子目录/文件合并到 canonical root；冲突内容保留在 legacy path，避免覆盖数据。
- UI workspace browser、WorkspaceService、organization skills 和 agent workspace home 都改为通过 ensure 入口获取 workspace root。

### 验收

- UI workspace browser 读取的 root 与 `organization_workspace_root(orgId)` 一致。
- 新创建的 agent instructions / private skills 落在 canonical `workspaces/agents/<agentWorkspaceKey>/`。
- 新导入的 org skills 落在 canonical `workspaces/skills/<slug>/`。
- 新 run 产物落在 canonical `workspaces/artifacts/` 或 `workspaces/executions/` 下。
- legacy `.octopus/organizations/<orgId>/workspaces` 不再被新写入。
- `tests/contract/test_workspace_paths.py` 覆盖 legacy layout 迁移。

## 3. Agent workspace home 未初始化 `life/`、`memory/`、`skills/`

### 背景

上游 agent workspace home 通常位于：

```text
<OCTOPUS_HOME>/instances/<instanceId>/organizations/<orgId>/workspaces/agents/<agentWorkspaceKey>/
```

该目录除了 `instructions/`，还应作为 agent 长期资料根目录，包含：

```text
instructions/
skills/
life/
memory/
```

其中：

- `instructions/`：说明文件 bundle，例如 `SOUL.md`、`HEARTBEAT.md`、`TOOLS.md`、`MEMORY.md`。
- `skills/`：agent-private skill package 根目录，例如 `skills/<slug>/SKILL.md`。
- `life/`：长期结构化记忆目录，供 `para-memory-files` 等 skill 使用。
- `memory/`：每日或会话时间线记忆目录，例如 `memory/YYYY-MM-DD.md`。

注意：`instructions/MEMORY.md` 和 `memory/` 目录不是同一个东西。前者是说明文件 bundle 里的长期偏好/操作模式文件；后者是运行中不断追加的时间线记忆目录。

### 症状

- 上游同类目录下能看到 `life/`、`memory/`、`skills/`，当前本地 agent workspace home 下没有。
- UI “组织 - 工作区 - 文件 - agents/<agent>/” 下只看到 `instructions/`，或目录为空。
- `para-memory-files` skill 和 onboarding 文档引用 `$AGENT_HOME/life/`、`$AGENT_HOME/memory/`，但磁盘上没有对应目录。
- agent private skill 只有在首次创建私有 skill 时才出现 `skills/`，空目录不会提前展示。

### 影响边界

- `skills/` 缺失会影响 agent-private skill 的可见性和 workspace browser 的一致性。
- `life/`、`memory/` 缺失不一定会让当前 run 直接失败，但属于上游目录约定未 materialize，运行时写记忆时会缺少预期落点。
- 这不是 `agent_enabled_skills` 为空的问题；那张表表达“启用了哪些 skill”，这里表达“agent 长期 home 是否具备上游约定目录”。

### 修复

- 新建 agent 时，server 会在 agent workspace home 下初始化 `instructions/`、`skills/`、`life/`、`memory/`。
- 准备 runtime config、查询或同步 skills 时，也会对已有 agent 补齐这些目录。
- `agentSkillsRootPath` 指向已创建的 `<agent workspace home>/skills/`。

### 验收

- 新建 agent 后，canonical instance path 下出现：

```text
.octopus/instances/default/organizations/<orgId>/workspaces/agents/<agentWorkspaceKey>/instructions/
.octopus/instances/default/organizations/<orgId>/workspaces/agents/<agentWorkspaceKey>/skills/
.octopus/instances/default/organizations/<orgId>/workspaces/agents/<agentWorkspaceKey>/life/
.octopus/instances/default/organizations/<orgId>/workspaces/agents/<agentWorkspaceKey>/memory/
```

- 已有 agent 下一次准备 runtime config 或查询/sync skills 后，也会补齐上述目录。
- `tests/workflows/test_step11_agent_workflow.py` 覆盖目录初始化。

## 4. SQLite DB 与 Octopus home 默认不同源导致 workspace 写到用户目录

### 背景

旧版本开发阶段常见启动方式是在仓库根目录使用默认 SQLite：

```text
D:\coding\octopus\octopus.db
```

当时组织工作区、agent workspace home、runtime home、storage/logs 等本地文件也应该落在同一个开发数据根附近：

```text
D:\coding\octopus\.octopus
```

正式或桌面运行可以把数据都放到用户目录，但 DB 和 Octopus home 必须一起切换，而不是 DB 在仓库、workspace 在用户目录。

### 症状

- `octopus.db` 在 `D:\coding\octopus\octopus.db`。
- 新建 agent 后，`agents.agent_runtime_config.instructionsRootPath` 指向：

```text
C:\Users\<user>\.octopus\instances\default\organizations\<orgId>\workspaces\agents\<agentWorkspaceKey>\instructions
```

- VSCode 打开的 `D:\coding\octopus\.octopus` 没变化。
- 同一个 DB 中同时存在旧 agent 指向 repo-local `.octopus`，新 agent 指向 user-home `.octopus`。

### 根因

旧逻辑中：

- `OCTOPUS_DATABASE_URL` 默认是 `sqlite+aiosqlite:///./octopus.db`。
- `OCTOPUS_HOME` 未设置时默认是 `~/.octopus`。

因此在仓库根目录启动 server 时，DB 和 workspace home 默认就不是同源目录。

### 修复

Step 23 后修复规则调整为对齐上游 instance layout：

- 显式设置 `OCTOPUS_HOME` 时仍以显式配置为准。
- 未设置 `OCTOPUS_HOME` 时，默认 Octopus home 是用户目录下的 `.octopus`，不再从数据库 URL 反推。
- SQLite 默认 URL 由 `OCTOPUS_HOME` 和 `OCTOPUS_INSTANCE_ID` 生成，文件位于 `<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db`。
- 使用 PostgreSQL/MySQL 外部连接时，数据库连接不会携带文件侧 instance root；部署配置或启动器必须同时绑定 `OCTOPUS_HOME` / `OCTOPUS_INSTANCE_ID`。

### 验收

仓库根目录开发如果显式设置 `OCTOPUS_HOME=D:\coding\octopus\.octopus`，默认路径应是：

```text
D:\coding\octopus\.octopus\instances\default\db\octopus.db
D:\coding\octopus\.octopus\instances\default\organizations\<orgId>\workspaces
```

如果正式/桌面运行希望使用用户目录，需要同时设置：

```powershell
$env:OCTOPUS_HOME = "C:/Users/<user>/.octopus"
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///C:/Users/<user>/.octopus/instances/default/db/octopus.db"
```

或者由启动器只设置 `OCTOPUS_HOME` / `OCTOPUS_INSTANCE_ID`，让 server 生成默认 SQLite URL。

## 5. 切换 Octopus home 后已有 managed instructions 仍指向旧绝对路径

### 背景

`agents.agent_runtime_config` 会持久化：

```text
instructionsBundleMode
instructionsRootPath
instructionsEntryFile
instructionsFilePath
```

如果某个 agent 是在旧 `OCTOPUS_HOME` 下创建的，`instructionsRootPath` 可能是旧 home 的绝对路径。之后即使 server 默认 home 修正到当前 DB 同级 `.octopus/`，已有 agent 仍可能继续指向旧路径。

### 症状

- `GET /api/orgs/{orgId}/workspace/files?path=` 返回 `agents/`、`artifacts/`、`plans/`、`skills/`。
- 但 `agents/` 目录下面是空的。
- DB 中该 org 的 agent 存在，且 `instructionsRootPath` 指向另一套 home，例如：

```text
C:\Users\<user>\.octopus\instances\default\organizations\<orgId>\workspaces\agents\<agentWorkspaceKey>\instructions
```

- 当前 UI workspace root 指向：

```text
D:\coding\octopus\.octopus\instances\default\organizations\<orgId>\workspaces
```

### 根因

默认 home 修正只能影响后续路径解析；已经持久化到 DB 的 managed instructions 绝对路径不会自动改写。于是 workspace browser 看当前 canonical root，而 agent instructions 仍留在旧 root。

### 修复

- 读取 managed instructions bundle 时，如果发现 `instructionsBundleMode=managed` 但 `instructionsRootPath` 不等于当前 agent workspace home 下的 `instructions/`，server 会：
  - 先导出旧 root 中已有说明文件。
  - 写入当前 managed root。
  - 补齐默认 bundle 文件。
  - 更新 DB 中的 `instructionsRootPath` 和 `instructionsFilePath`。

### 验收

- 访问 `GET /api/agents/{agentId}/instructions-bundle` 后，当前 workspace root 下出现：

```text
agents/<agentWorkspaceKey>/instructions/
```

- 旧 root 中的 `SOUL.md`、`MEMORY.md` 等内容被带到当前 managed root。
- DB 中 `agents.agent_runtime_config.instructionsRootPath` 指向当前 `OCTOPUS_HOME` 对应的 canonical path。

## 6. Agent workspace key 被二次 normalize 导致目录分裂

### 背景

`agents.workspace_key` 是持久化的 agent workspace 目录名，例如：

```text
ceo-1--623d0e91
```

这个值一旦写入 DB，后续所有 agent workspace home 解析都应直接使用它，不能再重新 slug/normalize。

### 症状

同一个 agent 在 workspace browser 中出现两个相似目录：

```text
agents/ceo-1--623d0e91/
agents/ceo-1-623d0e91/
```

其中：

- `ceo-1--623d0e91/instructions/` 有 `SOUL.md`、`MEMORY.md` 等说明文件。
- `ceo-1-623d0e91/instructions/`、`life/`、`memory/`、`skills/` 只是空目录。

### 根因

不同服务使用了不同的 workspace key 计算方式：

- instructions bundle 使用 DB 中的 `workspace_key`，保留 `--`。
- runtime config / agent workspace layout 又对 `workspace_key` 做了一次 URL key normalize，把 `--` 压成 `-`。

因此同一个 agent 的长期目录被分裂成两个磁盘路径。

### 修复

- 当 `agents.workspace_key` 存在时，agent workspace home 解析直接使用 DB 值。
- 只有旧数据缺少 `workspace_key` 时，才从 agent name / id 推导 fallback。
- instructions service 和 agent runtime preparation 使用同一规则。

### 验收

- `agentSkillsRootPath` 的父目录名等于 DB 中的 `workspace_key`。
- managed instructions root 保留 `workspace_key` 中的双连字符。
- 新触发 runtime config 或 instructions bundle 后，不再创建被二次 normalize 的空目录。

## 7. Run logs 默认不在 instance `data/run-logs` 下

### 背景

上游 Rudder 的 run log store 默认挂在 instance root 下：

```text
<RUDDER_HOME>/instances/<RUDDER_INSTANCE_ID>/data/run-logs
```

Octopus 之前默认写到：

```text
<OCTOPUS_HOME>/run-logs
```

这会绕开 `OCTOPUS_INSTANCE_ID`，导致不同本地 instance 的 heartbeat/runtime run 日志可能混在同一个目录，也不利于按 instance 清理、备份或迁移。

### 修复

- `OCTOPUS_RUN_LOG_DIR` 显式设置时继续优先生效。
- 未设置时，默认改为：

```text
<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/data/run-logs
```

### 验收

- 默认开发路径变为：

```text
D:\coding\octopus\.octopus\instances\default\data\run-logs
```

- `tests/contract/test_step20_observability.py` 覆盖默认路径和 env override。

## 8. 缺少 instance-scoped server/app 文件日志目录

### 背景

上游 Rudder 有两类日志目录：

```text
<RUDDER_HOME>/instances/<instance>/logs
<RUDDER_HOME>/instances/<instance>/data/run-logs
```

其中 `logs/` 是 server/app 自身日志，`data/run-logs/` 是 agent run 的执行日志。Octopus 之前只有 run log store，没有初始化 instance-scoped server/app file log 目录。

### 修复

- server 启动时创建并配置：

```text
<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/logs/octopus.log
```

- `OCTOPUS_LOG_DIR` 显式设置时可覆盖该目录。
- `OCTOPUS_LOG_LEVEL` 同时用于控制文件 handler 的日志等级。

### 验收

- `uv run server` 启动时会创建 instance `logs/` 目录和 `octopus.log` 文件。
- `tests/contract/test_step2_server_skeleton.py` 覆盖 server main 的日志目录初始化。

## 9. Issue run 的 `cwd` 可能被旧 agent runtime config 带回 repo 根目录

### 背景

Octopus runtime 有两类路径：

- `cwd`：runtime 子进程实际启动目录。相对路径读写默认发生在这里。
- artifacts dir：server 为 organization workspace 准备的 durable output 目录，即 `workspaces/artifacts/`。严格对齐上游时，默认不按 issue/run/chat 在文件系统里细分 artifacts；issue/run 关联由 DB work product metadata 表达。

`cwd` 不是产物归档目录。报告、截图、CSV、mockup、handoff 文件等 durable output 应优先写到 `RUDDER_ORG_ARTIFACTS_DIR` 或对应 control-plane organization artifacts env。

### 症状

- agent run 后，仓库根目录 `D:\coding\octopus` 下出现 `hello.py`、`ACCEPTANCE.md`、报告文件等任务产物。
- 同一 run 的 organization workspace artifacts 目录存在，但目标产物没有写进去。
- issue/project 已经绑定到 workspace，但 runtime 仍在旧 cwd 下执行。

### 根因

旧逻辑中，heartbeat 执行前会先读取 agent 的 `agent_runtime_config`。如果里面已经有 `cwd`，workspace preflight 解析出的 `rudderWorkspace.cwd` 不会覆盖它：

```text
agent_runtime_config.cwd wins over workspace cwd
```

这会导致历史 agent 配置、开发期手动配置或 server 启动目录相关配置把 issue run 带回 repo 根目录。runtime 再写相对路径时，产物就会落到 `D:\coding\octopus`。

同时，部分测试 adapter 也把交付物写到 `context.config["cwd"]`，等于把“执行目录”误当成“产物目录”，容易把错误语义固化。

### 修复

- issue/project run 只要 workspace preflight 解析出 `rudderWorkspace.cwd`，heartbeat 执行时就用该 cwd 覆盖 agent runtime config 中的旧 `cwd`。
- 非 issue/project run 仍可继续使用 agent runtime config 中的显式 `cwd`。
- 闭环验收测试中的 durable output 示例改为写 `RUDDER_ORG_ARTIFACTS_DIR`，不再示范把交付物写 cwd。

### 验收

- agent runtime config 即使保存了 `cwd=D:\coding\octopus`，issue run 仍会在 workspace resolver 解析出的 cwd 下执行。
- 相对路径写入不会再因为旧 agent cwd 配置落到 repo 根目录。
- durable output 示例写入：

```text
<OCTOPUS_HOME>/instances/<instanceId>/organizations/<orgId>/workspaces/artifacts/
```

- `tests/contract/test_step15_workspace_contract.py` 覆盖 issue run workspace cwd 覆盖旧 agent runtime cwd。
- `tests/contract/test_step22_closed_loop_acceptance.py` 覆盖闭环产物写入 organization artifacts。

## 10. 无 project 的 issue run 没有 fallback 到 organization workspace

### 背景

Issue run 不一定绑定 project。按运行时 workspace 语义：

- 有 project workspace 时，优先使用 project/execution workspace。
- 没有 project workspace 时，fallback 到 organization workspace。
- 没有 `project_id` 的 issue 也应该 fallback 到 organization workspace，而不是跳过 workspace preflight。

### 症状

- `ceo-1` 这类无 project issue run 中，agent 打印 `RUDDER_ORG_ARTIFACTS_DIR` 为空。
- `heartbeat_runs.context_snapshot` 中有 `issueId`，但没有 `workspace`。
- `contextSnapshot.workspace.env.RUDDER_ORG_ARTIFACTS_DIR` 不存在。
- agent 只能看到 runtime 当前 cwd，例如 `D:\coding\octopus`，无法知道 organization artifacts 目录。

### 根因

旧逻辑中：

```text
issue.project_id is None -> WorkspaceService.resolve_for_issue() returns None
```

因此 `prepare_runtime_context_for_run()` 直接返回 `None`，heartbeat 执行时不会注入 workspace context/env。

### 修复

- `issue.project_id is None` 时构造 organization workspace fallback runtime context。
- 该 fallback 不创建 `execution_workspaces` 数据库行，避免触碰当前 `execution_workspaces.project_id` 非空 schema。
- workspace cwd 指向 canonical organization workspace root。
- 注入 `RUDDER_ORG_ARTIFACTS_DIR`。
- generated artifacts 扫描允许 `executionWorkspaceId=None`，仍可登记 organization artifacts 产物。

### 验收

- 无 project issue 的 run 也会得到：

```text
contextSnapshot.workspace.env.RUDDER_ORG_ARTIFACTS_DIR
```

- 产物可以落到：

```text
<OCTOPUS_HOME>/instances/<instanceId>/organizations/<orgId>/workspaces/artifacts/
```

- `tests/contract/test_step15_workspace_contract.py` 覆盖 projectless issue fallback 到 organization workspace。

## 11. Chat run 没有 organization artifacts context，产物落到 cwd

### 背景

上游 Rudder 的 chat 可以调用 runtime，但 durable execution 仍应有明确 workspace context。严格对齐上游时，runtime 默认只获得 organization artifacts：

```text
RUDDER_ORG_ARTIFACTS_DIR
```

普通 chat 没有 issue 时，也需要 organization workspace cwd 和 organization artifacts env，避免 agent 把文件写到 server cwd 或开发仓库根目录。

### 症状

- 在 chat 中让 agent 创建文件，agent 回复“环境变量未设置”，然后写到：

```text
D:\coding\octopus\hello_world.md
```

- `RUDDER_ORG_ARTIFACTS_DIR` 不可见。
- 文件没有进入 organization workspace，也不会被稳定展示为任务产物。

### 修复

- Chat runtime 调用前也准备 workspace context/env。
- 没有 primary issue 的 chat 注入：

```text
RUDDER_ORG_ARTIFACTS_DIR
```

- organization artifacts 路径为：

```text
<OCTOPUS_HOME>/instances/<instanceId>/organizations/<orgId>/workspaces/artifacts/
```

- chat runtime `cwd` 覆盖为 organization workspace root，避免默认落回 server cwd。
- runtime env/guidance 严格对齐上游，只暴露 organization artifacts，不默认暴露 conversation/run artifacts。
- 如果 chat 绑定 primary issue，则优先复用 issue workspace context，但 artifacts 仍是 organization artifacts。

### 验收

- 普通 chat run 的 adapter env 中存在 `RUDDER_ORG_ARTIFACTS_DIR`。
- 普通 chat run 的 adapter env 中不存在 `RUDDER_CONVERSATION_ARTIFACTS_DIR`、`RUDDER_ISSUE_ARTIFACTS_DIR`、`RUDDER_RUN_ARTIFACTS_DIR`。
- 普通 chat run 的 cwd 是 organization workspace root，而不是 `D:\coding\octopus`。
- `tests/contract/test_step11_chat_loop.py` 覆盖 chat runtime organization artifacts env。

## 12. runtime home、workspace、DB 路径仍存在非上游式 legacy/error layout

### 背景

Step 23 已把默认 SQLite 路径对齐到 instance db layout：

```text
<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>/db/octopus.db
```

但文件侧 layout 仍需要继续收口。上游 Rudder 的 runtime home 和 workspace 不是全局目录，而是挂在 instance 和 organization 下。Octopus 中历史上出现过这些非 canonical 路径：

```text
<OCTOPUS_HOME>/runtime-homes
<OCTOPUS_HOME>/instances/<instance>/runtime-homes
<OCTOPUS_HOME>/instances/<instance>/workspaces
<OCTOPUS_HOME>/test-tmp
```

详细路径规则归 Step 23C 收口。

canonical instance root：

```text
<OCTOPUS_HOME>/instances/<OCTOPUS_INSTANCE_ID>
```

核心目录应统一属于同一个 instance root：

```text
<OCTOPUS_HOME>/instances/<instance>/db/octopus.db
<OCTOPUS_HOME>/instances/<instance>/data/storage
<OCTOPUS_HOME>/instances/<instance>/data/run-logs
<OCTOPUS_HOME>/instances/<instance>/logs
<OCTOPUS_HOME>/instances/<instance>/organizations/<orgId>/workspaces
<OCTOPUS_HOME>/instances/<instance>/organizations/<orgId>/codex-home/agents/<agentId>
<OCTOPUS_HOME>/instances/<instance>/organizations/<orgId>/opencode-home
<OCTOPUS_HOME>/instances/<instance>/organizations/<orgId>/claude-home
```

### 症状

- `.octopus/runtime-homes` 或 `.octopus/instances/default/runtime-homes` 下仍有 runtime 数据。
- `.octopus/instances/default/workspaces` 下出现 workspace 数据，但 UI 和 runtime 使用的是 `organizations/<orgId>/workspaces`。
- 测试在 `.octopus/test-tmp` 留下临时数据，污染产品 home。
- 数据库、workspace、runtime home、storage、logs 看起来都在 `.octopus` 下，但不属于同一个 canonical instance root。

### 预期行为

runtime home 应使用 organization-scoped 路径：

```text
<OCTOPUS_HOME>/instances/<instance>/organizations/<orgId>/codex-home/agents/<agentId>
<OCTOPUS_HOME>/instances/<instance>/organizations/<orgId>/opencode-home
<OCTOPUS_HOME>/instances/<instance>/organizations/<orgId>/claude-home
```

organization workspace 应使用：

```text
<OCTOPUS_HOME>/instances/<instance>/organizations/<orgId>/workspaces
```

测试临时数据不应写入产品 home。

### 修复

Step 23C 已修复：

- 新写入不得再创建 `runtime-homes` 或 instance-level `workspaces`。
- 对 legacy runtime home 和 legacy workspace 做 lazy migration。
- storage、run logs、server logs 默认路径应保持 instance-scoped。
- 冲突数据不覆盖，保留在 legacy path 供人工处理。
- 测试临时目录改为 pytest `tmp_path` 或 repo-local `.tmp-pytest`。

### 验收

- 上游对齐路径下能看到 organization workspace、agent workspace home、runtime managed home、storage、run logs 和 server logs。
- `.octopus/runtime-homes/...` 和 `.octopus/instances/<instance>/runtime-homes/...` 不再作为目标目录。
- `.octopus/instances/<instance>/workspaces` 不再作为目标目录。
- `.octopus/test-tmp` 不再由测试创建。

### 验证

- `tests/contract/test_workspace_paths.py` 覆盖 storage、run logs、workspace operation logs、legacy organization workspace 和 instance-level workspaces 迁移。
- `tests/contract/test_step23_database_portability.py` 覆盖 legacy runtime-homes 和 instance-level runtime-homes 迁移。
- `tests/contract/test_step17_agent_instructions.py` 不再写入 `.octopus/test-tmp`。
