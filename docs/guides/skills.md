# Skills Guide

本文说明 Octopus 产品内的技能分几层存放、各层怎么管理，以及启用后如何进入不同运行时原生的 skills 目录。

## 四层技能

先区分两类目录：

```text
workspace skills 目录
= Octopus 长期保存技能来源文件的地方
= 例如 workspaces/skills、workspaces/agents/<agentId>/skills

RUNTIME_SKILL_HOME
= 文档里的统一术语，不是固定环境变量
= 当前 agent 在当前 runtime 下最终可加载的技能目录
= 具体路径由 runtime adapter 决定

# codex    ~/.octopus/instances/default/organizations/<orgId>/codex-home/agents/agent-demo/skills
# claude   临时注入目录，例如 `%TEMP%/octopus-claude-skills-xxxx/.claude/skills
# opencode ~/.octopus/instances/default/organizations/<orgId>/opencode-home/home/.claude/skills
```

也就是说，四层技能目录解决“技能源文件长期放在哪里、谁能管理”；`RUNTIME_SKILL_HOME` 解决“这次运行时到底从哪里加载”。

| 层级 | 谁能用 | 典型位置 | 是否通常在 `.octopus` 下 |
| --- | --- | --- | --- |
| 内置技能 | 所有组织可同步/可选 | `server/skills/bundled/<slug>/SKILL.md` | 否 |
| 社区预置技能 | 所有组织可同步/可选 | `server/skills/community/<slug>/SKILL.md` | 否 |
| 组织技能 | 当前组织内多个 agent 可选 | `OCTOPUS_HOME/instances/<instance>/organizations/<orgId>/workspaces/skills/<slug>/SKILL.md` | 是 |
| agent 私有技能 | 只属于某一个 agent | `OCTOPUS_HOME/instances/<instance>/organizations/<orgId>/workspaces/agents/<agentId>/skills/<slug>/SKILL.md` | 是 |

这四层是“来源层”。它们回答的是：

```text
这个技能原始文件在哪里？
这个技能谁可以选择？
```

它们不是 runtime 最终读取的位置。runtime 最终读取的位置在后面的“整合进 `RUNTIME_SKILL_HOME`”里说明。

### 内置技能

内置技能来自源码目录：

```text
server/skills/bundled/<slug>/SKILL.md
```

用途：

- Octopus 自带的基础能力。
- 新组织可以从这里 seed / sync 到组织技能目录/清单（catalog）。

管理方式：

| 操作 | 方式 |
| --- | --- |
| 增 | 修改源码，新增 `server/skills/bundled/<slug>/SKILL.md` |
| 删 | 修改源码移除；已同步到组织的记录需要迁移或标记不可用 |
| 改 | 修改源码；组织侧是否同步更新取决于 sync 策略 |
| 查 | 读取源码目录，或通过组织技能 catalog 查看已同步项 |

内置技能不是用户在 UI 里直接编辑的工作区文件。

### 社区预置技能

社区预置技能来自源码目录：

```text
server/skills/community/<slug>/SKILL.md
```

用途：

- Octopus 提供的可选预置技能。
- 可作为组织技能候选，但不等于组织工作区文件。

管理方式：

| 操作 | 方式 |
| --- | --- |
| 增 | 修改源码，新增 `server/skills/community/<slug>/SKILL.md` |
| 删 | 修改源码移除；已同步到组织的记录需要迁移或标记不可用 |
| 改 | 修改源码；组织侧是否同步更新取决于 sync 策略 |
| 查 | 读取源码目录，或通过组织技能 catalog 查看已同步项 |

社区预置技能也不是所有 agent 自动启用的技能。

### 组织技能

组织技能在组织工作区里：

```text
OCTOPUS_HOME/instances/<instance>/organizations/<orgId>/workspaces/skills/<slug>/SKILL.md
```

含义：

- 当前组织公共可用的技能。
- 多个 agent 都可以选择启用。

例子：

```text
~/.octopus/instances/default/organizations/<orgId>/workspaces/skills/deep-research/SKILL.md
```

管理方式：

| 操作 | 方式 |
| --- | --- |
| 增 | UI/API 创建，或从内置/社区/外部来源导入 |
| 删 | UI/API 删除组织技能，或标记为不可用 |
| 改 | UI/API 编辑 `SKILL.md` 和相关文件 |
| 查 | `GET /api/orgs/{orgId}/skills`、组织技能页、workspace 文件浏览 |

组织技能只是“可选库”，不代表某个 agent 已经启用。

### agent 私有技能

agent 私有技能在 agent 工作区里：

```text
OCTOPUS_HOME/instances/<instance>/organizations/<orgId>/workspaces/agents/<agentId>/skills/<slug>/SKILL.md
```

含义：

- 只属于这个 agent 自己。
- 其他 agent 默认看不到，也不会使用。

例子：

```text
~/.octopus/instances/default/organizations/<orgId>/workspaces/agents/agent-demo/skills/personal-runbook/SKILL.md
~/.octopus/instances/default/organizations/<orgId>/workspaces/agents/agent-demo/skills/incident-response/SKILL.md
```

管理方式：

| 操作 | 方式 |
| --- | --- |
| 增 | agent 自己创建，或通过 agent skills API 创建 |
| 删 | agent skills API 删除，或清理 agent 工作区 |
| 改 | agent skills API 编辑，或直接修改 agent 工作区文件 |
| 查 | agent 技能页、agent skills snapshot、workspace 文件浏览 |

agent 私有技能只解决“这个 agent 自己需要的长期技能”。

## Catalog 是什么

技能目录/清单（catalog）可以理解成应用里的商品列表：

```text
列表里有这个商品
  不代表用户已经买了

