# Skills Guide

本文说明 Octopus 项目里三类“技能”的区别和使用方式：

- `.agents/skills`：开发期助手技能
- 组织技能：Octopus 产品里的组织级技能库
- 智能体技能：某个具体智能体实际启用并安装的技能

这三类技能名字相似，但使用者、存放位置、生命周期和影响范围不同。

## 一句话区别

```text
.agents/skills
= 开发 Octopus 时，给 Codex/Claude/OpenCode 这类开发助手看的工作手册

组织技能
= Octopus 产品里，一个组织可用的技能目录

智能体技能
= 某个 agent 从组织技能里选中并实际带入运行时的技能
```

## 对比表

| 类型 | 谁使用 | 存放位置 | 是否进入产品业务 | 主要作用 |
| --- | --- | --- | --- | --- |
| `.agents/skills` | 开发本项目的 Codex/Claude/OpenCode | `.agents/skills/**/SKILL.md` | 否 | 约束开发助手如何 review、调试、发版、优化 UI、维护本地环境 |
| 组织技能 | Octopus server / 组织管理员 / UI 组织技能页 | 数据库 `organization_skills`，来源可包含 `server/skills/bundled` | 是 | 表示一个组织有哪些技能可选 |
| 智能体技能 | Octopus 中某个具体 agent 的 runtime | agent 配置和 runtime materialization 后的 `AGENT_HOME/skills/<slug>/SKILL.md` | 是 | 表示某个 agent 实际启用了哪些技能，并在运行时加载 |

## `.agents/skills`

`.agents/skills` 是项目开发期使用的技能目录。

它服务的是“正在开发 Octopus 的助手”，不是 Octopus 产品里的普通用户或业务智能体。

典型用途：

- 用户要求 review 代码、review Codex session 或做 PM review
- 用户要求调试 agent run transcript
- 用户要求发版、检查 release、修 npm dist-tag
- 用户要求 UI polish、截图验证、mock/demo data
- 用户要求停止或重启本地 dev runtime

示例：

```text
用户：review 一下这个 codex session
使用：.agents/skills/maintainer/codex-session-product-reviewer-maintainer/SKILL.md

用户：为什么这个 run 失败
使用：.agents/skills/maintainer/debug-run-transcript-maintainer/SKILL.md

用户：发版
使用：.agents/skills/maintainer/release-maintainer/SKILL.md
```

### 中文副本

同级的 `SKILL.zh-CN.md` 是中文阅读副本，方便人理解。

运行时仍以英文 `SKILL.md` 为主。中文副本不应该改变技能触发逻辑，也不应该作为唯一运行时来源。

## 组织技能

组织技能是 Octopus 产品里的组织级技能库。

它回答的问题是：

```text
这个组织有哪些技能可以给智能体使用？
```

组织技能可以来自多个来源：

- server 内置技能：`server/skills/bundled`
- 组织本地创建的技能
- 后续规划中的外部导入技能
- 后续规划中的社区或插件来源技能

当前组织技能主要通过 server API 暴露给 UI：

```text
GET /api/orgs/{orgId}/skills
GET /api/orgs/{orgId}/skills/{skillId}
GET /api/orgs/{orgId}/skills/{skillId}/files?path=SKILL.md
```

UI 的“组织-技能”页面展示的是这一层。

组织技能不是某个 agent 已经启用的技能，它只是组织层面的候选库。

## 智能体技能

智能体技能是某个具体 agent 从组织技能中选择并启用后的结果。

它回答的问题是：

```text
这个 agent 实际运行时会带哪些技能？
```

一个组织可以有很多技能，但某个 agent 只会启用其中一部分。

示例：

```text
组织有 10 个技能：
- control-plane
- skill-creator
- create-agent
- create-plugin
- conversation-to-skill
- ...

CEO agent 实际启用：
- control-plane
- skill-creator
```

当 agent 运行时，server/runtime 会把启用的技能 materialize 到该 agent 的 runtime home：

```text
AGENT_HOME/skills/<slug>/SKILL.md
```

