# Step 10 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先把治理与系统收口模块拆清楚，不在这一步把所有系统性能力一次冻结到生产级。等业务、执行、协作、资源模块逐步落地后，再把配置、上下文、预算 / 成本 / 活动治理的最终口径收紧。

## 目标

收口以下横切治理能力：

- 配置模型
- proxy / actor context
- budget / cost / activity 治理

这一步的目标是把跨模块规则统一起来，避免继续散落在各业务实现里。

## 本阶段范围

- `server/config.py`
- deployment mode / database / storage / runtime / workspace / resource 配置入口
- proxy context / actor context 注入与消费
- budget / cost / activity 归集与治理

## A 线必须先冻结的内容

以下内容当前仍是草稿收口方向：

- 统一配置模型的最小字段分层
- proxy / actor context 的最小语义与进入点
- budget / cost / activity 的统一归集口径
- 哪些治理规则必须在 route / service / background 中统一生效

## B 线实现边界

- 配置必须集中，不允许继续散到各模块自己读 env
- proxy / actor context 不得混入业务 payload
- budget / cost / activity 不得在各模块中各自解释口径
- 先建立统一入口，再补完整统计 / 治理细节

## 验收 demo

- Demo 1：展示配置模型覆盖 database / storage / runtime / workspace
- Demo 2：展示 proxy / actor context 参与请求或后台任务的一条真实链路
- Demo 3：展示 budget / cost / activity 的统一归集方式
- Demo 4：展示 contract / typecheck 结果

## 待确认项

- proxy / actor context 在 HTTP 与后台任务中的统一进入方式
- budget / cost 是否需要先冻结最小聚合模型
- activity 在治理层与业务层的边界切分
- 配置模型是一次性收口还是按子模块渐进补齐

## Step 9 完成后再补

- 统一配置模型的字段级清单
- proxy / actor context 的测试矩阵
- budget / cost / activity 的最终归集断言
- 哪些系统级治理规则必须阻止发布

## 当前不冻结

- observability / recovery / failover 的最终收口
- compatibility diff 工具输入输出格式
- 全量生产运维体系