catalog 里有这个技能
  不代表 agent 已经启用
```

例子：

```text
组织技能 catalog 里有 deep-research
  = UI 可以展示 deep-research，agent 可以选择它

agent 启用了 deep-research
  = 这个 agent 的 desired skills 里有对应 selectionKey

runtime 能用 deep-research
  = RUNTIME_SKILL_HOME/deep-research/SKILL.md 已经存在
```

更准确地说：

```text
catalog 不存放 SKILL.md 文件。
catalog 存放 Octopus 已知/已纳入管理的技能记录、索引和元数据。
```

也就是说：

```text
catalog = 技能索引
source directories = 技能文件来源
RUNTIME_SKILL_HOME = 当前 agent 已启用技能的运行时落点
```

概念上，catalog 可以记录内置、社区预置、组织、agent 私有等来源的信息，但不应该把四层技能文件都复制进去。

当前实现要更具体：

```text
组织技能 catalog
= 数据库里的 organization_skills 记录
= 覆盖内置、社区预置、组织本地/导入技能
= `GET /api/orgs/{orgId}/skills`

agent 私有技能索引
= 没有单独的数据库 catalog 表
= 由 agent workspace 文件系统动态派生
= `workspaces/agents/<agentId>/skills/<slug>/SKILL.md`
= `GET /api/agents/{agentId}/skills` runtime snapshot 中的 `sourceClass=agent_home`

外部发现技能
= 没有 catalog 记录
= 由 runtime home 扫描得到
= `GET /api/agents/{agentId}/skills` runtime snapshot 中的 `sourceClass=adapter_home` 或 external
```

因此，在当前代码里，组织技能页不会显示 agent 私有技能；agent 私有技能只出现在对应 agent 的技能 snapshot / 技能页里。

## 外部技能和 catalog

不是 runtime 能用的所有技能都会进入 Octopus catalog。

例如你的 Codex 使用了 `superpower` 技能，如果它安装在 Codex 自己的 runtime home 里，而不是通过 Octopus 创建、导入、同步或启用的，那么它属于：

```text
外部已安装技能 / external skill
```

它的特点是：

- Codex runtime home 能看到。
- Codex 可以使用。
- Octopus 可能能扫描到，并展示为 external。
- 但它不一定进入 Octopus catalog。
- Octopus 也不应该默认把它当成组织技能或 agent 私有技能管理。

可以这样理解：

```text
Codex runtime home 里有 superpower
= Codex 能用

