# Plugin-Compatible Agent Tools Capability Plan

状态：待实施
日期：2026-06-29
实施分支：`step-29-plugins`
归属：Step 29 Plugin Framework / Runtime Tooling

## 1. 背景

当前 Octopus 已有 Step 29 plugin framework：

- `PluginManifest.tools` 能声明 plugin-contributed RPC 工具。
- `PluginToolDispatcher` 能发现 ready plugin 的 tools，并通过 worker 或内置 worker 执行。
- `plugin-git` 已作为 bundled plugin 暴露 `git.status`、`git.diff`、`git.commit`、`git.push` 等 RPC 工具。
- local runtime 当前还硬编码准备了两个 agent home shim：
  - `control-plane` / `control-plane.cmd`
  - `git` / `git.cmd` Git 写策略包装器

这里的问题不是“缺一套新的 Tool Registry”，而是工具能力被拆成了两套：

```text
plugin tools:
  通过 PluginManifest.tools + PluginToolDispatcher 暴露 RPC 工具

runtime managed bin:
  通过 runtime prepare 硬编码写入 agent_home/.octopus/bin
```

后续如果再单独做一套 Tool Registry，会和 plugins 重复。因此新的工具能力必须兼容并扩展现有 plugins：

```text
Plugin = 能力包
Tool Capability = Plugin 暴露给 agent/runtime 的一种能力
```

## 2. 目标

实现 plugin-compatible agent tools，使用户或系统通过 plugin 配置工具后，agent 在运行时能稳定获得、理解、受策略约束地使用这些工具。

最终链路：

```text
安装/启用 plugin
  -> plugin manifest 声明 tools / runtimeTools / mcp / env / policy
  -> server 按 org/project/agent/runtime/workspace 解析可用 capabilities
  -> runtime prepare 安装或生成 agent_home/.octopus/bin 入口
  -> PATH / env / MCP / prompt 注入
  -> agent 使用工具
  -> 策略拦截、执行结果和失败原因可审计
```

## 3. 非目标

- 不新建一套和 plugins 并列的 Tool Registry。
- 不要求用户手动修改 `agent_home/.octopus/bin`。
- 不默认把所有系统 PATH 命令纳入 Octopus 管理。
- 不让 plugin tool 绕过 workspace、sandbox、Git write policy 或 approval 边界。
- 不在首版实现插件 marketplace、远程工具包分发或生产级安全沙箱。
- 不把 MCP、binary 下载器、secret 管理一次性做完；这些可以作为后续 capability 类型扩展。

## 4. 术语

### Plugin

已存在的 Step 29 插件实体。它负责安装、启用、配置、状态、worker、UI、job、webhook、日志等生命周期。

### RPC Tool

当前已有的 plugin tool：

```json
{
  "name": "git.status",
  "displayName": "查看状态",
  "description": "查看当前 runtime workspace 仓库状态。",
  "parametersSchema": { "type": "object" }
}
```

它通过 `PluginToolDispatcher.execute_tool()` 进入 plugin worker 或内置 worker。

### Runtime Tool

需要安装或暴露到 agent runtime 环境的工具，例如：

```text
agent_home/.octopus/bin/git.cmd
agent_home/.octopus/bin/control-plane.cmd
agent_home/.octopus/bin/my-tool.cmd
```

它通常通过 shell 命令被 agent 调用。

### Capability

Plugin 对外提供的能力声明。当前已有 `agent.tools.register` 这种粗粒度 capability，后续需要补充更具体的 runtime tool capability schema。

## 5. 设计原则

1. plugins 是唯一扩展入口

   新工具能力必须挂在 plugin manifest 上，不能绕开 plugin framework 自建 registry。

2. tools 分层表达

   `tools` 继续表示 RPC tools。新增 `runtimeTools` 表示需要进入 agent runtime 的命令、shim、script、system command。

3. 内置工具也走 plugin model

   `git wrapper` 和 `control-plane` 不再只是 runtime 硬编码概念，应映射为 builtin plugin runtime tools。

4. prepare 是唯一落地入口

   `agent_home/.octopus/bin` 是生成产物目录，不是用户配置入口。所有工具必须由 runtime prepare 根据 plugin capabilities 生成。

5. 策略先于执行

   工具是否可用、是否只读、是否需要 approval、是否可访问 workspace/network/secrets，必须在安装、prompt 注入和执行时统一体现。

6. 不破坏现有 plugin tools

   当前 `PluginManifest.tools`、`PluginToolDispatcher` 和 bundled plugin fixtures 必须保持兼容。

## 6. Manifest 扩展方案

保留现有字段：

```json
{
  "capabilities": ["agent.tools.register"],
  "tools": []
}
```

新增可选字段：

