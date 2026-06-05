# Agent runtime 问题记录

## Bug 列表

当前记录：4 个。

| 编号 | 问题 | 状态 |
| --- | --- | --- |
| 1 | Agent skill 未启用 | 已修复 |
| 2 | 组织工作区 legacy layout 可能导致 UI 文件树为空 | 已修复 |
| 3 | Agent workspace home 未初始化 `life/`、`memory/`、`skills/` | 已修复 |
| 4 | SQLite DB 与 Octopus home 默认不同源导致 workspace 写到用户目录 | 已修复 |

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

开发阶段常见启动方式是在仓库根目录使用默认 SQLite：

```text
D:\coding\octopus\octopus.db
```

此时组织工作区、agent workspace home、runtime home、storage/logs 等本地文件也应该落在同一个开发数据根附近：

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

- 显式设置 `OCTOPUS_HOME` 时仍以显式配置为准。
- 未设置 `OCTOPUS_HOME` 且 `OCTOPUS_DATABASE_URL` 是本地 SQLite 文件时，默认 Octopus home 改为数据库文件同级的 `.octopus/`。
- 使用 PostgreSQL、`:memory:` 或无法解析本地 DB 文件时，才退回 `~/.octopus`。

### 验收

仓库根目录开发启动时，默认路径应是：

```text
D:\coding\octopus\octopus.db
D:\coding\octopus\.octopus\instances\default\organizations\<orgId>\workspaces
```

如果正式/桌面运行希望使用用户目录，需要同时设置：

```powershell
$env:OCTOPUS_DATABASE_URL = "sqlite+aiosqlite:///C:/Users/<user>/.octopus/instances/default/data/octopus.db"
$env:OCTOPUS_HOME = "C:/Users/<user>/.octopus"
```

或者由启动器保证这两个值来自同一个 instance 数据根。
