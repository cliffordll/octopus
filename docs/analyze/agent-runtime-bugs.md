# Agent runtime 问题记录

## Bug 列表

当前记录：2 个。

| 编号 | 问题 | 状态 |
| --- | --- | --- |
| 1 | Agent skill 未启用 | 待修复 |
| 2 | 组织工作区 legacy layout 可能导致 UI 文件树为空 | 已修复 |

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

### 修复入口

创建 agent 时传入 `desiredSkills`，可写入 `agent_enabled_skills`。

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
