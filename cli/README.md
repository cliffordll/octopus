# Octopus CLI

该 CLI 通过当前服务端 API 操作组织工作流。命令面优先采用上游控制面已存在、并且本项目服务端已支持的操作；`project` 与 `chat` 是本项目当前已提供的扩展。

## 启动服务

在仓库根目录启动本地服务：

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run server
```

默认 API 地址为 `http://127.0.0.1:8000`。全局参数应放在资源命令之前：

```powershell
uv run python -m cli --api-base http://127.0.0.1:8000 --json org list
```

## 与上游对齐的命令

### Organization

```powershell
uv run python -m cli org list
uv run python -m cli org get <org-id>
uv run python -m cli org create --name "Demo"
uv run python -m cli org update <org-id> --name "Renamed"
uv run python -m cli org archive <org-id>
```

`organization` 仍可作为 `org` 的兼容名称使用。

### Issue

```powershell
uv run python -m cli issue list --org-id <org-id> --status in_review
uv run python -m cli issue get <issue-id>
uv run python -m cli issue create --org-id <org-id> --title "Review API"
uv run python -m cli issue update <issue-id> --status in_progress
uv run python -m cli issue comment <issue-id> --body "Investigating"
uv run python -m cli issue comment-list <issue-id>
uv run python -m cli issue review <issue-id> --decision approve
```

旧命令 `issue comment-add` 继续有效。

### Approval

```powershell
uv run python -m cli approval list --org-id <org-id> --status pending
uv run python -m cli approval get <approval-id>
uv run python -m cli approval create --org-id <org-id> --type hire_agent --payload '{"name":"Builder"}'
uv run python -m cli approval approve <approval-id> --note "Approved"
uv run python -m cli approval reject <approval-id> --note "Rejected"
uv run python -m cli approval request-revision <approval-id> --note "Revise scope"
uv run python -m cli approval resubmit <approval-id> --payload '{"name":"Builder"}'
```

### Agent

```powershell
uv run python -m cli agent list --org-id <org-id>
uv run python -m cli agent get <agent-id>
uv run python -m cli agent configuration <agent-id>
uv run python -m cli agent config-revisions <agent-id>
uv run python -m cli agent config-revision <agent-id> <revision-id>
uv run python -m cli agent runtime-state <agent-id>
uv run python -m cli agent task-sessions <agent-id>
```

本项目同时保留服务端已支持的管理操作：

```powershell
uv run python -m cli agent create --org-id <org-id> --name Builder --role engineer --runtime codex_local
uv run python -m cli agent pause <agent-id>
uv run python -m cli agent resume <agent-id>
uv run python -m cli agent terminate <agent-id>
uv run python -m cli agent archive <agent-id>
uv run python -m cli agent invoke <agent-id>
```

### Heartbeat

```powershell
uv run python -m cli heartbeat run --agent-id <agent-id>
uv run python -m cli heartbeat list --org-id <org-id> --agent-id <agent-id>
uv run python -m cli heartbeat get <run-id>
uv run python -m cli heartbeat events <run-id>
uv run python -m cli heartbeat debug <run-id>
```

## 本项目已有扩展

当前服务端支持项目与对话 API，因此 CLI 保留这些命令；它们不是依据上游 CLI 新增的对齐范围。

```powershell
uv run python -m cli project list --org-id <org-id>
uv run python -m cli project get <project-id>
uv run python -m cli project resource-list <project-id>

uv run python -m cli chat list --org-id <org-id>
uv run python -m cli chat create --org-id <org-id> --title "你好" --agent-id <agent-id>
uv run python -m cli chat message <chat-id> --body "继续"
uv run python -m cli chat messages <chat-id>
```

上游 CLI 没有 `chat` 对话指令，本项目不会为对齐上游增加 `chat send` 或已有历史会话切换智能体命令。

## 验证

```powershell
uv run pytest cli/tests -q
uv run ruff check cli
uv run pyright cli
```