不同 runtime 的安装位置可能不同，但语义相同：把 agent 需要的技能放进该 agent 运行时可读取的位置。

## 数据流

整体关系可以理解为：

```text
.agents/skills
  只给开发助手使用
  不进入 Octopus 产品技能库

server/skills/bundled
  ↓ seed / sync
组织技能
  ↓ enable / sync
智能体技能
  ↓ materialize
AGENT_HOME/skills/<slug>/SKILL.md
```

## 常见误区

### 误区 1：`.agents/skills` 会出现在组织技能页

不会。

`.agents/skills` 是开发期助手技能目录，不是 server 的组织技能来源。

组织技能页读取的是 server API 和数据库里的组织技能数据。

### 误区 2：组织技能等于智能体技能

不等于。

组织技能是“可选库”，智能体技能是“某个 agent 已启用的技能”。

```text
组织技能：组织有哪些可选技能
智能体技能：这个 agent 选了哪些技能
```

### 误区 3：中文 skill 文件会影响运行时

默认不影响。

`SKILL.zh-CN.md` 只是中文说明副本。运行时仍应使用 `SKILL.md`，避免中文副本和英文逻辑产生偏差。

### 误区 4：`server/skills/bundled` 是开发助手技能

不是。

`server/skills/bundled` 是 Octopus 产品内置技能来源，会进入组织技能和智能体技能流程。

## 什么时候改哪里

### 修改 `.agents/skills`

当你想改变“开发助手如何协作开发 Octopus”时修改这里。

例如：

- 改 Codex session review 流程
- 改发版检查流程
- 改 UI polish 工作方式
- 改本地 dev 停止/启动维护流程

### 修改 `server/skills/bundled`

当你想改变“Octopus 产品默认给组织提供哪些内置技能”时修改这里。

例如：

- 增加一个默认内置技能
- 调整组织技能页里可同步的内置技能
- 改 agent runtime 实际可安装的技能内容

### 修改组织技能 API / 数据库

当你想改变“组织如何管理技能库”时修改 server 的组织技能能力。

例如：

- 创建组织技能
- 编辑组织技能文件
- 扫描技能目录
- 导入外部技能
- 管理组织技能来源和状态

### 修改智能体技能能力

当你想改变“某个 agent 如何选择、同步、安装技能”时修改 agent skill / runtime materialization 相关能力。

例如：

- agent 启用某个组织技能
- agent 同步 desired skills
- 把技能物理安装到 Codex/Claude/OpenCode runtime home
- 记录 installed / available / enabled 状态

## 调试建议

如果组织技能页为空，优先检查：

```text
GET /api/orgs/{orgId}/skills
```

如果某个 agent 运行时没有加载技能，优先检查：

```text
该 agent 是否启用了该组织技能
runtime materialization 是否把技能写入 AGENT_HOME/skills/<slug>/SKILL.md
```

如果 Codex 开发过程中没有触发某个工作流，才检查：

```text
.agents/skills/**/SKILL.md
```

## 运行路径概念

技能调试时还会遇到几个容易混淆的路径概念：

- `cwd`
- 工作区
- `CODEX_HOME`
- `AGENT_HOME`

它们不是同一个东西。

## `cwd`

`cwd` 是当前进程的 working directory。

在开发 Octopus 时，通常是当前 repo 根目录：

```text
D:\coding\octopus
```

它回答的问题是：

```text
当前命令从哪里执行？
```

例如你运行：

```powershell
uv run server
```

如果当前目录是 `D:\coding\octopus`，那 server 里用 `Path.cwd()` 解析出来的就是这个 repo 根目录。

当前项目里很多本地路径都和 `cwd` 有关，例如：

```text
.agents/skills
server/skills/bundled
.octopus/organizations
```

如果 `cwd` 不对，服务端可能找不到预期的本地资源。

## 工作区

“工作区”在 Octopus 产品语境里通常指组织或 agent 运行时使用的文件工作区。

它回答的问题是：

```text
Octopus 运行中的组织、项目、agent 把共享文件、计划、产物、技能放在哪里？
```

