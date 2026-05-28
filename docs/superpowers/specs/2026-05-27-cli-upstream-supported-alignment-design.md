# CLI 上游已支持能力对齐设计

## 目标

在不修改 `server/`、`packages/` 或 API 契约的前提下，将 Python CLI 的命令面向上游控制面中已经存在、且本项目服务端已经支持的能力靠齐。

## 范围

本轮新增以下入口：

- `issue comment <issue-id> --body <text>`：作为现有 `comment-add` 的上游风格入口，旧命令保留兼容。
- `agent configuration <agent-id>`：读取智能体配置快照。
- `agent config-revisions <agent-id>`：读取配置修订列表。
- `agent config-revision <agent-id> <revision-id>`：读取单个配置修订。
- `agent runtime-state <agent-id>`：读取运行态。
- `agent task-sessions <agent-id>`：读取任务会话。
- `heartbeat run --agent-id <agent-id>`：以上游风格触发一次 heartbeat；现有 `agent invoke` 保留。

## 排除范围

- 不新增 `chat` 命令：上游 CLI 没有对话命令，本项目已有命令保留。
- 不新增 `org export/import/delete`、issue 搜索/文档/checkout、approval comment/issues、agent skills/hire/inbox 等命令，因为当前服务端没有对应接口。
- 不新增 agent 配置 rollback 或 reset-session 命令：虽然当前服务端提供接口，但不属于本次上游命令对齐所需的最小范围。

## 命令与 API 映射

| CLI 命令 | HTTP 请求 |
| --- | --- |
| `issue comment <id> --body <text>` | `POST /api/issues/{id}/comments` |
| `agent configuration <id>` | `GET /api/agents/{id}/configuration` |
| `agent config-revisions <id>` | `GET /api/agents/{id}/config-revisions` |
| `agent config-revision <id> <revision-id>` | `GET /api/agents/{id}/config-revisions/{revisionId}` |
| `agent runtime-state <id>` | `GET /api/agents/{id}/runtime-state` |
| `agent task-sessions <id>` | `GET /api/agents/{id}/task-sessions` |
| `heartbeat run --agent-id <id>` | `POST /api/agents/{id}/heartbeat/invoke` |

## 兼容与错误处理

- 现有命令不移除、不改已有 HTTP 行为。
- 新命令复用 `ApiClient` 的输出和服务端 `detail` 错误传播。
- `heartbeat run` 使用现有无参数 invoke 路由，不添加上游服务端才有的附加 options。

## 测试与文档

- 在现有 CLI 测试文件中为新命令验证路径、HTTP method 与 payload。
- 更新 `cli/README.md`，优先展示 `org`、`issue comment` 与 `heartbeat run`，并明确本项目扩展命令。
- 完成后运行 CLI 测试与仓库既有校验。
