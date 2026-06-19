# Step 24: Agent Memory

状态：开发中；已在 `step-24-agent-memory` 分支实现 runtime memory contract、专用 memory/life API 和 Agent Memory UI。

## 背景

当前 agent workspace 已能 materialize `instructions`，runtime managed HOME 也能按 runtime type 准备执行目录，但 agent 长期记忆仍主要停留在说明文件初始化和运行时读取层面。上游项目存在 `MEMORY.md`、`memory/`、`life/` 与 `para-memory-files` 相关约定，说明“长期说明”和“运行后可持续写入的记忆文件”需要分层实现。

## 目标

补齐 agent 个人记忆能力，使 agent 能在自己的长期 home 中持久化和读取记忆，同时保持 runtime managed HOME 只作为单次或单类 runtime 的执行 home，不把临时运行配置误写成长期记忆。

## 上游证据

开发前必须优先核对：

- `D:\coding\rudder\packages\agent-runtime-utils\src\server-utils.prompts.ts`
- `D:\coding\rudder\server\resources\bundled-skills\para-memory-files\SKILL.md`
- `D:\coding\rudder\server\src\onboarding-assets\**\MEMORY.md`
- `D:\coding\rudder\server\src\onboarding-assets\**\HEARTBEAT.md`
- `D:\coding\rudder\doc\plans\2026-04-30-agent-memory-instructions.md`

## 范围

- 明确 `AGENT_HOME` 的长期记忆目录契约：
  - `instructions/MEMORY.md`：启动时可被 runtime prompt 引用的长期记忆入口。
  - `memory/YYYY-MM-DD.md`：按日期追加的运行记忆、观察、决策记录。
  - `life/`：面向长期实体、偏好、项目背景或稳定事实的结构化文件目录。
- 补齐 memory/life 的目录创建、路径安全、读写策略和初始化策略。
- 将 memory 写入能力接到 runtime prompt/tool guidance，使 agent 知道何时记录、记录到哪里、哪些内容不应记录。
- 对齐 `para-memory-files` skill 的使用边界：它是 memory 文件读写方法说明，不等同于 Octopus 产品 DB 的 `agent_enabled_skills`。
- 让 workspace/file browser 能看见 agent home 中的 memory/life 文件，便于开发者调试。
- 增加 contract/workflow tests，覆盖新建 agent、运行后写入、重启后保留、跨 agent 隔离和路径逃逸拒绝。

## 不做

- 不做向量数据库、语义检索或自动总结系统。
- 不把所有 `memory/`、`life/` 文件自动塞进每次 prompt；默认只稳定引用 `instructions/MEMORY.md`，其余按 skill/tool guidance 主动读取。
- 不做跨 agent 共享记忆或组织级全局记忆。
- 不把 runtime managed HOME 当作长期记忆源；managed HOME 可以 mount/copy 长期来源，但写回策略必须明确。

## 验收

- 新建 agent 后，长期 home 能得到稳定的 `instructions/MEMORY.md`、`memory/` 和 `life/` 目录。
- runtime 执行时能获得明确 memory guidance，并能把需要保留的内容写入长期 home。
- 同一个 agent 的多次 run 能复用同一份长期 memory；不同 runtime type 的 managed HOME 不会分裂长期记忆。
- 不同 agent 的 memory 互相隔离；非法相对路径、绝对路径和越权 workspace 访问被拒绝。
- UI/文件列表能显示 memory/life 目录，便于确认记忆是否真实落盘。

## 交付记录

### 2026-06-08

- Runtime prompt 会自动加载长期 home 下 `instructions/MEMORY.md` 作为 tacit memory。
- Runtime prompt 不会自动注入 `memory/` 或 `life/` 全目录内容，避免把日记和长期结构化资料无界塞进上下文。
- Agent runtime config 的 `_octopus` 上下文会暴露 `agentHome`、`agentInstructionsDir`、`agentMemoryDir`、`agentLifeDir`、`agentSkillsRootPath`。
- Local runtime env 支持从 workspace context 或 `_octopus` fallback 注入 `AGENT_HOME`、`OCTOPUS_AGENT_MEMORY_DIR`、`OCTOPUS_AGENT_LIFE_DIR` 等路径。
- Codex/Claude/OpenCode managed HOME 不再默认占用 `AGENT_HOME`；`HOME/USERPROFILE` 仍用于 runtime CLI 凭据、缓存和 profile 隔离。
- 已补 contract/workflow tests 覆盖 tacit memory 加载、lazy memory/life、runtime env fallback、managed HOME 与长期 `AGENT_HOME` 分离。
- 新增 agent-scoped memory/life 文件 API：
  - `GET /api/agents/{id}/memory/files?layer=memory|life&path=...`
  - `GET /api/agents/{id}/memory/file?layer=memory|life&path=...`
  - `PUT /api/agents/{id}/memory/file`
  - `DELETE /api/agents/{id}/memory/file?layer=memory|life&path=...`
- Agent 详情页新增“记忆”tab，可在 `memory` daily notes 和 `life` 长期目录之间切换，并支持创建、读取、编辑、删除文件。
- 已补 API contract tests 覆盖 memory/life 写读列删、nested life 文件、非法路径和非法 layer 拒绝；已补 Agent 页面测试覆盖 Memory UI 基本交互。
