# Step 13 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先给出技能、插件与智能体资源封装模块的方向，不在这一步提前冻结全部资源元数据。等智能体对象和执行主线真正落地后，再收紧 skill / plugin / agent resource 的真实边界。

## 目标

整合以下资源封装能力：

- bundled skills
- plugins
- agent resource bindings

## 本阶段范围

- `server/resources/skills/bundled/`
- `server/resources/plugins/`
- skill / plugin metadata
- agent resource binding
- agent 与 runtime / workspace / chat 资源的最小装配边界

## A 线必须先冻结的内容

- skill id / plugin id 与目录命名规则
- skill / plugin metadata 的最小字段语义
- agent resource binding 的最小 contract
- 资源扫描、注册、装配的最小边界

## B 线实现边界

- skill / plugin 发现与装配必须走集中 scanner / registry
- 不允许在业务逻辑里零散推导目录名或资源路径
- agent resource binding 不得隐式写死在单一 runtime
- 不在本步提前把 budget / cost / activity 治理揉进资源 metadata

## 验收 demo

- Demo 1：演示 skill 扫描与 metadata 装配
- Demo 2：演示 plugin 扫描、注册或启用
- Demo 3：演示 agent resource binding 路径
- Demo 4：展示相关测试结果

## 待确认项

- skill / plugin 是否区分启用态、可见态、默认态
- agent resource binding 是否需要版本语义
- metadata 最小字段集是否一步冻结

## 与前后步骤的边界

- 消费 Step 10 的 agent 主对象边界
- 消费 Step 11 的 runtime / workspace 挂接点
- 消费 Step 12 的 chat / artifact / storage 资源边界
- 为 Step 14 的配置、上下文和治理层提供统一资源装配入口

## 当前不冻结

- 全量 provider 资源差异
- observability / recovery / compatibility diff
