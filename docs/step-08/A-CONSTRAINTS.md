# Step 8 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先给出 Step 8 的 runtime 方向，不作为当前阶段的冻结实现约束。等 B 完成 Step 3 之后，再根据 run 相关共享契约和 workflow 需求收紧。

## 目标

建立 runtimes 适配和运行编排基础，让 server 通过统一 contract 驱动不同 runtime，而不让 runtime 差异渗透到业务语义层。

## 本阶段范围

- `packages/runtimes/shared/`
- `claude_local`
- `codex_local`
- `opencode_local`
- `openclaw_gateway`
- run 状态、结果和 transcript 归一化边界

## A 线必须先冻结的内容

- 以下内容暂不视为已冻结，只是后续收口方向：
- runtime contract
- run result / transcript 的统一语义
- server 与 runtime 的职责边界
- 不同 runtime 的能力差异如何向上层屏蔽

## B 线实现边界

- 先做最小 shared runtime adapter
- 让业务 service 只依赖 shared runtime contract
- 预留新增 runtime 的扩展位

## 验收 demo

- Demo 1：展示 server 通过统一 contract 调用某个 runtime
- Demo 2：展示 runtime 返回结果归一化后的结构
- Demo 3：展示替换 / 新增 runtime 时业务层不需要改语义代码
- Demo 4：展示 runtime 相关测试或 fake adapter 注入方式

## 待确认项

- 各 runtime 的最小能力交集
- transcript 持久化的统一格式
- timeout、cancel、retry 的统一抽象

## Step 3 完成后再补

- run 相关 shared types 的真实边界
- runtime adapter 的最小方法集
- result / transcript 归一化字段集
- fake runtime 和测试注入边界

## 当前不冻结

- 全量 provider 特性
- UI 层 runtime 展示差异
- 所有外部网关细节
