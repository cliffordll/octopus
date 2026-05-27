# UI 与 CLI 一期设计方案

## 1. 目标

在不修改现有 `server/`、`packages/`、数据库结构、API 路径和服务启动方式的前提下，新增两个独立客户端入口：

- `ui/`：浏览器中的操作界面，用于组织、问题和审批流程
- `cli/`：Python HTTP 客户端，用于脚本化调用同一组现有 API

一期仅覆盖当前服务端已经提供的能力，不为尚未实现的领域提前制作空页面或伪接口。

## 2. 明确边界

### 2.1 不改变的内容

- 服务继续通过 `uv run server` 启动。
- 默认服务地址继续为 `http://127.0.0.1:8000`。
- 本地调试 actor 继续由启动服务时设置 `OCTOPUS_LOCAL_TRUSTED=1` 提供。
- `server/`、`packages/`、已有测试与配置文件不纳入一期修改范围。
- 不新增或修改服务端 API，不修改现有 payload、状态值或访问语义。

### 2.2 一期功能范围

一期客户端只消费以下现有业务域：

| 业务域 | 操作范围 |
| --- | --- |
| Organization | 列表、详情、创建、编辑 |
| Issue | 列表、详情、创建、编辑、评论、review decision |
| Approval | 列表、详情、创建、approve、reject、request revision、resubmit |

以下能力不进入一期导航、页面或 CLI 命令：project、goal、agent、run、runtime、workspace、cost、chat、storage、auth。

## 3. 目录结构

```text
octopus/
├─ server/                     # 现有服务端，不修改
├─ packages/                   # 现有共享契约和持久化，不修改
├─ ui/                         # 新增 Web 客户端
│  ├─ package.json
│  ├─ vite.config.ts
│  └─ src/
│     ├─ api/                  # HTTP client 与领域请求封装
│     ├─ components/           # 导航、列表、表单、状态展示
│     ├─ pages/                # 页面组件
│     └─ app/                  # 路由、query client、应用 shell
└─ cli/                        # 新增 Python API 客户端
   ├─ __init__.py
   ├─ __main__.py
   ├─ client.py                # HTTP client 与错误处理
   ├─ output.py                # 文本/JSON 输出
   └─ commands/                # organization / issue / approval 命令
```

两个新增目录均独立依赖现有服务提供的 HTTP API。它们不导入服务端内部 service 或数据库实现，防止客户端和 Python 重写内部结构耦合。

## 4. Web UI 设计

### 4.1 技术选择

- React + TypeScript + Vite
- React Router 负责页面路由
- TanStack Query 负责请求缓存、刷新和 mutation 后失效更新
- CSS/Tailwind 方案在实施计划中选择，目标是实现紧凑暗色控制台样式

开发环境中，Vite 将 `/api` 代理到 `http://127.0.0.1:8000`。因此 UI 请求使用相对路径 `/api/...`，无需服务端增加 CORS 或静态文件承载。

### 4.2 交互风格

界面采用紧凑、暗色、信息优先的控制台风格：

- 左侧导航只包含组织选择、`Issues`、`Approvals`、`Organizations`
- 主页面为列表优先布局，不在一期实现三栏详情联动
- 状态与优先级使用稳定颜色和文本标签同时表达，避免仅依赖颜色
- mutation 提供禁用态、错误提示与刷新行为，不假设服务端支持乐观并发控制

### 4.3 页面与路由

| 路由 | 页面职责 | 现有 API |
| --- | --- | --- |
| `/` | 按已有组织进入首个组织的 Issue 列表；无组织时引导创建 | `GET /api/orgs` |
| `/organizations` | 组织列表与创建入口 | `GET/POST /api/orgs` |
| `/organizations/:orgId` | 组织基本信息编辑 | `GET/PATCH /api/orgs/{orgId}` |
| `/orgs/:orgId/issues` | 默认工作页，按状态分组展示问题、筛选、新建 | `GET/POST /api/orgs/{orgId}/issues` |
| `/issues/:issueId` | 问题详情、字段更新、评论、review decision | `GET/PATCH /api/issues/{id}` 及 comment/review endpoints |
| `/orgs/:orgId/approvals` | 审批列表，默认突出 pending 项 | `GET /api/orgs/{orgId}/approvals` |
| `/approvals/:approvalId` | 审批详情与决策动作 | approval detail/action endpoints |

### 4.4 Issues 默认工作台

Issues 是进入组织后的默认落点，采用已选定的列表优先结构：

- 顶部显示当前组织、创建问题按钮、基础筛选控件。
- 列表按 `status` 分组，展示 `identifier`、标题、优先级、状态和更新时间。
- 一期筛选只提供当前接口支持且立即有价值的 `status`、`assigneeAgentId`、`projectId`、`originKind`、`originId`。
- 点击列表项进入独立详情页面，不在列表页嵌入详情面板。

`projectId` 与 `assigneeAgentId` 目前仅按原始值筛选和显示，不制作项目或代理详情跳转，因为对应资源接口尚未纳入当前实现。

### 4.5 Issue 详情

Issue 详情页包含：

