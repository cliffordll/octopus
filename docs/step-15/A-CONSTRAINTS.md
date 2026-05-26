# Step 15 A Constraints

## 当前状态

当前文件是草稿版本。

用途是先把可观测性、恢复能力与兼容差异比对模块的最终收口方向定住，不在这一步提前展开生产级全部运维体系。等前序模块基本跑通后，再把风险最高的故障路径与回归口径收紧。

## 目标

收口以下系统稳定性能力：

- observability
- recovery / failover
- compatibility diff

## 本阶段范围

- `server/observability/`
- recovery / failover 逻辑
- compatibility diff 与回归测试工具
- wrong-route / wrong-pod / lease 失效 / workspace / runtime / storage 故障路径

## A 线必须先冻结的内容

- 最低可接受的观测证据类型
- 必须进入回归集的故障路径
- compatibility diff 的最小对照范围
- 哪些高风险不兼容必须阻止合并或发布

## B 线实现边界

- 观测、恢复和兼容 diff 要落成真正可执行能力，不是只写文档
- 故障路径必须能被测试或脚本验证
- 不在这一步扩展与兼容目标无关的额外平台能力

## 验收 demo

- Demo 1：演示日志、指标或追踪中的至少一种真实观测证据
- Demo 2：演示 failover、lease 失效或恢复行为
- Demo 3：演示 compatibility diff 与关键回归测试
- Demo 4：展示系统是否达到稳定扩展基线

## 待确认项

- 先落日志、指标还是追踪
- compatibility diff 的输入输出形式
- 最低回归测试覆盖范围

## 当前不冻结

- 全量生产运维体系
- UI 层诊断工具
- 与兼容目标无关的增强功能
