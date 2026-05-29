---
name: create-plugin
description: 使用当前 SDK/runtime 创建新的控制平面插件。用于脚手架插件包、添加示例插件或更新插件作者文档。
disable: true
---

# 创建控制平面插件

当任务是创建、脚手架化或记录控制平面插件时使用该技能。

## 基本规则

需要时先阅读：

1. `doc/plugins/PLUGIN_AUTHORING_GUIDE.md`
2. `packages/plugins/sdk/README.md`
3. `doc/plugins/PLUGIN_SPEC.md`，仅作为面向未来的上下文参考

当前 runtime 假设：

- plugin worker 是受信任代码。
- plugin UI 是同源宿主中的受信任代码。
- worker API 受 capability 控制。
- plugin UI 不由 manifest capability 沙箱隔离。
- 当前没有宿主提供的共享 plugin UI 组件库。
- 当前 runtime 不支持 `ctx.assets`。

## 推荐流程

优先使用脚手架包，不要手写样板：

```bash
pnpm --filter @control-plane/create-control-plane-plugin build
node packages/plugins/create-control-plane-plugin/dist/index.js <npm-package-name> --output <target-dir>
```

如果插件位于控制平面仓库之外，应传入 `--sdk-path`，让脚手架把本地 SDK/shared packages 快照到 `.control-plane-sdk/`。

## 输出要求

- 插件 manifest 应清晰声明能力和入口。
- worker 代码应只使用已授权 capability。
- UI 代码应遵守当前同源受信任模型。
- 示例和文档应能让后续开发者复现构建、安装和调试流程。

## 注意

该技能当前被禁用，说明它不是默认可用的运行时技能。保留中文说明仅用于产品展示和后续规划，不改变运行时行为。