```json
{
  "runtimeTools": [
    {
      "name": "git",
      "displayName": "Git CLI",
      "description": "Git command wrapper controlled by Octopus policy.",
      "type": "shim",
      "commandName": "git",
      "platforms": ["windows", "linux", "darwin"],
      "install": {
        "kind": "builtin",
        "builtinKey": "git-policy-wrapper"
      },
      "policy": {
        "filesystem": "workspace",
        "git": "policy_controlled",
        "network": false,
        "requiresApproval": false
      },
      "prompt": {
        "usage": "Use git for repository inspection. Mutating commands may be blocked by OCTOPUS_GIT_WRITE_POLICY.",
        "limitations": [
          "Do not bypass the wrapper with an absolute Git path.",
          "Respect read_only policy."
        ]
      }
    }
  ]
}
```

### 6.1 runtime tool types

首版支持：

| type | 含义 | 示例 |
| --- | --- | --- |
| `builtin` | Octopus 内置工具，由代码生成 | `control-plane` |
| `shim` | 包装真实命令的入口 | `git` wrapper |
| `system_command` | 系统 PATH 已存在命令，只做检测和提示 | `rg`、`node` |
| `script` | Octopus 根据 manifest 写入脚本 | `my-tool.cmd` |

后续扩展：

| type | 含义 |
| --- | --- |
| `mcp` | 注入 MCP server 配置，不写入 bin |
| `downloaded_binary` | 下载或解压到 managed tools cache |
| `containerized` | 通过容器或真正 sandbox 执行 |

### 6.2 capability 枚举

新增 capability：

```text
agent.runtimeTools.register
```

保留：

```text
agent.tools.register
```

区别：

```text
agent.tools.register:
  声明 RPC tools，经 PluginToolDispatcher 调用。

agent.runtimeTools.register:
  声明 runtime environment tools，经 runtime prepare 安装到 agent 环境。
```

## 7. 内置工具兼容映射

### 7.1 Git

当前已有：

```text
server/plugins/bundled/plugin-git/manifest.json
packages/runtimes/git_policy.py
packages/runtimes/local_skills.py 中的 git shim 生成逻辑
```

目标：

```text
plugin-git
  tools:
    git.status / git.diff / git.log / git.commit / git.push ...
  runtimeTools:
    git
```

RPC tool 和 CLI wrapper 都归属 `plugin-git`，但职责不同：

```text
git.status RPC:
  结构化工具调用，走 worker/dispatcher。

git CLI wrapper:
  agent shell 中普通 git 命令的安全入口，走 agent_home/.octopus/bin/git。
```

### 7.2 Control Plane

当前 control-plane 主要作为 skill/CLI shim 注入。

目标新增 builtin plugin：

```text
builtin.control-plane
  runtimeTools:
    control-plane
```

这不要求把 control-plane skill 立即迁移成 plugin，但 runtime tool 的安装、prompt 注入和审计应走同一 manifest/capability 模型。

## 8. 服务端解析流程

新增或扩展服务：

```text
server/plugins/runtime_tools.py
```

职责：

- 查询 ready plugins。
- 过滤声明了 `agent.runtimeTools.register` 的 plugins。
- 读取 `runtimeTools`。
- 按 org/project/agent/runtime/workspace 解析作用域。
- 合并 builtin runtime tools。
- 输出给 runtime context。

输出结构建议：

```json
{
  "runtimeTools": [
    {
      "pluginId": "plugin-id",
      "pluginKey": "git.local",
      "name": "git",
      "commandName": "git",
      "type": "shim",
      "install": {},
      "policy": {},
      "prompt": {}
    }
  ]
}
```

注入位置：

```text
WorkspaceService.prepare_runtime_context_*
  -> runtime_context["_octopus"]["runtimeTools"]
  -> RuntimeExecutionContext.config / workspace / env
```

## 9. Runtime Prepare 流程

新增：

```text
packages/runtimes/managed_tools.py
packages/runtimes/tool_installer.py
```

替换当前硬编码调用：

```text
ensure_control_plane_cli_shim()
ensure_git_policy_shims()
```

目标流程：

```text
prepare_managed_runtime_tools(context, env, home)
  -> ensure agent_home/.octopus/bin
  -> install builtin control-plane
  -> install builtin git wrapper when enabled
  -> install plugin-declared runtimeTools
  -> prepend bin dir to PATH
  -> return installed tool manifest
```

兼容要求：

- 第一阶段可以保留 `ensure_control_plane_cli_shim()` 函数名，但内部改为调用统一 installer。
- `claude_local`、`opencode_local`、`codex_local`、`openclaw_local` 都必须走同一入口。
- 如果 runtime context 没有 `runtimeTools`，仍然安装当前默认内置工具，保持现有行为。