当前 server 里组织技能工作区类似：

```text
.octopus/organizations/<org-id>/workspaces/skills/<slug>
```

这属于 Octopus 产品内部管理的 workspace 数据，不等同于 repo 根目录，也不等同于 `CODEX_HOME`。

工作区常用于：

- 组织本地技能
- agent 运行产物
- 共享计划
- 组织资源和文件
- runtime materialization 的中间来源

## `CODEX_HOME`

`CODEX_HOME` 是 Codex runtime 自己的 home 目录。

它回答的问题是：

```text
Codex 这个运行时从哪里读取自己的配置、状态和技能？
```

Codex-local agent 运行时 materialize 技能时，目标通常会落到类似：

```text
CODEX_HOME/skills/<slug>/SKILL.md
```

注意：

```text
CODEX_HOME != cwd
CODEX_HOME != .agents/skills
CODEX_HOME != 组织工作区
```

`.agents/skills` 是开发期助手技能来源；`CODEX_HOME/skills` 是 Codex runtime 实际运行时读取的技能安装位置。

## `AGENT_HOME`

`AGENT_HOME` 是更通用的 agent runtime home 概念。

它回答的问题是：

```text
当前这个 agent 运行时自己的 home 在哪里？
```

不同 runtime 可以有不同 home：

```text
Codex local  -> CODEX_HOME
Claude local -> Claude runtime home
OpenCode     -> OpenCode runtime home
```

文档里写 `AGENT_HOME/skills/<slug>/SKILL.md`，通常是泛指：

```text
把 agent 启用的技能安装到该 agent runtime 能读取的位置
```

对 Codex 来说，这个位置通常就是：

```text
CODEX_HOME/skills/<slug>/SKILL.md
```

## 路径关系图

```text
cwd
= 当前命令执行目录
= D:\coding\octopus

  ├─ .agents/skills
  │  └─ 开发期助手技能，不进入 Octopus 产品技能库
  │
  ├─ server/skills/bundled
  │  └─ Octopus 产品内置技能来源
  │
  └─ .octopus/organizations/<org-id>/workspaces/skills
     └─ Octopus 组织本地技能工作区

CODEX_HOME
= Codex runtime 自己的 home

  └─ skills/<slug>/SKILL.md
     └─ Codex agent 实际运行时读取的已安装技能

AGENT_HOME
= 泛指某个 agent runtime 的 home
= Codex/Claude/OpenCode 各自可不同
```

## 常见路径误区

### 误区 1：在 repo 下有 `.agents/skills`，Codex agent 就会自动使用

不一定。

`.agents/skills` 是当前开发助手可用的项目技能目录。Octopus 产品里的 Codex-local agent 是否使用某个技能，要看组织技能是否同步、该 agent 是否启用、runtime materialization 是否写入 `CODEX_HOME/skills`。

### 误区 2：`cwd` 就是 `CODEX_HOME`

不是。

`cwd` 是命令执行目录。`CODEX_HOME` 是 Codex runtime 的 home。

开发 server 时 `cwd` 常是 repo 根目录；运行 Codex agent 时 `CODEX_HOME` 可能是由 runtime 为该 agent 准备的独立目录。

### 误区 3：组织技能文件直接等于 runtime 技能文件

不等于。

组织技能是 source/catalog。runtime 技能文件是 materialized/install 结果。

```text
组织技能
  ↓ agent 启用
  ↓ runtime materialize
CODEX_HOME/skills/<slug>/SKILL.md
```

如果组织技能页能看到技能，但 agent 对话时技能没生效，要检查 materialization，而不是只检查组织技能 API。

## 排查顺序

### 页面上看不到组织技能

检查：

```text
GET /api/orgs/{orgId}/skills
server/skills/bundled
organization_skills 表
```

### agent 已启用技能但运行时没生效

检查：

```text
agent desired skills
runtime materialization 日志
CODEX_HOME/skills/<slug>/SKILL.md
```

### 开发助手没有按某个流程工作

检查：

```text
.agents/skills/**/SKILL.md
当前对话是否触发了该 skill
```
