# Step 11 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先给出运行、心跳运行与工作区模块的后续收口方向，不在这一步预先冻结执行面全部细节。等 Step 8 的规划与执行对象真正落地后，再收紧 run / workspace 的字段和状态边界。

## 目标

将以下执行面能力拉成完整主线：

- heartbeat runs
- runtime orchestration
- workspace lifecycle

## 本阶段范围

- `heartbeat_runs`
- run result / transcript / artifact 的最小归一化边界
- workspace allocation / release / recovery
- run 与 issue / goal / project / agent 的最小关联关系

## A 线必须先冻结的内容

- heartbeat run 的最小状态机
- runtime result / transcript 的统一语义
- workspace 分配、释放、失败恢复的最小口径
- 执行对象与业务对象的最小绑定规则

## B 线实现边界

- runtime 仍然必须通过集中 shared adapter 接入
- workspace 必须有真实生命周期，不允许只停留在字段写入
- run / workspace 故障路径必须可验证

## 验收 demo

- Demo 1：演示 heartbeat run 创建和状态推进
- Demo 2：演示 runtime 调度与结果归一化
- Demo 3：演示 workspace 分配、释放或恢复
- Demo 4：展示 workflow 测试结果

## 待确认项

- run result 与 artifact 的最小持久化边界
- workspace 失败恢复与 failover 的职责切分
- transcript 是否在本步冻结持久化格式

## 当前不冻结

- chat / storage / skill / plugin 资源细节
- observability / compatibility diff