## 10. Prompt / Tool Capabilities 注入

扩展：

```text
packages/runtimes/tool_capabilities.py
```

注入内容：

```text
Available plugin-provided runtime tools:
- git: Git CLI wrapper from plugin-git. Policy: read_only when OCTOPUS_GIT_WRITE_POLICY=read_only.
- control-plane: Octopus coordination CLI.
- my-tool: Provided by plugin example. Scope: project.
```

要求：

- 不只列工具名，还要列用途、限制和策略。
- read-only / approval / network / secret 限制必须进入 prompt。
- 被禁用或安装失败的工具不能作为可用工具提示。
- RPC tools 和 runtime tools 要区分展示，避免 agent 误以为 shell 可直接调用 `git.status`。

## 11. 权限与策略

首版策略字段：

```json
{
  "filesystem": "none | workspace_read | workspace_write",
  "git": "none | read_only | policy_controlled | write",
  "network": false,
  "secrets": "none | refs_only | read",
  "requiresApproval": false
}
```

规则：

- 无 issue heartbeat 默认只能获得 read-only 工具。
- `OCTOPUS_GIT_WRITE_POLICY=read_only` 时，Git CLI wrapper 必须继续拦截写操作。
- plugin runtime tool 不能凭 manifest 自行提升权限。
- 高风险工具默认不安装，除非 plugin enabled、scope 匹配且策略允许。
- 后续接入 Step 30 access/secrets 后，secret 只传引用，不直接写入 prompt。

## 12. UI 计划

不新增独立 Tools 页面，复用 Plugins 页面。

Plugin detail 增加：

```text
Capabilities
  - RPC tools
  - Runtime tools
  - UI slots
  - Jobs
  - Webhooks
  - Required permissions
```

Runtime tools 显示：

```text
名称
命令名
类型
作用域
策略
安装状态
最近失败原因
```

Agent / Project 页面后续可只读展示“实际可用工具”，但配置入口仍在 Plugins。

## 13. 审计与诊断

需要能回答：

```text
某个 run 实际安装了哪些 runtime tools？
工具由哪个 plugin 提供？
为什么某个工具没安装？
Git checkout 为什么被拦截？
agent prompt 中暴露了哪些工具？
```

首版记录到 run/workspace operation log：

```text
runtime_tool_prepare_started
runtime_tool_installed
runtime_tool_skipped
runtime_tool_failed
runtime_tool_policy_blocked
```

后续可独立表：

```text
plugin_runtime_tool_installs
plugin_runtime_tool_events
```

## 14. 实施阶段

### 阶段 A：Schema 与兼容契约

- 扩展 `PluginManifest` TypedDict，新增 `runtimeTools`。
- 扩展 validator，校验 runtime tool 字段、type、install、policy、prompt。
- 新增 capability：`agent.runtimeTools.register`。
- 更新 bundled `plugin-git` manifest，声明 `git` runtime tool。
- 新增 builtin control-plane runtime tool manifest 或内置注入描述。
- 保持现有 `tools` 字段和 `PluginToolDispatcher` 行为不变。

验收：

- 旧 manifest 不需要 `runtimeTools` 也能通过。
- 新 manifest 能声明 runtime tools。
- 不合法 tool type、commandName、policy 会被拒绝。

### 阶段 B：Runtime Tool Resolver

- 新增服务解析 ready plugins 的 runtime tools。
- 将解析结果注入 runtime context。
- 按 org/project/agent/runtime/workspace 预留 scope 过滤接口。
- 内置 git/control-plane 走同一输出格式。

验收：

- ready plugin 的 runtime tools 出现在 runtime context。
- disabled/error plugin 不会暴露 runtime tools。
- 无 issue heartbeat 只能得到 read-only 兼容工具集。

### 阶段 C：统一 Runtime Installer

- 新增 runtime tool installer。
- 把 git wrapper 和 control-plane shim 迁移到 installer。
- local runtime 统一调用 `prepare_managed_runtime_tools()`。
- 保证 `agent_home/.octopus/bin` 继续排在 PATH 前面。

验收：

- 现有 local runtime tests 继续通过。
- `git` / `git.cmd` 和 `control-plane` / `control-plane.cmd` 仍被生成。
- 新增 script/system_command runtime tool 能被准备或明确失败。

### 阶段 D：Prompt 注入与策略

- 扩展 `tool_capabilities.py`，展示 plugin-provided runtime tools。
- 将安装成功的工具 manifest 传入 prompt 构造。
- read-only、approval、network、secret 限制进入 prompt。
- Git policy wrapper 继续执行硬拦截。

验收：

- agent prompt 中能看到 runtime tools。
- disabled/failed tools 不出现在可用工具列表。
- read-only heartbeat prompt 明确说明 Git 写操作禁止。