Octopus catalog 里没有 superpower
= Octopus 没把它纳入组织/agent 技能管理
```

如果以后要让 Octopus 管理它，需要一个明确动作：

```text
导入到组织技能
或
接管为 agent 私有技能
```

否则它只是“runtime 外部已有能力”，不是 Octopus 管理的技能。

## 整合进 `RUNTIME_SKILL_HOME`

这套逻辑的目的就是使用不同 runtime 原生的 skill 加载方式。不是让所有 runtime 都理解 Octopus 的工作区结构。

### 整合逻辑

agent 运行前，Octopus 要做的是：

```text
四层技能来源
  ↓ catalog 展示和选择
agent desired skills / selectionKey
  ↓ 解析成 runtimeName
当前 agent 已启用的技能
  ↓ materialize / mount / copy / inject
RUNTIME_SKILL_HOME/<slug>/SKILL.md
```

这里的重点是：

- catalog 可以很多。
- 当前 agent 启用的技能应该很少。
- `RUNTIME_SKILL_HOME` 只放当前 agent 已启用的技能。
- runtime adapter 负责把技能放到该 runtime 原生会加载的位置。

例如 `deep-research` 的来源可能是：

```text
server/skills/bundled/deep-research/SKILL.md
server/skills/community/deep-research/SKILL.md
OCTOPUS_HOME/instances/<instance>/organizations/<orgId>/workspaces/skills/deep-research/SKILL.md
```

但进入 runtime 后，应该变成该 runtime 能加载的形态：

```text
RUNTIME_SKILL_HOME/deep-research/SKILL.md
```

### 不同运行时整合实例

| Runtime | `RUNTIME_SKILL_HOME` demo | Runtime 表达方式 | 完整 skill 文件路径 demo |
| --- | --- | --- | --- |
| Codex local | `~/.octopus/instances/default/organizations/<orgId>/codex-home/agents/agent-demo/skills` | `CODEX_HOME/skills/deep-research/SKILL.md` | `~/.octopus/instances/default/organizations/<orgId>/codex-home/agents/agent-demo/skills/deep-research/SKILL.md` |
| Claude local | 临时注入目录，例如 `%TEMP%/octopus-claude-skills-xxxx/.claude/skills` | `<injectedRoot>/.claude/skills/deep-research/SKILL.md` | `%TEMP%/octopus-claude-skills-xxxx/.claude/skills/deep-research/SKILL.md` |
| OpenCode local | `~/.octopus/instances/default/organizations/<orgId>/opencode-home/home/.claude/skills` | `AGENT_HOME/.claude/skills/deep-research/SKILL.md` | `~/.octopus/instances/default/organizations/<orgId>/opencode-home/home/.claude/skills/deep-research/SKILL.md` |

说明：

- `AGENT_HOME` 是便于理解的相对写法，不是所有 runtime 都有同一个固定目录。
- Claude local 当前会把技能放到临时注入目录的 `.claude/skills`，再通过 `--add-dir` 暴露给 Claude；它不等于长期 workspace 目录。
- OpenCode local 当前放到受管 home 的 `.claude/skills`。
- Codex local 使用 `CODEX_HOME/skills`。

所以不能统一写死成：

```text
AGENT_HOME/.claude/skills
```

更准确的通用说法是：

```text
runtime adapter 会把当前 agent 已启用的技能放到该 runtime 原生会加载的 skills home。
```

## 同名技能怎么处理

最终落到 `RUNTIME_SKILL_HOME` 时，同一个 `<slug>` 只能有一个结果。

比如多个来源都叫：

```text
deep-research
```

runtime 最终只能看到一个：

```text
RUNTIME_SKILL_HOME/deep-research/SKILL.md
```

上游有类似边界：

- enabled / desired skills 最终映射到 `RUNTIME_SKILL_HOME`。
- 同名 slug 不应静默选择，应该使用唯一 key，或者报 ambiguous。

Octopus 建议补齐明确优先级：

```text
agent 私有技能
  > 组织本地技能
  > 社区预置技能
  > 内置技能
  > 外部发现技能
```

这条优先级是 Octopus 应该明确实现的产品规则，不是外部 runtime 天然保证的规则。

## 会不会很多

可能会多，但正常情况下不应该多。

关键区别是：

```text
catalog
= 系统知道有哪些技能可选，可能很多