- 标题、描述、状态、优先级及当前 API 返回的关联字段
- 编辑操作：通过 `PATCH /api/issues/{id}` 更新现有可编辑字段
- 评论时间线：列表与新增评论
- Review 操作区：仅在可审阅状态下提供 `approve`、`request_changes`、`blocked`、`needs_followup`

提交 review 后重新拉取详情和评论；若服务端返回 `422` 或 `403`，页面直接显示服务端错误信息，不在客户端重建状态规则。

### 4.6 Approval 页面

Approval 列表支持 status 筛选，并将 `pending` 作为默认重点。详情页：

- 展示脱敏后的 payload、状态、申请主体与决策信息
- 支持 create、approve、reject、request revision、resubmit 对应动作
- 决策后回到更新后的审批详情；服务端触发的关联 issue 恢复由刷新 issue 页面后反映

`resubmit` 严格沿用现有 actor 规则：本地 board 创建的审批可在本地调试模式下重提；存在 `requestedByAgentId` 的审批仅允许对应 agent 重提。UI 与 CLI 不新增身份模拟能力，服务端拒绝时直接展示错误。

不实现审批评论或审批与 issue 的额外链接视图，因为当前 API 未提供这些读取/写入接口。

## 5. Python CLI 设计

### 5.1 运行方式

一期不修改根目录 `pyproject.toml` 注册入口，因此从仓库根目录运行：

```powershell
python -m cli --help
```

CLI 默认请求 `http://127.0.0.1:8000`，所有业务命令支持：

```text
--api-base <url>    覆盖默认服务地址
--json              输出可供脚本处理的 JSON
```

CLI 不启动服务、不打开浏览器、不维护 auth token 或上下文 profile。服务应由用户事先启动，并在本地调试模式下配置 actor。

### 5.2 命令面

```text
python -m cli organization list
python -m cli organization get <org-id>
python -m cli organization create --name <name>
python -m cli organization update <org-id> [fields]

python -m cli issue list --org-id <id> [filters]
python -m cli issue get <issue-id>
python -m cli issue create --org-id <id> --title <title> [fields]
python -m cli issue update <issue-id> [fields]
python -m cli issue comment <issue-id> --body <text>
python -m cli issue review <issue-id> --decision <decision> [--note <text>]

python -m cli approval list --org-id <id> [--status <status>]
python -m cli approval get <approval-id>
python -m cli approval create --org-id <id> --type <type> --payload-json <json> [--issue-ids <csv>]
python -m cli approval approve <approval-id> [--decision-note <text>]
python -m cli approval reject <approval-id> [--decision-note <text>]
python -m cli approval request-revision <approval-id> [--decision-note <text>]
python -m cli approval resubmit <approval-id> [--payload-json <json>]
```

### 5.3 输出与错误

- 默认输出适于终端阅读的单行列表和字段摘要。
- `--json` 原样打印 API 返回 JSON，不改字段名或状态值。
- 网络错误、非 JSON 响应和 HTTP 错误统一转为非零退出码。
- HTTP 错误正文中的 `detail` 在终端中直接展示，便于识别 actor 未启用、作用域拒绝和字段校验失败。

## 6. 数据流与运行方式

本地使用顺序保持简单：

```powershell
$env:OCTOPUS_LOCAL_TRUSTED = "1"
$env:OCTOPUS_AUTO_MIGRATE = "1"
uv run server
```

在另一终端运行 UI 开发服务或 CLI：

```powershell
# UI：由 ui/ 中的开发命令启动，/api 代理到 127.0.0.1:8000

# CLI
python -m cli organization list
```

数据流如下：

```text
Browser UI ── /api proxy ──┐
                            ├── FastAPI at 127.0.0.1:8000 ── existing database
Python CLI ── HTTP ─────────┘
```

## 7. 测试策略

由于一期不更改服务端代码，现有服务端测试只作为回归确认，不新增服务端业务测试。

### 7.1 UI

- API client 单元测试：路径、query string 和请求 payload。
- 页面交互测试：组织空态、Issue 列表分组、Issue 评论/review 提交、Approval 决策。
- 测试中 mock HTTP 请求，确保只调用现有 API。
- 构建和 TypeScript 类型检查作为交付验证。

### 7.2 CLI

- HTTP client 测试：base URL、JSON payload、错误映射。
- 命令测试：参数解析、文本输出、`--json` 输出、非零错误退出。
- 使用 mock HTTP server 或传输 mock，不依赖真实数据库。

### 7.3 回归验证

实施完成后执行：

- 新增 UI 的类型检查、测试与构建
- 新增 CLI 的测试
- 仓库现有四步 Python 验证，确认新增目录未影响服务端基线

## 8. 实施顺序建议

1. 建立 `ui/` 前端骨架与 API client，完成组织选择和 Issues 列表。
2. 完成 Issue 详情、评论与 review decision。
3. 完成 Approval 列表、详情与决策操作。
4. 建立 `cli/` HTTP client 与基础输出设施。
5. 按 organization、issue、approval 顺序补齐 CLI 命令。
6. 补齐 UI/CLI 测试与联调说明。

一期完成标准是：在不修改现有服务端实现的前提下，用户能够从浏览器和 Python CLI 完成现有 Organization、Issue/Review、Approval 工作闭环。