### 阶段 E：Plugins UI 展示

- Plugin detail 显示 runtime tools。
- Plugin list/detail 标注提供 agent tools 的 plugin。
- 显示每个 runtime tool 的 policy 和 install status。
- 不新增独立 Tools 设置页。

验收：

- 用户能在 Plugins 页面看到 plugin 提供了哪些 RPC tools 和 runtime tools。
- 用户能区分“结构化 plugin tool”和“shell 命令工具”。

### 阶段 F：审计与诊断

- 在 run operation log 中记录 runtime tool prepare 事件。
- 记录 skipped/failed/policy blocked 的原因。
- Git wrapper 拦截事件至少进入 stderr；后续接入 operation log。

验收：

- run 详情可追踪实际工具安装清单。
- 失败能定位到 plugin、tool、install step。
- Git 写操作被拦截时有清晰原因。

## 15. 需要修改的主要文件

Shared types / validators：

```text
packages/shared/constants/plugins.py
packages/shared/types/plugins.py
packages/shared/validators/plugins.py
ui/src/api/types.ts
```

Plugin services：

```text
server/plugins/registry.py
server/plugins/tool_dispatcher.py
server/plugins/runtime_tools.py        # 新增
server/plugins/bundled/plugin-git/manifest.json
```

Runtime：

```text
packages/runtimes/local_skills.py
packages/runtimes/managed_tools.py     # 新增
packages/runtimes/tool_installer.py    # 新增
packages/runtimes/tool_capabilities.py
packages/runtimes/context_env.py
packages/runtimes/git_policy.py
packages/runtimes/*_local/runner.py
```

Workspace / heartbeat context：

```text
server/services/workspaces.py
server/services/heartbeat.py
```

UI：

```text
ui/src/pages/PluginsPage.tsx
ui/src/api/plugins.ts
ui/src/api/types.ts
```

Tests：

```text
tests/contract/test_step29_plugins.py
tests/contract/test_runtime_git_policy.py
tests/contract/test_step14_runtime_adapters.py
tests/contract/test_step15_workspace_contract.py
```

## 16. 验收标准

### Plugin compatibility

- 现有 plugin manifest 继续可用。
- `tools` RPC 工具不被 runtime tool 改造破坏。
- `plugin-git` 同时提供 RPC tools 和 Git CLI wrapper runtime tool。

### Runtime install

- 每个 agent home 下自动生成应有工具。
- 不同 agent home 不共享可变工具产物。
- PATH 注入只影响 managed runtime，不修改用户系统环境。

### Policy

- 无 issue heartbeat 不会继承 server cwd。
- 无 issue heartbeat 的 Git policy 为 read-only。
- Git CLI wrapper 继续拦截 checkout、merge、push、pull、stash 等写操作。
- plugin runtime tool 不能通过 manifest 绕过策略。

### Prompt

- agent prompt 能看到已安装 runtime tools。
- prompt 清楚区分 RPC tools 和 shell/runtime tools。
- 工具权限、限制、失败处理方式可见。

### UI / diagnosis

- Plugins 页面能看到 plugin 提供的 runtime tools。
- run 日志或 operation 能显示 runtime tool prepare 结果。
- 工具缺失、安装失败、策略拦截有明确原因。

## 17. 风险与处理

### 风险：RPC tool 和 runtime tool 混淆

处理：

- manifest 字段分开：`tools` vs `runtimeTools`。
- prompt 和 UI 分开展示。

### 风险：插件提升权限

处理：

- manifest 只能声明请求，实际策略由 server 根据 org/project/agent/run/workspace 决定。
- runtime installer 只安装 resolver 输出的 allowed tools。

### 风险：再次出现隐式 cwd / Git 写问题

处理：

- runtime tool installer 不决定 cwd。
- cwd 仍由 workspace context 决定。
- 无 issue heartbeat 使用 sandbox + Git read-only policy。

### 风险：重复建设工具系统

处理：

- 不新增独立 Tool Registry。
- 所有用户可配置工具都通过 plugins/capabilities 进入。

## 18. 推荐首个实现切片

第一刀不要做 UI，先完成后端和 runtime 闭环：

```text
1. manifest 增加 runtimeTools schema
2. plugin-git 声明 git runtime tool
3. builtin control-plane 映射成 runtime tool
4. runtime resolver 输出 tools manifest
5. installer 统一生成 git/control-plane
6. prompt 注入 installed runtime tools
7. tests 覆盖 ready/disabled plugin、heartbeat read-only、local runtime PATH
```

这个切片完成后，产品语义就从：

```text
runtime 硬编码工具
```

变成：

```text
plugins 声明工具，runtime 根据 plugin capabilities 准备工具
```

后续再补 UI、审计、script/system command/MCP 类型。