RUNTIME_SKILL_HOME
= 当前 agent 本次 runtime 最终可加载的已启用技能，应该很少
```

解决方案：

- 不把 catalog 全量塞进 `RUNTIME_SKILL_HOME`。
- 只 materialize 当前 agent 已启用的技能。
- 优先使用 symlink / mount / adapter 注入，不一定复制完整目录。
- UI 上限制或提醒一个 agent 启用过多技能。
- runtime 启动前清理已取消启用的旧技能，避免 stale skill 继续留在可加载目录。

建议产品约束：

```text
普通 agent：默认 1-5 个技能
复杂 agent：5-10 个技能
超过 10 个：UI 提醒，并要求用户确认是否真的需要
```

如果一个 agent 需要长期启用很多技能，通常说明它的职责太宽，应该考虑拆成多个更专门的 agent。

## 当前实现状态

当前 Octopus 已有：

- 组织技能 catalog。
- agent 技能启用 UI。
- runtime skill snapshot。

但 runtime materialization 还不是完整闭环。

当前 runtime skill snapshot 大致会看这些来源：

```text
config.skillsRootPath
config._octopus.organizationSkillsRootPath
server/skills/bundled
config._octopus.agentSkillsRootPath
```

注意：

- `server/skills/community` 主要用于组织技能 seed / sync，不是 runtime snapshot 直接扫描的普通根目录。
- runtime snapshot 用目录名作为技能可用 key。
- 如果 agent desired skills 保存的是 control-plane selection ref，需要在进入 runtime 前解析成 runtime name。
- runtime 应只加载该 agent 已启用的技能，不应把 catalog 里的所有技能都装进去。

## 常见报错

### `Desired skill "... " is not available`

例如：

```text
Desired skill "org:organization/<orgId>/deep-research" is not available.
```

这通常不是说系统里完全没有 `deep-research`，而是说：

```text
runtime 当前可用技能列表里，没有名为 org:organization/<orgId>/deep-research 的技能
```

更可能的问题是：

- selection ref 没有被解析成 `deep-research`。
- runtime snapshot 没扫到对应来源。
- materialization 没把 `SKILL.md` 安装到 `RUNTIME_SKILL_HOME`。

排查顺序：

```text
1. 组织技能 catalog 里是否有 deep-research
2. agent desired skills 是否保存了正确 selectionKey
3. server 是否把 selectionKey 解析到 runtime name
4. runtime snapshot 是否能看到 deep-research
5. RUNTIME_SKILL_HOME/deep-research/SKILL.md 是否存在
```

## 常见误区

### 组织技能等于 agent 已启用技能

不等于。

```text
组织技能 = 组织有哪些技能可选
agent 技能 = 这个 agent 实际启用了哪些技能
```

### 组织技能文件等于 runtime 技能文件

不等于。

组织技能是来源和目录记录；runtime 技能文件是 materialized / installed 结果。

```text
组织技能
  ↓ agent 启用
  ↓ runtime materialize
RUNTIME_SKILL_HOME/<slug>/SKILL.md
```

### `.agents/skills` 会出现在组织技能页

不会。

`.agents/skills` 是开发期助手技能目录，不是 Octopus 产品技能来源。组织技能页读取的是 server API 和数据库里的组织技能数据。

### 中文 skill 文件会影响运行时

默认不影响。

`SKILL.zh-CN.md` 只是中文说明副本。运行时仍应使用 `SKILL.md`。

## 附录：路径术语

| 术语 | 含义 |
| --- | --- |
| `cwd` | 当前进程 working directory，开发时通常是 repo 根目录 |
| `OCTOPUS_HOME` | Octopus instance 数据根目录 |
| `CODEX_HOME` | Codex runtime 自己的 home |
| `AGENT_HOME` | 泛指某个 agent runtime 的 home，具体含义由 runtime adapter 决定 |

示例关系：

```text
cwd
= D:\coding\octopus

  ├─ .agents/skills
  ├─ server/skills/bundled
  └─ server/skills/community

OCTOPUS_HOME/instances/<instance>
  └─ organizations/<orgId>/workspaces/skills

RUNTIME_SKILL_HOME
  └─ <slug>/SKILL.md
```
