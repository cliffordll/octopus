# Step 7 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先给出 Step 7 的 workflow 方向，不作为当前阶段的冻结实现约束。等 B 完成 Step 3，并开始进入 read / data / workflow 交界处后，再结合 `WORKFLOW-NOTES.md` 逐步收紧。

## 目标

实现核心控制面的 mutation 语义，优先保证 `issue`、`approval`、`activity` 和基础 run 状态流转与 上游参考实现 一致。

## 本阶段范围

- `issue` create / update / delete / checkout / release / commit
- `approval` create / approve / reject / request revision / resubmit / comment
- activity 写入时机
- 关键事务边界与错误语义

## A 线必须先冻结的内容

- 以下内容暂不视为已冻结，只是后续收口方向：
- 状态流转表
- activity action 名称和触发时机
- 关键错误码与拒绝语义
- 事务边界与副作用先后顺序

## B 线实现边界

- 把 mutation 放在 service / workflow 层，而不是直接堆在 route
- 保持状态变更、activity 写入和 wakeup 副作用顺序可追踪

## 验收 demo

- Demo 1：演示一个完整 issue / approval mutation 流程
- Demo 2：展示相关 activity 与副作用记录
- Demo 3：展示非法状态流转被拒绝
- Demo 4：展示 workflow 测试结果

## 待确认项

- activity payload 字段级兼容范围
- wakeup 入队失败时的最小处理策略
- run 相关基础状态流转是否与 issue mutation 一起落地

## Step 3 完成后再补

- 基于真实 shared types 的 mutation payload 边界
- issue / approval 第一批必须先实现的状态流转
- activity 写入的最小字段集
- 事务边界和副作用时序验证口径

## 当前不冻结

- chat mutation
- 复杂运营后台 mutation
- 全量审计 payload 细节
