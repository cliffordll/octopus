---
name: create-agent
description: 通过 `control-plane` CLI 创建新的控制平面 agent，并遵守治理流程。用于检查 adapter 配置、比较已有 agent、草拟 prompt/config，并提交 hire request。
---

# 创建 Agent 技能

当任务是为控制平面创建或雇佣一个新的 agent 时使用该技能。

## 前置条件

你需要具备以下权限之一：

- board access。
- 组织内 `canCreateAgents=true` 的 agent 权限。

如果没有权限，需要升级给 CEO 或 board 处理。

该工作流优先使用 CLI：

- 结构化读取和变更使用 `control-plane ... --json`。
- 命令目录以 `references/cli-reference.md` 为准。
- `references/api-reference.md` 仅用于内部调试或兼容参考。
- 不要手动创建 agent 目录、说明文件或组织元数据作为降级方案。
- 如果 heartbeat 中 CLI 认证不可用，应停止并报告认证问题，不要直接修改文件系统。

## 工作流

1. 确认当前身份和组织上下文。

```sh
control-plane agent me --json
```

如果返回 `{"error":"Agent authentication required"}`，说明本次运行缺少有效 agent 认证：

- 不要在 heartbeat 中索要 `CONTROL_PLANE_API_KEY`。
- 不要降级为手动文件系统创建。
- 停止并报告本次运行缺少或注入了无效认证。

2. 查看组织中已有 agent，避免重复创建。

3. 检查目标 runtime adapter 支持的配置项。

4. 草拟新 agent 的职责、说明、runtime type、runtime config 和治理约束。

5. 按组织流程提交 hire request 或创建请求。

6. 记录结果，说明新 agent 的用途、权限、限制和后续验证方式。

## 约束

- 不要绕过治理权限。
- 不要伪造组织或 agent 身份。
- 不要手动写入控制平面内部数据作为替代创建流程。
- 创建前应尽量复用已有 agent 配置模式，避免无约束扩散。
