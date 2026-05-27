# Step 14: Runtime Adapter 执行

状态：待开发

## 任务

- 定义统一 runtime adapter contract。
- 实现首个具备上游证据的 runtime adapter。
- 将 Step 13 的 run 生命周期接入 adapter，并映射输入、输出、日志和失败语义。

## 不包含

- Workspace 生命周期与产物持久化，归 Step 15。

## 验收

- Tests 证明 runtime 差异不会改变业务 API 或 run 状态语义。
